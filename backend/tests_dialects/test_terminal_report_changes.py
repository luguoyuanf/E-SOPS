"""Fixed test MySQL: effective quantities, review authority and terminal ownership."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import ProductionReport, Terminal
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.terminal_dto import (
    ReportChangeInput,
    ReportChangeReview,
)
from app.modules.esop.report_change_routes import (
    report_changes,
    request_report_change,
    review_report_change,
    terminal_reports,
)
from app.modules.esop.report_routes import (
    _progress,
    report_revisions,
    submit_web_report,
)
from app.platform.web_api import Principal, TenantContext
from tests_dialects.test_web_reporting import task as task


def setup(task):
    saved = submit_web_report(task.body, task.uow, task.principal, task.users)
    terminal = Terminal(tenant_id=task.uow.tenant_id, device_code='change-' + uuid.uuid4().hex, station_id=task.station.id)
    task.uow.session.add(terminal)
    task.uow.session.flush()
    task.users.can_correct_production_reports = lambda user, tenant: True
    tenant = TenantContext(tenant_id=task.uow.tenant_id, tenant_code='TEST', user_id=task.principal.id)
    return SimpleNamespace(
        row=saved, device=DeviceIdentity(tenant_id=tenant.tenant_id, terminal_id=terminal.id), tenant=tenant,
        body=ReportChangeInput(request_id=uuid.uuid4(), expected_revision=0, input_qty=2, good_qty=2, defect_qty=0, reason='补正数量'),
    )


def request(task, state, body=None, principal=None, tenant=None):
    return request_report_change(state.row.id, body or state.body, task.uow.session, state.device,
                                 principal or task.principal, tenant or state.tenant, task.users)


def test_request_pending_keeps_effective_totals_then_approval_applies_once(task):
    state = setup(task)
    change = request(task, state)
    assert change.status == 'pending' and change.order_code == task.order.code
    assert request(task, state).id == change.id
    assert task.uow.session.get(ProductionReport, state.row.id).good_qty == 1
    assert _progress(task.uow.session, task.order).good_total == 1
    rows = terminal_reports(task.uow.session, state.device, task.principal, state.tenant, task.users)
    assert rows.total == 1 and rows.items[0].change_status == 'pending'
    reviewed = review_report_change(change.id, ReportChangeReview(approve=True), task.uow, task.principal, task.users)
    assert reviewed.status == 'approved'
    assert _progress(task.uow.session, task.order).good_total == 2
    assert report_revisions(state.row.id, task.uow).total == 1
    assert request(task, state).id == change.id  # uncertain response retry after approval
    with pytest.raises(HTTPException) as error:
        review_report_change(change.id, ReportChangeReview(approve=True), task.uow, task.principal, task.users)
    assert error.value.status_code == 409
    assert report_revisions(state.row.id, task.uow).total == 1


def test_rejection_keeps_original_and_allows_resubmission(task):
    state = setup(task)
    change = request(task, state)
    rejected = review_report_change(change.id, ReportChangeReview(approve=False, note='核对后重新提交'), task.uow, task.principal, task.users)
    assert rejected.status == 'rejected'
    assert task.uow.session.get(ProductionReport, state.row.id).good_qty == 1
    assert report_revisions(state.row.id, task.uow).total == 0
    result = terminal_reports(task.uow.session, state.device, task.principal, state.tenant, task.users)
    assert result.items[0].change_reason == '核对后重新提交'
    assert request(task, state, state.body.model_copy(update={'request_id': uuid.uuid4()})).status == 'pending'


def test_ordinary_employee_cannot_review_or_list_requests(task):
    state = setup(task)
    change = request(task, state)
    task.users.can_correct_production_reports = lambda user, tenant: False
    for call in [lambda: report_changes(task.uow, task.principal, task.users),
                 lambda: review_report_change(change.id, ReportChangeReview(approve=True), task.uow, task.principal, task.users)]:
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 403


@pytest.mark.parametrize('invalid', ['other_employee', 'foreign_tenant', 'stale', 'zero', 'unchanged', 'pending', 'reused_key'])
def test_invalid_request_is_rejected(task, invalid):
    state = setup(task)
    principal, tenant, body = task.principal, state.tenant, state.body
    if invalid == 'other_employee':
        principal = Principal(id=task.employee, is_superuser=False)
    if invalid == 'foreign_tenant':
        tenant = TenantContext(tenant_id=uuid.uuid4(), tenant_code='OTHER', user_id=principal.id)
    if invalid == 'stale':
        body = body.model_copy(update={'expected_revision':
        5})
    if invalid == 'zero':
        body = body.model_copy(update={'input_qty': 0, 'good_qty': 0, 'defect_qty':
        0})
    if invalid == 'unchanged':
        body = body.model_copy(update={'input_qty': 1, 'good_qty': 1, 'defect_qty':
        0})
    if invalid in {'pending', 'reused_key'}:
        request(task, state)
        body = body.model_copy(update={'request_id': uuid.uuid4()}) if invalid == 'pending' else body.model_copy(update={'good_qty': 4})
    with pytest.raises(HTTPException) as error:
        request(task, state, body, principal, tenant)
    assert error.value.status_code in {403, 404, 409, 422}
    assert task.uow.session.get(ProductionReport, state.row.id).good_qty == 1


def test_station_and_tenant_scope_and_pagination(task):
    state = setup(task)
    first = terminal_reports(task.uow.session, state.device, task.principal, state.tenant, task.users, 1, 1)
    second = terminal_reports(task.uow.session, state.device, task.principal, state.tenant, task.users, 2, 1)
    assert first.total == 1 and len(first.items) == 1 and second.items == []
    other = terminal_reports(task.uow.session, state.device, Principal(id=task.employee, is_superuser=False), state.tenant, task.users)
    assert other.total == 0
    change = request(task, state)
    with Session(bind=task.uow.session.connection(), join_transaction_mode='create_savepoint') as session:
        with EsopTenantUnitOfWork(session, uuid.uuid4()) as uow:
            assert report_changes(uow, task.principal, task.users).total == 0
            with pytest.raises(HTTPException) as error:
                review_report_change(change.id, ReportChangeReview(approve=True), uow, task.principal, task.users)
            assert error.value.status_code == 404


def test_stale_approval_does_not_replace_newer_correction(task):
    from app.modules.esop.public_api.terminal_dto import ReportCorrectionInput
    from app.modules.esop.report_routes import correct_report
    state = setup(task)
    change = request(task, state)
    correct_report(state.row.id, ReportCorrectionInput(expected_revision=0, staff_user_id=task.principal.id, input_qty=2, good_qty=2, defect_qty=0, reason='经理核实'), task.uow, task.principal, task.users)
    with pytest.raises(HTTPException) as error:
        review_report_change(change.id, ReportChangeReview(approve=True), task.uow, task.principal, task.users)
    assert error.value.status_code == 409
    assert task.uow.session.get(ProductionReport, state.row.id).good_qty == 2


@pytest.mark.parametrize('code', ['director', 'general_manager', 'chairman'])
def test_senior_post_review_authority_is_tenant_local_and_revocable(code):
    from sqlmodel import select

    from app.core.database import engine
    from app.platform.core.authorization_models import Post, UserPost
    from app.platform.core.identity_models import User
    from app.platform.core.tenancy_models import TenantMembership
    from app.platform.tenant_uow import PlatformTenantUnitOfWork
    from app.platform.user_directory import SqlUserDirectory

    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
            member = session.exec(select(TenantMembership).where(TenantMembership.is_active)).first()
            with PlatformTenantUnitOfWork(session, member.tenant_id):
                user = User(username='review-' + uuid.uuid4().hex[:12], full_name='审核测试', hashed_password='not-for-login')
                session.add(user)
                session.flush()
                session.add(TenantMembership(user_id=user.id, tenant_id=member.tenant_id))
                post = session.exec(select(Post).where(Post.code == code)).first()
                if post is None:
                    post = Post(tenant_id=member.tenant_id, code=code, name='审核岗位测试', is_active=True)
                    session.add(post)
                    session.flush()
                session.add(UserPost(user_id=user.id, tenant_id=member.tenant_id, post_id=post.id))
                session.flush()
                directory = SqlUserDirectory(session)
                assert directory.can_correct_production_reports(user.id, member.tenant_id)
                assert not directory.can_correct_production_reports(user.id, uuid.uuid4())
                post.is_active = False
                session.flush()
                assert not directory.can_correct_production_reports(user.id, member.tenant_id)
            session.rollback()
        transaction.rollback()


def test_simultaneous_change_requests_create_only_one_pending_row(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlmodel import select

    from app.core.database import engine
    from app.modules.esop import report_change_routes as routes
    from app.modules.esop.infrastructure.models import ProductionReportChange
    from app.platform.public_api.users import UserSummary

    tenant_id, user_id, station_id = [uuid.uuid4() for _ in range(3)]
    terminal = Terminal(tenant_id=tenant_id, device_code='concurrency-' + uuid.uuid4().hex, station_id=station_id)
    row = ProductionReport(
        tenant_id=tenant_id, terminal_id=terminal.id, request_id=uuid.uuid4().hex, request_hash='test-only',
        staff_user_id=user_id, staff_name='并发测试', release_id=uuid.uuid4(), order_id=uuid.uuid4(),
        order_code='CONCURRENCY-TEST', station_id=station_id, station_position=1,
        operation_id=uuid.uuid4(), sop_id=uuid.uuid4(), sop_version=1, sop_title='并发测试', good_qty=1,
    )
    device = DeviceIdentity(tenant_id=tenant_id, terminal_id=terminal.id)
    principal = Principal(id=user_id, is_superuser=False)
    tenant = TenantContext(tenant_id=tenant_id, tenant_code='TEST', user_id=user_id)
    users = SimpleNamespace(get_users=lambda ids: [UserSummary(id=user_id, full_name='并发测试', is_active=True)])
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant_id):
        session.add_all([row, terminal])
        session.commit()
        report_id = row.id
    barrier = Barrier(2)
    original = routes._terminal

    def synchronized_terminal(session, device):
        result = original(session, device)
        barrier.wait(timeout=15)  # Both MySQL consistent-read snapshots precede either INSERT.
        return result

    monkeypatch.setattr(routes, '_terminal', synchronized_terminal)

    def submit():
        with Session(engine) as session:
            try:
                result = routes.request_report_change(report_id, ReportChangeInput(
                    request_id=uuid.uuid4(), expected_revision=0, input_qty=2, good_qty=2, defect_qty=0, reason='并发验收',
                ), session, device, principal, tenant, users)
                return result.status
            except HTTPException as error:
                session.rollback()
                return error.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        assert sorted(results, key=str) == [409, 'pending']
        with Session(engine) as session, EsopTenantUnitOfWork(session, tenant_id):
            changes = session.exec(select(ProductionReportChange)).all()
            assert len(changes) == 1 and changes[0].status == 'pending'
            assert session.get(ProductionReport, report_id).good_qty == 1
    finally:
        with Session(engine) as session, EsopTenantUnitOfWork(session, tenant_id):
            for model in [ProductionReportChange, ProductionReport, Terminal]:
                for entity in session.exec(select(model)).all():
                    session.delete(entity)
            session.commit()


@pytest.mark.parametrize('model', ['MODEL-100', None])
def test_terminal_report_product_metadata_and_tenant_product_port(task, model):
    from app.modules.erp.application.product_directory import SqlProductDirectory
    from app.modules.erp.infrastructure.models import (
        Product,
        ProductCategory,
        ProductUnit,
    )
    from app.modules.erp.infrastructure.tenant_uow import ErpTenantUnitOfWork

    state = setup(task)
    session = task.uow.session
    tenant_id = task.uow.tenant_id
    with ErpTenantUnitOfWork(session, tenant_id):
        category = ProductCategory(tenant_id=tenant_id, code='REPORT-MODEL', name='产品型号测试')
        unit = ProductUnit(tenant_id=tenant_id, code='REPORT-PIECE', name='件')
        session.add_all([category, unit])
        session.flush()
        session.add(Product(id=task.order.product_id, tenant_id=tenant_id,
                            code='REPORT-PRODUCT', name='报工产品', model=model,
                            category_id=category.id, unit_id=unit.id))
        session.flush()
    directory = SqlProductDirectory(session, tenant_id)
    assert directory.get(task.order.product_id).model == model
    assert directory.list()[0].model == model
    assert directory.tree()[1][0].model == model
    assert SqlProductDirectory(session, uuid.uuid4()).get(task.order.product_id) is None
    result = terminal_reports(session, state.device, task.principal, state.tenant, task.users)
    assert result.items[0].product_name == '报工产品'
    assert result.items[0].product_model == model
    assert result.model_dump()['items'][0]['product_model'] == model
