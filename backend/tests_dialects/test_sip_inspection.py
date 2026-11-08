"""SIP can inspect reported pieces in parts without double counting."""

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
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
    ProductionReport,
    SipInspection,
    Station,
    Terminal,
    WorkRelease,
    WorkReleaseAssignment,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.migrations.mysql_versions.mysql_esop_0038_release_assignments import (
    upgrade as upgrade_assignments,
)
from app.modules.esop.sip_routes import (
    SipInput,
    admin_sip_inspections,
    admin_sip_plans,
    ensure_report_inspection_balance,
    submit_sip,
    terminal_sip_plans,
)
from app.platform.web_api import Principal, TenantContext


def test_partial_sip_quantity_and_tenant_boundary():
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
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
        station = Station(tenant_id=tenant, line_id=line, position=1, row=1, column=1)
        terminal = Terminal(tenant_id=tenant, device_code="sip-test", station_id=station.id)
        order = ProductionOrder(tenant_id=tenant, code="MO-SIP", product_id=uuid.uuid4(),
                                quantity=10, due_date=date(2026, 11, 4))
        with ErpTenantUnitOfWork(session, tenant):
            session.add(Product(tenant_id=tenant, id=order.product_id, code="P-SIP", name="成片",
                                category_id=uuid.uuid4(), unit_id=uuid.uuid4()))
        assignment = {"station_id": str(station.id), "operation_id": str(operation),
                      "operation_name": "成片工序", "sop_id": str(sop)}
        plan = ProductionPlan(tenant_id=tenant, code="PLAN-SIP", order_id=order.id,
                              quantity=10, line_id=line, status="published", assignments=[assignment])
        release = WorkRelease(tenant_id=tenant, plan_id=plan.id, order_id=order.id,
                              line_id=line, product_id=order.product_id, quantity=10,
                              due_date=order.due_date, published_by=staff, assignments=[assignment])
        report = ProductionReport(
            tenant_id=tenant, terminal_id=terminal.id, request_id="report-sip", request_hash="x",
            staff_user_id=staff, staff_name="员工", release_id=release.id, order_id=order.id,
            order_code=order.code, station_id=station.id, station_position=1,
            operation_id=operation, sop_id=sop, sop_version=1, sop_title="成片工序",
            input_qty=5, good_qty=3, defect_qty=2,
        )
        read_row = WorkReleaseAssignment(tenant_id=tenant, release_id=release.id, ordinal=0,
                                         station_id=station.id, operation_id=operation,
                                         operation_name="成片工序")
        session.add_all([station, terminal, order, plan, release, report, read_row])
        session.commit()
        device = DeviceIdentity(tenant_id=tenant, terminal_id=terminal.id)
        listed = terminal_sip_plans(session, device, principal, context)
        assert listed["items"][0]["reportedQty"] == 5
        assert listed["items"][0]["goodQty"] == 3
        assert listed["items"][0]["badQty"] == 2
        first = SipInput(requestId="sip-1", releaseId=release.id, operationId=operation, quantity=2)
        saved = submit_sip(first, session, device, principal, context)
        assert submit_sip(first, session, device, principal, context)["id"] == saved["id"]
        assert terminal_sip_plans(session, device, principal, context)["items"][0]["availableQty"] == 3
        submit_sip(SipInput(requestId="sip-2", releaseId=release.id, operationId=operation,
                            quantity=3), session, device, principal, context)
        history = admin_sip_inspections(
            SimpleNamespace(session=session, tenant_id=tenant),
            release_id=release.id, operation_id=operation, station_id=station.id, page_size=1,
        )
        assert history["total"] == 2 and len(history["items"]) == 1
        assert session.exec(select(SipInspection)).all()[0].report_allocations[0]["reportId"] == str(report.id)
        with pytest.raises(HTTPException) as excess:
            submit_sip(SipInput(requestId="sip-3", releaseId=release.id, operationId=operation,
                                quantity=1), session, device, principal, context)
        assert excess.value.status_code == 409
        with pytest.raises(HTTPException) as correction:
            ensure_report_inspection_balance(session, report, 4)
        assert correction.value.status_code == 409
        with pytest.raises(HTTPException) as foreign:
            terminal_sip_plans(session, device, principal, TenantContext(
                tenant_id=uuid.uuid4(), tenant_code="OTHER", user_id=staff,
            ))
        assert foreign.value.status_code == 403


def test_admin_sip_plan_queries_do_not_grow_with_stations_and_plans():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None, "erp": None}},
    )
    event.listen(engine, "connect", lambda connection, _record: connection.create_function(
        "set_config", 3, lambda _name, value, _local: value,
    ))
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS] +
                                 [ProductCategory.__table__, ProductUnit.__table__, Product.__table__])
    tenant, line, staff, operation, product = [uuid.uuid4() for _ in range(5)]
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
        with ErpTenantUnitOfWork(session, tenant):
            session.add(Product(tenant_id=tenant, id=product, code="P-SIP", name="成片",
                                category_id=uuid.uuid4(), unit_id=uuid.uuid4()))
        stations = [Station(tenant_id=tenant, line_id=line, position=i + 1,
                            row=1, column=i + 1) for i in range(3)]
        session.add_all(stations)
        for i in range(4):
            order = ProductionOrder(tenant_id=tenant, code=f"MO-{i}", product_id=product,
                                    quantity=10, due_date=date(2026, 11, 4))
            assignments = [{"station_id": str(station.id), "operation_id": str(operation)}
                           for station in stations]
            plan = ProductionPlan(tenant_id=tenant, code=f"PLAN-{i}", order_id=order.id,
                                  quantity=10, line_id=line, status="published", assignments=assignments)
            release = WorkRelease(tenant_id=tenant, plan_id=plan.id, order_id=order.id,
                                  line_id=line, product_id=product, quantity=10,
                                  due_date=order.due_date, published_by=staff, assignments=assignments)
            read_rows = [WorkReleaseAssignment(
                tenant_id=tenant, release_id=release.id, ordinal=index,
                station_id=station.id, operation_id=operation,
            ) for index, station in enumerate(stations)]
            session.add_all([order, plan, release, *read_rows])
        session.commit()
        statements = []
        def count_select(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT") and "set_config" not in statement:
                statements.append(statement)
        event.listen(engine, "before_cursor_execute", count_select)
        try:
            result = admin_sip_plans(SimpleNamespace(session=session, tenant_id=tenant), page_size=5)
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert result["total"] == 12 and len(result["items"]) == 5
        assert len(statements) == 2
        second = admin_sip_plans(SimpleNamespace(session=session, tenant_id=tenant), page=2, page_size=5)
        assert second["total"] == 12 and len(second["items"]) == 5
        first_keys = {(row["releaseId"], row["stationId"]) for row in result["items"]}
        assert first_keys.isdisjoint((row["releaseId"], row["stationId"]) for row in second["items"])
        filtered = admin_sip_plans(SimpleNamespace(session=session, tenant_id=tenant), keyword="MO-1")
        assert filtered["total"] == 3
        assert all(row["orderCode"] == "MO-1" for row in filtered["items"])
        assert admin_sip_plans(SimpleNamespace(session=session, tenant_id=tenant), category="completed")["total"] == 0


def test_existing_release_assignments_are_backfilled_without_loss():
    engine = create_engine("sqlite://")
    tenant, release, station, operation = [uuid.uuid4() for _ in range(4)]
    release_table = sa.Table(
        "esop_work_release", sa.MetaData(), sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid()), sa.Column("assignments", sa.JSON()),
    )
    release_table.create(engine)
    snapshot = [
        {"station_id": str(station), "operation_id": str(operation), "operation_name": "成片"},
        {"station_id": str(station), "operation_id": str(uuid.uuid4()), "operation_name": "复检"},
    ]
    with engine.begin() as connection:
        connection.execute(release_table.insert(), [
            {"id": release, "tenant_id": tenant, "assignments": snapshot},
            {"id": uuid.uuid4(), "tenant_id": tenant, "assignments": []},
        ])
        with Operations.context(MigrationContext.configure(connection)):
            upgrade_assignments()
        rows = connection.execute(sa.text(
            "SELECT release_id, ordinal, tenant_id, station_id, operation_id, operation_name "
            "FROM esop_work_release_assignment ORDER BY ordinal"
        )).all()
    assert len(rows) == len(snapshot)
    assert [row.ordinal for row in rows] == [0, 1]
    assert [row.operation_name for row in rows] == ["成片", "复检"]
    assert all(row.release_id == release.hex and row.tenant_id == tenant.hex for row in rows)
