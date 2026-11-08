"""Screen totals, live orders and cross-day progress share tenant-scoped batch reads."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlmodel import Session

from app.core.database import engine
from app.modules.esop.dashboard_routes import read_esop_dashboard
from app.modules.esop.data_screen import build_data_screen
from app.modules.esop.infrastructure.models import (
    ProductionLine,
    ProductionOrder,
    ProductionPlan,
    ProductionReport,
    Station,
    WorkRelease,
    Workshop,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork


def test_screen_counts_unique_orders_and_uses_cumulative_latest_release(monkeypatch):
    now = datetime(2026, 11, 8, 8, tzinfo=UTC)
    monkeypatch.setattr(
        "app.modules.esop.dashboard_routes.get_datetime_utc", lambda: now
    )
    product, first, last, tenant = (uuid.uuid4() for _ in range(4))
    monkeypatch.setattr(
        "app.modules.esop.data_screen.product_directory_for_tenant",
        lambda *_: SimpleNamespace(
            list=lambda: [SimpleNamespace(id=product, name="测试产品")]
        ),
    )
    with Session(engine) as session:
        try:
            with EsopTenantUnitOfWork(session, tenant) as uow:
                workshop = Workshop(
                    tenant_id=tenant, code="SCREEN-ORDERS", name="Screen"
                )
                lines = [
                    ProductionLine(
                        tenant_id=tenant,
                        workshop_id=workshop.id,
                        code=f"SCREEN-{i}",
                        name=f"Line {i}",
                    )
                    for i in range(2)
                ]
                station = Station(
                    tenant_id=tenant, line_id=lines[0].id, position=1, row=1, column=1
                )
                orders = [
                    ProductionOrder(
                        tenant_id=tenant,
                        code=f"SCREEN-{i}",
                        product_id=product,
                        quantity=qty,
                        operation_ids=[str(first), str(last)],
                        due_date=(now + timedelta(days=due)).date(),
                    )
                    for i, qty, due in [(1, 100, -1), (2, 20, -1), (3, 10, 1)]
                ]
                plans = [
                    ProductionPlan(
                        tenant_id=tenant,
                        code=f"SCREEN-PLAN-{i}",
                        order_id=orders[order].id,
                        line_id=lines[line].id,
                        quantity=qty,
                        status=status,
                        start_at=now - timedelta(days=2),
                        end_at=now + timedelta(days=1),
                    )
                    for i, order, line, qty, status in [
                        (1, 0, 0, 60, "published"),
                        (2, 0, 1, 40, "published"),
                        (3, 1, 0, 20, "completed"),
                        (4, 0, 0, 200, "cancelled"),
                    ]
                ]
                releases = [
                    WorkRelease(
                        tenant_id=tenant,
                        plan_id=plan.id,
                        order_id=plan.order_id,
                        line_id=plan.line_id,
                        product_id=product,
                        quantity=plan.quantity,
                        due_date=now.date(),
                        version=2,
                        published_by=uuid.uuid4(),
                        assignments=[
                            {"operation_id": str(first)},
                            {"operation_id": str(last)},
                        ],
                    )
                    for plan in plans
                ]
                old = WorkRelease(
                    tenant_id=tenant,
                    plan_id=plans[0].id,
                    order_id=orders[0].id,
                    line_id=lines[0].id,
                    product_id=product,
                    quantity=60,
                    due_date=now.date(),
                    version=1,
                    published_by=uuid.uuid4(),
                    is_active=False,
                    assignments=[{"operation_id": str(last)}],
                )

                def report(release, operation, qty, when=now, deleted=False):
                    return ProductionReport(
                        tenant_id=tenant,
                        release_id=release.id,
                        order_id=release.order_id,
                        order_code="SCREEN",
                        station_id=station.id,
                        station_position=1,
                        request_id=str(uuid.uuid4()),
                        request_hash="x" * 64,
                        staff_user_id=uuid.uuid4(),
                        staff_name="test",
                        operation_id=operation,
                        sop_id=uuid.uuid4(),
                        sop_version=1,
                        sop_title="Screen",
                        input_qty=qty,
                        good_qty=qty,
                        defect_qty=0,
                        occurred_at=when,
                        is_deleted=deleted,
                    )

                reports = [
                    report(releases[0], first, 60),
                    report(releases[0], last, 20, now - timedelta(days=1)),
                    report(releases[0], last, 10),
                    report(releases[1], first, 40),
                    report(releases[1], last, 10),
                    report(releases[2], first, 20),
                    report(releases[2], last, 20),
                    report(releases[3], last, 999),
                    report(old, last, 999),
                    report(releases[0], last, 666, deleted=True),
                    report(releases[0], last, 777, now + timedelta(hours=1)),
                ]
                session.add_all(
                    [
                        workshop,
                        *lines,
                        station,
                        *orders,
                        *plans,
                        *releases,
                        old,
                        *reports,
                    ]
                )
                session.flush()
                base = read_esop_dashboard(uow)
                result = build_data_screen(uow, base, scoped=False)
                assert (
                    result.order_total,
                    result.order_running,
                    result.order_completed,
                    result.order_overdue,
                ) == (3, 1, 1, 1)
                assert len(result.running_orders) == 2
                assert all(
                    row.product_name == "测试产品" for row in result.running_orders
                )
                assert sorted(row.good_qty for row in result.running_orders) == [10, 30]
                progress = {row.line_id: row for row in result.line_progress}
                assert (
                    progress[lines[0].id].good_qty,
                    progress[lines[0].id].planned_qty,
                ) == (50, 80)
                assert (
                    progress[lines[1].id].good_qty,
                    progress[lines[1].id].planned_qty,
                ) == (10, 40)
                scoped = build_data_screen(
                    uow, read_esop_dashboard(uow, line_id=lines[1].id), scoped=True
                )
                assert (
                    scoped.order_total == scoped.order_running == 1
                    and len(scoped.running_orders) == 1
                )
            with EsopTenantUnitOfWork(session, uuid.uuid4()) as uow:
                empty = build_data_screen(uow, read_esop_dashboard(uow), scoped=False)
                assert empty.order_total == empty.order_running == 0
                assert empty.running_orders == empty.line_progress == []
        finally:
            session.rollback()
