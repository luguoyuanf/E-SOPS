"""Capacity, station progression and auditable deletion on the fixed MySQL test database."""
import uuid

import pytest
from fastapi import HTTPException

from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import ProductionReport, Terminal
from app.modules.esop.public_api.terminal_dto import (
    ReportChangeReview,
    ReportDeleteInput,
)
from app.modules.esop.report_change_routes import (
    request_report_deletion,
    review_report_change,
    terminal_reports,
)
from app.modules.esop.report_routes import (
    _progress,
    report_revisions,
    submit_web_report,
)
from app.modules.esop.terminal_routes import _active_tasks
from app.platform.web_api import Principal, TenantContext
from tests_dialects.test_web_reporting import task as task


def prepare(task):
    terminal = Terminal(tenant_id=task.uow.tenant_id, device_code='delete-' + uuid.uuid4().hex, station_id=task.station.id)
    task.uow.session.add(terminal)
    task.uow.session.flush()
    task.users.can_correct_production_reports = lambda user, tenant: True
    device = DeviceIdentity(tenant_id=task.uow.tenant_id, terminal_id=terminal.id)
    tenant = TenantContext(tenant_id=task.uow.tenant_id, tenant_code='TEST', user_id=task.principal.id)
    saved = submit_web_report(task.body, task.uow, task.principal, task.users)
    body = ReportDeleteInput(request_id=uuid.uuid4(), expected_revision=0, reason='重复录入申请撤销')
    return terminal, device, tenant, saved, body


def test_delete_request_keeps_totals_until_approval_then_reverses_once(task):
    terminal, device, tenant, saved, body = prepare(task)
    change = request_report_deletion(saved.id, body, task.uow.session, device, task.principal, tenant, task.users)
    assert change.kind == 'delete' and change.status == 'pending'
    assert request_report_deletion(saved.id, body, task.uow.session, device, task.principal, tenant, task.users).id == change.id
    assert _progress(task.uow.session, task.order).good_total == 1
    assert terminal_reports(task.uow.session, device, task.principal, tenant, task.users).items[0].change_kind == 'delete'
    result = review_report_change(change.id, ReportChangeReview(approve=True), task.uow, task.principal, task.users)
    assert result.status == 'approved'
    assert _progress(task.uow.session, task.order).good_total == 0
    assert _progress(task.uow.session, task.order).input_total == 0
    row = task.uow.session.get(ProductionReport, saved.id)
    assert row.is_deleted and row.revision == 1 and row.good_qty == 1
    assert terminal_reports(task.uow.session, device, task.principal, tenant, task.users).total == 0
    history = report_revisions(saved.id, task.uow).items
    assert history[0].before['is_deleted'] is False and history[0].after['is_deleted'] is True
    assert request_report_deletion(saved.id, body, task.uow.session, device, task.principal, tenant, task.users).id == change.id
    with pytest.raises(HTTPException) as error:
        review_report_change(change.id, ReportChangeReview(approve=True), task.uow, task.principal, task.users)
    assert error.value.status_code == 409
    assert report_revisions(saved.id, task.uow).total == 1
    # Freed capacity can be used again; the deleted fact never adds to new totals.
    updated = submit_web_report(task.body.model_copy(update={'request_id': uuid.uuid4(), 'input_qty': 2, 'good_qty': 2}), task.uow, task.principal, task.users)
    assert updated.good_qty == 2 and _progress(task.uow.session, task.order).good_total == 2


def test_delete_rejection_keeps_original_and_allows_another_request(task):
    terminal, device, tenant, saved, body = prepare(task)
    change = request_report_deletion(saved.id, body, task.uow.session, device, task.principal, tenant, task.users)
    review_report_change(change.id, ReportChangeReview(approve=False, note='数量属实'), task.uow, task.principal, task.users)
    assert not task.uow.session.get(ProductionReport, saved.id).is_deleted
    assert _progress(task.uow.session, task.order).good_total == 1
    assert request_report_deletion(saved.id, body.model_copy(update={'request_id': uuid.uuid4()}), task.uow.session, device, task.principal, tenant, task.users).status == 'pending'


def test_delete_is_owner_scoped_and_requires_manager_review(task):
    terminal, device, tenant, saved, body = prepare(task)
    with pytest.raises(HTTPException) as error:
        request_report_deletion(saved.id, body, task.uow.session, device, Principal(id=task.employee, is_superuser=False), tenant, task.users)
    assert error.value.status_code == 404
    change = request_report_deletion(saved.id, body, task.uow.session, device, task.principal, tenant, task.users)
    task.users.can_correct_production_reports = lambda user, tenant: False
    with pytest.raises(HTTPException) as error:
        review_report_change(change.id, ReportChangeReview(approve=True), task.uow, task.principal, task.users)
    assert error.value.status_code == 403
    assert not task.uow.session.get(ProductionReport, saved.id).is_deleted


def test_over_remaining_allowed_but_completed_operation_rejects_new_writes(task):
    terminal, device, tenant, saved, body = prepare(task)
    second = task.body.model_copy(update={'request_id': uuid.uuid4(), 'input_qty': 2, 'good_qty': 2})
    assert submit_web_report(second, task.uow, task.principal, task.users).good_qty == 2
    assert _progress(task.uow.session, task.order).good_total == 3
    with pytest.raises(HTTPException) as error:
        submit_web_report(task.body.model_copy(update={'request_id': uuid.uuid4()}), task.uow, task.principal, task.users)
    assert error.value.status_code == 409
    assert submit_web_report(second, task.uow, task.principal, task.users).good_qty == 2


def test_same_station_moves_to_next_incomplete_operation(task):
    assignment = task.release.assignments[0]
    next_operation = uuid.uuid4()
    task.release.assignments = [assignment, {**assignment, 'operation_id': str(next_operation), 'operation_name': '下一工序', 'sop_id': str(uuid.uuid4())}]
    terminal = Terminal(tenant_id=task.uow.tenant_id, device_code='next-operation-test', station_id=task.station.id)
    task.uow.session.add(terminal)
    task.uow.session.flush()
    assert _active_tasks(task.uow.session, terminal)[0][1]['operation_id'] == assignment['operation_id']
    submit_web_report(task.body.model_copy(update={'input_qty': 2, 'good_qty': 2}), task.uow, task.principal, task.users)
    assert _active_tasks(task.uow.session, terminal)[0][1]['operation_id'] == str(next_operation)


def test_deletion_of_completed_plan_reverses_statistics_without_restarting_it(task):
    terminal, device, tenant, saved, body = prepare(task)
    submit_web_report(task.body.model_copy(update={'request_id': uuid.uuid4()}), task.uow, task.principal, task.users)
    assert task.plan.status == 'completed' and not task.release.is_active
    change = request_report_deletion(saved.id, body, task.uow.session, device, task.principal, tenant, task.users)
    review_report_change(change.id, ReportChangeReview(approve=True), task.uow, task.principal, task.users)
    assert _progress(task.uow.session, task.order).good_total == 1
    assert task.plan.status == 'completed' and not task.release.is_active


def test_concurrent_report_writes_are_serialized_and_may_exceed_target():
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date
    from threading import Barrier

    from sqlmodel import Session, select

    from app.core.database import engine
    from app.modules.esop.infrastructure.models import WorkRelease
    from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
    from app.modules.esop.report_routes import _lock_release_for_report_write

    tenant_id, actor, operation = [uuid.uuid4() for _ in range(3)]
    release = WorkRelease(tenant_id=tenant_id, plan_id=uuid.uuid4(), order_id=uuid.uuid4(),
                          line_id=uuid.uuid4(), product_id=uuid.uuid4(), quantity=1,
                          due_date=date.today(), published_by=actor)
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant_id):
        session.add(release)
        session.commit()
        release_id, order_id = release.id, release.order_id
    ready = Barrier(2)

    def report():
        with Session(engine) as session, EsopTenantUnitOfWork(session, tenant_id):
            ready.wait(timeout=15)
            try:
                _lock_release_for_report_write(session, release_id)
                session.add(ProductionReport(tenant_id=tenant_id, request_id=uuid.uuid4().hex,
                    request_hash='capacity-test', staff_user_id=actor, staff_name='并发验收',
                    release_id=release_id, order_id=order_id, order_code='CAPACITY-TEST',
                    station_id=uuid.uuid4(), station_position=1, operation_id=operation,
                    sop_id=uuid.uuid4(), sop_version=1, sop_title='容量验收', input_qty=1, good_qty=1))
                session.commit()
                return 'saved'
            except HTTPException as error:
                session.rollback()
                return error.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: report(), range(2)))
        assert results == ['saved', 'saved']
        with Session(engine) as session, EsopTenantUnitOfWork(session, tenant_id):
            rows = session.exec(select(ProductionReport)).all()
            assert sum(row.good_qty + row.defect_qty for row in rows) == 2
    finally:
        with Session(engine) as session, EsopTenantUnitOfWork(session, tenant_id):
            for model in [ProductionReport, WorkRelease]:
                for row in session.exec(select(model)).all():
                    session.delete(row)
            session.commit()
