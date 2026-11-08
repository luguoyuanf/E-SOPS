"""Tenant-scoped plan transitions shared by APIs, terminal polls and reports."""

import uuid

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlmodel import Session, select

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import (
    ProductionOrder,
    ProductionPlan,
    ProductionPlanGroup,
    ProductionReport,
    Station,
    WorkRelease,
    WorkReleaseAssignment,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork


def _lines(session: Session, assignments: list[dict]) -> set[uuid.UUID]:
    station_ids = [uuid.UUID(str(item["station_id"])) for item in assignments]
    stations = session.exec(select(Station).where(Station.id.in_(station_ids))).all()
    return {station.line_id for station in stations}


def _group_plans(session: Session, group_id: uuid.UUID) -> list[ProductionPlan]:
    return list(session.exec(select(ProductionPlan).where(
        ProductionPlan.group_id == group_id,
    ).order_by(ProductionPlan.group_position)).all())


def station_cursor_plan(session: Session, station_id: uuid.UUID) -> ProductionPlan | None:
    station = session.get(Station, station_id)
    release = session.get(WorkRelease, station.current_release_id) if station and station.current_release_id else None
    return session.get(ProductionPlan, release.plan_id) if release else None


def station_advanced_past(session: Session, plan: ProductionPlan, station_id: uuid.UUID) -> bool:
    station = session.get(Station, station_id)
    selected = session.get(WorkRelease, station.selected_release_id) if station and station.selected_release_id else None
    if selected and selected.plan_id == plan.id:
        return False
    cursor = station_cursor_plan(session, station_id)
    return bool(cursor and plan.group_id and cursor.group_id == plan.group_id
                and (cursor.group_position or 0) > (plan.group_position or 0))


def station_can_start_plan(session: Session, plan: ProductionPlan, station_id: uuid.UUID) -> bool:
    group = session.get(ProductionPlanGroup, plan.group_id) if plan.group_id else None
    if group is None or group.switch_mode != "independent":
        return True
    cursor = station_cursor_plan(session, station_id)
    if cursor and cursor.group_id == group.id:
        if (cursor.group_position or 0) > (plan.group_position or 0):
            return False
        if cursor.id == plan.id:
            return True  # Approval of an old deletion must never move a station backwards.
        if group.is_paused:
            return False
    queue = _group_plans(session, group.id)
    earlier = [item for item in queue if (item.group_position or 0) < (plan.group_position or 0)]
    if group.is_paused and any(item.status in {"published", "paused", "expired"} for item in earlier):
        return False
    for item in earlier:
        operations = {str(a["operation_id"]) for a in item.assignments if str(a["station_id"]) == str(station_id)}
        if not operations or item.status == "completed" or station_advanced_past(session, item, station_id):
            continue
        if item.status != "published":
            return False
        release = session.exec(select(WorkRelease).where(WorkRelease.plan_id == item.id)
                               .order_by(WorkRelease.published_at.desc())).first()
        if release is None:
            return False
        reports = session.exec(select(ProductionReport).where(
            ProductionReport.release_id == release.id, ProductionReport.is_deleted == False,  # noqa: E712
        )).all()
        if any(sum(row.good_qty + row.defect_qty for row in reports if str(row.operation_id) == operation) < release.quantity
               for operation in operations):
            return False
    return True


def _independent_plan_ready(session: Session, plan: ProductionPlan) -> bool:
    return any(station_can_start_plan(session, plan, uuid.UUID(str(item["station_id"]))) for item in plan.assignments)


def start_plan(
    session: Session, plan: ProductionPlan, actor_id: uuid.UUID, uow=None, *, ignore_start_time: bool = False
) -> WorkRelease:
    if plan.status != "draft":
        raise HTTPException(status_code=409, detail="只有未启动的排产可以启动")
    now = get_datetime_utc()
    if not ignore_start_time and plan.start_at and now < plan.start_at:
        raise HTTPException(status_code=409, detail="尚未到排产开始时间")
    if plan.end_at and now >= plan.end_at:
        raise HTTPException(status_code=409, detail="排产结束时间已过")
    if plan.group_id:
        group = session.get(ProductionPlanGroup, plan.group_id)
        if group is None or group.tenant_id != plan.tenant_id:
            raise HTTPException(status_code=409, detail="任务组不可用")
        if group.is_paused:
            raise HTTPException(status_code=409, detail="任务组尚未启动或已暂停")
        if not ignore_start_time and group.start_at and now < group.start_at:
            raise HTTPException(status_code=409, detail="尚未到任务组开始时间")
        earlier = [item for item in _group_plans(session, group.id)
                   if item.group_position is not None and plan.group_position is not None
                   and item.group_position < plan.group_position]
        if group.switch_mode == "independent":
            if not _independent_plan_ready(session, plan):
                raise HTTPException(status_code=409, detail="请等待本工位前序排产完成")
        elif any(item.status != "completed" for item in earlier):
            raise HTTPException(status_code=409, detail="请等待任务组前序排产完成")
    # Recheck the current approved content when the task actually begins.
    from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
    from app.modules.esop.production_routes import (
        _require_order_capacity,
        _validate_assignments,
    )
    from app.modules.esop.public_api.production_dto import Assignment, PlanInput

    body = PlanInput(
        order_id=plan.order_id, line_id=plan.line_id,
        assignments=[Assignment.model_validate(item) for item in plan.assignments],
    )
    if uow is None:
        with EsopTenantUnitOfWork(session, plan.tenant_id) as active_uow:
            _require_order_capacity(active_uow, plan.order_id, plan.quantity,
                                    operation_ids={str(item["operation_id"]) for item in plan.assignments},
                                    exclude_plan_id=plan.id)
            snapshot = _validate_assignments(active_uow, body, complete=True)
    else:
        _require_order_capacity(uow, plan.order_id, plan.quantity,
                                operation_ids={str(item["operation_id"]) for item in plan.assignments},
                                exclude_plan_id=plan.id)
        snapshot = _validate_assignments(uow, body, complete=True)
    if not _lines(session, snapshot):
        raise HTTPException(status_code=422, detail="排产尚未分配工位")
    # Multiple published orders may share a line; each station selects one for reporting.
    order = session.get(ProductionOrder, plan.order_id)
    if order is None or order.tenant_id != plan.tenant_id:
        raise HTTPException(status_code=404, detail="生产订单不存在")
    release = WorkRelease(
        tenant_id=plan.tenant_id, plan_id=plan.id, version=1,
        order_id=order.id, line_id=plan.line_id, product_id=order.product_id,
        quantity=plan.quantity, due_date=order.due_date,
        assignments=snapshot, product_sop_version_id=body.product_sop_version_id,
        published_by=actor_id,
    )
    plan.status = "published"
    plan.updated_at = now
    session.add_all([plan, release, *(
        WorkReleaseAssignment(
            tenant_id=plan.tenant_id, release_id=release.id, ordinal=index,
            station_id=uuid.UUID(str(item["station_id"])),
            operation_id=uuid.UUID(str(item["operation_id"])),
            operation_name=str(item.get("operation_name") or ""),
        ) for index, item in enumerate(snapshot)
    )])
    session.flush()
    return release


def advance_due_plans(session: Session) -> None:
    """Run due starts and finish checks inside an existing tenant unit of work."""
    now = get_datetime_utc()
    # Read candidates before locking so completed/future plans never block terminal polls.
    candidate_ids = session.exec(select(ProductionPlan.id).where(or_(
        ProductionPlan.status == "published",
        and_(ProductionPlan.status == "draft", ProductionPlan.group_id.is_(None),
             ProductionPlan.start_at.is_not(None), ProductionPlan.start_at <= now),
    )).order_by(ProductionPlan.id)).all()
    plans = []
    for plan_id in candidate_ids:
        plan = session.get(ProductionPlan, plan_id, with_for_update=True, populate_existing=True)
        if plan is not None:
            plans.append(plan)
    for plan in plans:
        if plan.status != "published":
            continue
        releases = session.exec(select(WorkRelease).where(WorkRelease.plan_id == plan.id)).all()
        if not releases:
            continue
        release = releases[-1]
        reports = session.exec(select(ProductionReport).where(ProductionReport.release_id == release.id, ProductionReport.is_deleted == False)).all()  # noqa: E712
        operation_ids = {str(item["operation_id"]) for item in release.assignments}
        group = session.get(ProductionPlanGroup, plan.group_id) if plan.group_id else None
        completed = all(
            sum(row.good_qty + row.defect_qty for row in reports if str(row.operation_id) == operation_id) >= release.quantity
            or (group and group.switch_mode == "independent" and all(
                station_advanced_past(session, plan, uuid.UUID(str(item["station_id"])))
                for item in release.assignments if str(item["operation_id"]) == operation_id
            ))
            for operation_id in operation_ids
        )
        if completed and operation_ids:
            plan.status = "completed"
            release.is_active = False
            session.add_all([plan, release])
        elif plan.end_at and now >= plan.end_at:
            plan.status = "expired"
            release.is_active = False
            session.add_all([plan, release])
    session.flush()
    groups = session.exec(select(ProductionPlanGroup)).all()
    for group in groups:
        if group.is_paused:
            continue
        queue = _group_plans(session, group.id)
        if group.switch_mode == "independent":
            candidates = [item for item in queue if item.status == "draft" and _independent_plan_ready(session, item)]
        else:
            if any(item.status in {"published", "paused", "expired"} for item in queue):
                continue
            pending = next((item for item in queue if item.status == "draft"), None)
            candidates = [pending] if pending else []
        for next_plan in candidates:
            if (not group.start_at or now >= group.start_at) and (not next_plan.start_at or now >= next_plan.start_at):
                try:
                    start_plan(session, next_plan, next_plan.created_by or group.created_by)
                except HTTPException as exc:
                    if exc.status_code not in {409, 422}:
                        raise
    for plan in plans:
        if plan.group_id is None and plan.status == "draft" and plan.start_at and now >= plan.start_at:
            try:
                start_plan(session, plan, plan.created_by or plan.tenant_id)
            except HTTPException as exc:
                if exc.status_code not in {409, 422}:
                    raise
    session.commit()


def run_plan_schedule(session: Session, tenant_id: uuid.UUID) -> None:
    with EsopTenantUnitOfWork(session, tenant_id):
        advance_due_plans(session)
