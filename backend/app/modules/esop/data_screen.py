"""Batched order and cumulative plan metrics for the independent screen."""

from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlmodel import select

from app.modules.esop.infrastructure.models import (
    ProductionOrder,
    ProductionPlan,
    ProductionReport,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.dashboard_dto import (
    DataScreenDashboard,
    EsopDashboard,
    ScreenLineProgress,
    ScreenRunningOrder,
)
from app.modules.product_directory import product_directory_for_tenant


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def build_data_screen(
    uow: EsopTenantUnitOfWork, dashboard: EsopDashboard, *, scoped: bool
) -> DataScreenDashboard:
    session = uow.session
    lines = {row.id: row.name for row in dashboard.lines}
    query = select(ProductionOrder)
    if scoped:
        ids = select(ProductionPlan.order_id).where(
            ProductionPlan.line_id.in_(lines), ProductionPlan.status != "cancelled"
        )
        query = query.where(ProductionOrder.id.in_(ids))
    orders = session.exec(
        query.order_by(ProductionOrder.due_date, ProductionOrder.code)
    ).all()
    order_ids = [row.id for row in orders]
    plans = session.exec(
        select(ProductionPlan).where(ProductionPlan.order_id.in_(order_ids))
    ).all()
    plans_by_id = {row.id: row for row in plans}
    releases = session.exec(
        select(WorkRelease).where(WorkRelease.order_id.in_(order_ids))
    ).all()
    latest = {}
    by_order = defaultdict(list)
    for release in releases:
        by_order[release.order_id].append(release)
        if (
            release.plan_id not in latest
            or release.version > latest[release.plan_id].version
        ):
            latest[release.plan_id] = release
    totals = defaultdict(dict)
    rows = session.exec(
        select(
            ProductionReport.release_id,
            ProductionReport.operation_id,
            func.sum(ProductionReport.input_qty),
            func.sum(ProductionReport.good_qty),
            func.sum(ProductionReport.defect_qty),
        )
        .where(
            ProductionReport.release_id.in_([row.id for row in releases]),
            ProductionReport.is_deleted == False,  # noqa: E712
            ProductionReport.occurred_at <= dashboard.updated_at,
        )
        .group_by(ProductionReport.release_id, ProductionReport.operation_id)
    ).all()
    for release_id, operation_id, inputs, good, bad in rows:
        totals[release_id][str(operation_id)] = (int(inputs), int(good), int(bad))
    latest_by_order = defaultdict(list)
    for release in latest.values():
        if (
            release.plan_id in plans_by_id
            and plans_by_id[release.plan_id].status != "cancelled"
        ):
            latest_by_order[release.order_id].append(release)
    completed = set()
    for order in orders:
        relevant = by_order[order.id]
        if order.operation_ids is not None:
            relevant = latest_by_order[order.id]
            good = min(
                (
                    sum(totals[row.id].get(op, (0, 0, 0))[1] for row in relevant)
                    for op in order.operation_ids
                ),
                default=0,
            )
        else:
            good = sum(
                totals[row.id].get(str(row.assignments[-1]["operation_id"]), (0, 0, 0))[
                    1
                ]
                for row in relevant
                if row.assignments
            )
        if good >= order.quantity:
            completed.add(order.id)
    products = (
        {
            row.id: row.name
            for row in product_directory_for_tenant(session, uow.tenant_id).list()
        }
        if orders
        else {}
    )
    order_map = {row.id: row for row in orders}
    running = []
    for plan in plans:
        release = latest.get(plan.id)
        if (
            plan.line_id not in lines
            or plan.status != "published"
            or plan.order_id in completed
            or release is None
            or not release.is_active
            or (plan.start_at and _utc(plan.start_at) > dashboard.updated_at)
            or (plan.end_at and _utc(plan.end_at) < dashboard.updated_at)
        ):
            continue
        order = order_map[plan.order_id]
        good = (
            totals[release.id].get(
                str(release.assignments[-1]["operation_id"]), (0, 0, 0)
            )[1]
            if release.assignments
            else 0
        )
        running.append(
            ScreenRunningOrder(
                order_id=order.id,
                order_code=order.code,
                product_name=products.get(order.product_id, "历史产品"),
                line_name=lines[plan.line_id],
                plan_code=plan.code,
                plan_quantity=plan.quantity,
                good_qty=good,
                due_date=order.due_date,
            )
        )
    running.sort(
        key=lambda row: (row.due_date, row.order_code, row.line_name, row.plan_code)
    )
    zone = ZoneInfo(dashboard.timezone)
    start = datetime.combine(dashboard.day, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(
        dashboard.day + timedelta(days=1), time.min, tzinfo=zone
    ).astimezone(UTC)
    line_good = defaultdict(int)
    for plan in plans:
        covers = _utc(plan.start_at or plan.created_at) < end and (
            (plan.end_at is not None and _utc(plan.end_at) >= start)
            or (plan.end_at is None and plan.start_at is not None)
            or (plan.start_at is None and _utc(plan.created_at) >= start)
        )
        release = latest.get(plan.id)
        if (
            plan.status != "cancelled"
            and covers
            and release is not None
            and release.assignments
        ):
            line_good[plan.line_id] += totals[release.id].get(
                str(release.assignments[-1]["operation_id"]), (0, 0, 0)
            )[1]
    return DataScreenDashboard(
        **dashboard.model_dump(),
        order_total=len(orders),
        order_completed=len(completed),
        order_running=len({row.order_id for row in running}),
        order_overdue=sum(
            row.due_date < dashboard.day and row.id not in completed for row in orders
        ),
        running_orders=running,
        line_progress=[
            ScreenLineProgress(
                line_id=row.id, planned_qty=row.planned_qty, good_qty=line_good[row.id]
            )
            for row in dashboard.lines
        ],
    )
