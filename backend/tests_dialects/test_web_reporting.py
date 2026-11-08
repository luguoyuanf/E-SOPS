"""Web reporting uses the fixed MySQL test dependency; every synthetic write rolls back."""
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session

from app.core.database import engine
from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import (
    ProductionLine,
    ProductionOrder,
    ProductionPlan,
    ProductionReport,
    Station,
    Terminal,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.terminal_dto import ReportInput, WebReportInput
from app.modules.esop.report_routes import (
    submit_report,
    submit_web_report,
    web_report_options,
)
from app.platform.public_api.users import UserOption, UserSummary
from app.platform.web_api import Principal, TenantContext


@pytest.fixture
def task():
    tenant, actor, employee, product, operation, sop = [uuid.uuid4() for _ in range(6)]
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
            with EsopTenantUnitOfWork(session, tenant) as uow:
                line = ProductionLine(tenant_id=tenant, workshop_id=uuid.uuid4(), code='WEB-TEST', name='Web test')
                station = Station(tenant_id=tenant, line_id=line.id, position=1, row=1, column=1)
                order = ProductionOrder(tenant_id=tenant, code='WEB-TEST', product_id=product, quantity=2, due_date=date.today())
                assignment = {'station_id': str(station.id), 'station_position': 1, 'operation_id': str(operation), 'operation_name': '装配', 'sop_id': str(sop), 'sop_title': '报工测试', 'sop_version': 3}
                plan = ProductionPlan(tenant_id=tenant, code='WEB-TEST', order_id=order.id, quantity=2, line_id=line.id, status='published', assignments=[assignment], created_by=actor)
                release = WorkRelease(tenant_id=tenant, plan_id=plan.id, order_id=order.id, line_id=line.id, product_id=product, quantity=2, due_date=date.today(), published_by=actor, assignments=[assignment])
                session.add_all([line, station, order, plan, release])
                session.flush()
                options = [UserOption(id=actor, label='操作员'), UserOption(id=employee, label='员工')]
                users = SimpleNamespace(
                    is_tenant_administrator=lambda user, tenant: False,
                    list_tenant_options=lambda tenant: options,
                    get_users=lambda ids: [UserSummary(id=id, full_name='员工', is_active=True) for id in ids],
                )
                body = WebReportInput(request_id=uuid.uuid4(), release_id=release.id, station_id=station.id, operation_id=operation, sop_id=sop, input_qty=1, good_qty=1)
                yield SimpleNamespace(uow=uow, principal=Principal(id=actor, is_superuser=False), users=users, body=body, plan=plan, release=release, station=station, employee=employee, order=order)
            session.rollback()
        transaction.rollback()


def test_self_reporting_without_terminal_is_idempotent_and_keeps_actor(task):
    first = submit_web_report(task.body, task.uow, task.principal, task.users)
    assert first.terminal_id is None
    assert first.submitted_by == task.principal.id == first.staff_user_id
    assert first.sop_version == 3
    task.release.is_active = False
    task.uow.session.flush()
    assert submit_web_report(task.body, task.uow, task.principal, task.users).id == first.id
    with pytest.raises(HTTPException) as error:
        submit_web_report(task.body.model_copy(update={'good_qty': 2}), task.uow, task.principal, task.users)
    assert error.value.status_code == 409


def test_only_administrators_can_report_for_another_employee(task):
    body = task.body.model_copy(update={'staff_user_id': task.employee})
    with pytest.raises(HTTPException) as error:
        submit_web_report(body, task.uow, task.principal, task.users)
    assert error.value.status_code == 403
    ordinary = web_report_options(task.uow, task.principal, task.users)
    assert not ordinary.can_select_staff and [row.value for row in ordinary.staff] == [task.principal.id]
    task.users.is_tenant_administrator = lambda user, tenant: True
    admin = web_report_options(task.uow, task.principal, task.users)
    assert admin.can_select_staff and len(admin.staff) == 2
    saved = submit_web_report(body, task.uow, task.principal, task.users)
    assert saved.staff_user_id == task.employee and saved.submitted_by == task.principal.id


@pytest.mark.parametrize('invalid', ['foreign_release', 'station', 'operation', 'sop', 'foreign_employee', 'inactive_employee', 'paused', 'zero'])
def test_invalid_web_reporting_is_rejected(task, invalid):
    task.users.is_tenant_administrator = lambda user, tenant: True
    update = {}
    if invalid == 'foreign_release':
        update['release_id'] = uuid.uuid4()
    if invalid in {'station', 'operation', 'sop'}:
        update[invalid + '_id'] = uuid.uuid4()
    if invalid == 'foreign_employee':
        update['staff_user_id'] = uuid.uuid4()
    if invalid == 'inactive_employee':
        task.users.get_users = lambda ids: [UserSummary(id=id, is_active=False) for id in ids]
    if invalid == 'paused':
        task.plan.status = 'paused'
        task.uow.session.flush()
    if invalid == 'zero':
        update['good_qty'] = 0
    with pytest.raises(HTTPException) as error:
        submit_web_report(task.body.model_copy(update=update), task.uow, task.principal, task.users)
    assert error.value.status_code in {403, 404, 409, 422}
    with pytest.raises(ValidationError):
        WebReportInput(**{**task.body.model_dump(), 'input_qty': -1})


def test_web_and_terminal_reporting_share_completion_totals(task):
    submit_web_report(task.body, task.uow, task.principal, task.users)
    terminal = Terminal(tenant_id=task.uow.tenant_id, device_code='web-regression-test', station_id=task.station.id)
    task.uow.session.add(terminal)
    task.uow.session.flush()
    body = ReportInput(requestId=str(uuid.uuid4()), releaseId=task.release.id, orderId=task.order.id, sopId=task.body.sop_id, inputQty=1, goodQty=1)
    saved = submit_report(task.uow.session, DeviceIdentity(tenant_id=task.uow.tenant_id, terminal_id=terminal.id), task.principal, TenantContext(tenant_id=task.uow.tenant_id, tenant_code='TEST', user_id=task.principal.id), task.users, body)
    assert saved.terminal_id == terminal.id and saved.submitted_by is None
    assert task.uow.session.get(ProductionPlan, task.plan.id).status == 'completed'
    assert task.uow.session.get(ProductionReport, saved.id).good_qty == 1


def test_unbound_station_is_not_a_reporting_option(task):
    unbound = Station(tenant_id=task.uow.tenant_id, line_id=task.station.line_id, position=2, row=1, column=2)
    task.uow.session.add(unbound)
    task.uow.session.flush()
    options = web_report_options(task.uow, task.principal, task.users)
    assert [(row.station_id, row.operation_id) for row in options.tasks] == [(task.station.id, task.body.operation_id)]
    with pytest.raises(HTTPException) as error:
        submit_web_report(task.body.model_copy(update={'station_id': unbound.id}), task.uow, task.principal, task.users)
    assert error.value.status_code == 403


def test_terminal_task_information_uses_release_metrics_and_current_operation(task, monkeypatch):
    from app.modules.esop import report_routes, terminal_routes

    submit_web_report(task.body, task.uow, task.principal, task.users)
    terminal = Terminal(tenant_id=task.uow.tenant_id, device_code='task-progress-test', station_id=task.station.id)
    task.uow.session.add(terminal)
    # A second unreported operation keeps overall progress at zero, despite 50% on this operation.
    assignment = task.release.assignments[0]
    task.release.assignments = [assignment, {**assignment, 'operation_id': str(uuid.uuid4())}]
    task.uow.session.flush()
    monkeypatch.setattr(terminal_routes, '_active_tasks', lambda session, terminal, **kwargs: [(task.release, assignment)])
    monkeypatch.setattr(terminal_routes, 'current_assignment', lambda session, release, stored: stored)
    monkeypatch.setattr(report_routes, 'product_directory_for_tenant', lambda session, tenant: SimpleNamespace(get=lambda id: SimpleNamespace(code='P01', name='测试产品', model='M-100')))
    rows = report_routes.terminal_orders(task.uow.session, DeviceIdentity(tenant_id=task.uow.tenant_id, terminal_id=terminal.id))
    assert len(rows) == 1
    row = rows[0]
    assert row['productName'] == '测试产品' and row['productModel'] == 'M-100'
    assert row['planCode'] == task.plan.code and row['planQty'] == 2
    assert (row['operationInputQty'], row['operationGoodQty'], row['operationDefectQty']) == (1, 1, 0)
    assert row['completionRate'] == 0
