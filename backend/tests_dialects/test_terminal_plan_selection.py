"""An operator can switch between published orders without losing the old task."""

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.modules.erp.infrastructure.models import Product, ProductCategory, ProductUnit
from app.modules.erp.infrastructure.tenant_uow import ErpTenantUnitOfWork
from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import (
    ALL_MODELS,
    ProductionOrder,
    ProductionPlan,
    ProductionPlanGroup,
    ProductionReport,
    Station,
    Terminal,
    WorkRelease,
    WorkReleaseAssignment,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.plan_scheduler import advance_due_plans, station_can_start_plan
from app.modules.esop.public_api.terminal_dto import ReportInput
from app.modules.esop.report_routes import submit_report
from app.modules.esop.terminal_routes import (
    _active_tasks,
    select_terminal_production_plan,
    terminal_production_plans,
)
from app.modules.terminal_plan_query import terminal_plan_page
from app.platform.public_api.users import UserSummary
from app.platform.web_api import Principal, TenantContext


def test_station_selection_controls_display_and_reporting(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None, "erp": None}},
    )
    event.listen(engine, "connect", lambda connection, _record: connection.create_function(
        "set_config", 3, lambda _name, value, _local: value,
    ))
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS] +
                                 [ProductCategory.__table__, ProductUnit.__table__, Product.__table__])
    tenant, staff, line, operation, sop = [uuid.uuid4() for _ in range(5)]
    principal = Principal(id=staff, is_superuser=False)
    context = TenantContext(tenant_id=tenant, tenant_code="TEST", user_id=staff)
    monkeypatch.setattr(
        "app.modules.esop.terminal_routes.current_assignment",
        lambda session, release, assignment: assignment,
    )
    monkeypatch.setattr(
        "app.modules.esop.terminal_routes.product_directory_for_tenant",
        lambda session, tenant_id: SimpleNamespace(get=lambda product_id: SimpleNamespace(name="产品", model="M1")),
    )
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
        station = Station(tenant_id=tenant, line_id=line, position=1, row=1, column=1)
        terminal = Terminal(tenant_id=tenant, device_code="switch-test", station_id=station.id)
        assignment = {
            "station_id": str(station.id), "station_position": 1,
            "operation_id": str(operation), "operation_name": "装配",
            "sop_id": str(sop), "sop_title": "装配", "sop_version": 1,
        }
        rows = []
        for number in (1, 2):
            order = ProductionOrder(tenant_id=tenant, code=f"MO-{number}", product_id=uuid.uuid4(),
                                    quantity=10, due_date=date(2026, 11, 2))
            plan = ProductionPlan(tenant_id=tenant, code=f"PLAN-{number}", order_id=order.id,
                                  quantity=10, line_id=line, status="published", assignments=[assignment])
            release = WorkRelease(tenant_id=tenant, plan_id=plan.id, order_id=order.id,
                                  line_id=line, product_id=order.product_id, quantity=10,
                                  due_date=order.due_date, published_by=staff, assignments=[assignment])
            with ErpTenantUnitOfWork(session, tenant):
                session.add(Product(tenant_id=tenant, id=order.product_id, code=f"P-{number}",
                                    name="产品", model="M1", category_id=uuid.uuid4(),
                                    unit_id=uuid.uuid4()))
            session.add(WorkReleaseAssignment(
                tenant_id=tenant, release_id=release.id, ordinal=0,
                station_id=station.id, operation_id=operation, operation_name="装配",
            ))
            rows.append((order, plan, release))
            session.add_all([order, plan, release])
        group = ProductionPlanGroup(tenant_id=tenant, name="跨任务切换", created_by=staff,
                                    switch_mode="independent")
        rows[0][1].group_id, rows[0][1].group_position = group.id, 0
        rows[1][1].group_id, rows[1][1].group_position = group.id, 1
        session.add(group)
        session.add_all([station, terminal])
        session.flush()
        station.current_release_id = rows[0][2].id
        session.flush()
        identity = DeviceIdentity(tenant_id=tenant, terminal_id=terminal.id)

        listed = terminal_production_plans(session, identity, principal, context)
        assert listed["total"] == 2
        statements = []
        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT") and "set_config" not in statement:
                statements.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            assert terminal_plan_page(session, tenant, station, category="active", keyword="",
                                      page=1, page_size=1)["total"] == 2
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(statements) == 2
        filtered = terminal_plan_page(session, tenant, station, category="active", keyword="MO-1",
                                      page=1, page_size=30)
        assert filtered["total"] == 1 and filtered["items"][0]["orderCode"] == "MO-1"
        assert {item["orderCode"] for item in listed["items"]} == {"MO-1", "MO-2"}
        assert all(item["orderQty"] == 10 and item["dueDate"] == date(2026, 11, 2)
                   for item in listed["items"])
        with pytest.raises(HTTPException) as foreign:
            select_terminal_production_plan(
                rows[1][2].id, session, identity, principal,
                TenantContext(tenant_id=uuid.uuid4(), tenant_code="OTHER", user_id=staff),
            )
        assert foreign.value.status_code == 403
        assert not station_can_start_plan(session, rows[1][1], station.id)
        select_terminal_production_plan(rows[1][2].id, session, identity, principal, context)
        assert station.selected_release_id == rows[1][2].id
        assert _active_tasks(session, terminal, advance_cursor=True)[0][0].id == rows[1][2].id
        assert station.current_release_id == rows[0][2].id

        users = SimpleNamespace(get_users=lambda ids: [UserSummary(id=staff, full_name="员工", is_active=True)])
        def report(index):
            order, _, release = rows[index]
            return submit_report(session, identity, principal, context, users, ReportInput(
                requestId=str(uuid.uuid4()), releaseId=release.id, orderId=order.id,
                sopId=sop, inputQty=1, goodQty=1, defectQty=0,
            ))

        with pytest.raises(HTTPException) as stale:
            report(0)
        assert stale.value.status_code == 409
        saved = report(1)
        assert saved.release_id == rows[1][2].id
        assert station.selected_release_id == rows[1][2].id
        assert station.current_release_id == rows[0][2].id
        assert session.exec(select(ProductionReport)).all()[0].order_code == "MO-2"
        select_terminal_production_plan(rows[0][2].id, session, identity, principal, context)
        assert _active_tasks(session, terminal, advance_cursor=True)[0][0].id == rows[0][2].id
        assert report(0).release_id == rows[0][2].id
        assert {row.order_code for row in session.exec(select(ProductionReport)).all()} == {"MO-1", "MO-2"}
        station.current_release_id = rows[1][2].id
        session.flush()
        advance_due_plans(session)
        assert rows[0][1].status == "published" and rows[0][2].is_active
        station.current_release_id = rows[0][2].id
        session.flush()
        select_terminal_production_plan(rows[1][2].id, session, identity, principal, context)
        submit_report(session, identity, principal, context, users, ReportInput(
            requestId=str(uuid.uuid4()), releaseId=rows[1][2].id, orderId=rows[1][0].id,
            sopId=sop, inputQty=9, goodQty=9, defectQty=0,
        ))
        assert rows[1][1].status == "completed"
        assert terminal_production_plans(session, identity, principal, context)["total"] == 1
        completed = terminal_production_plans(
            session, identity, principal, context, category="completed",
        )
        assert completed["total"] == 1
        assert completed["items"][0]["orderCode"] == "MO-2"
        assert completed["items"][0]["canSwitch"] is False
        assert _active_tasks(session, terminal, advance_cursor=True)[0][0].id == rows[0][2].id
        assert station.selected_release_id is None
