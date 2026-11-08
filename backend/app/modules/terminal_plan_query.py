"""Compose the terminal production-plan page from ESOP and ERP read data."""

import uuid

from sqlalchemy import and_, func, or_
from sqlmodel import Session, select

from app.core.clock import get_datetime_utc
from app.modules.erp.infrastructure.models import Product
from app.modules.erp.infrastructure.tenant_uow import ErpTenantUnitOfWork
from app.modules.esop.infrastructure.models import (
    ProductionOrder,
    ProductionPlan,
    ProductionPlanGroup,
    ProductionReport,
    Station,
    WorkRelease,
    WorkReleaseAssignment,
)


def terminal_plan_page(session: Session, tenant_id: uuid.UUID, station: Station, *,
                       category: str, keyword: str, page: int, page_size: int) -> dict:
    page, page_size = max(1, page), min(100, max(1, page_size))
    latest = select(WorkRelease.plan_id, func.max(WorkRelease.version).label("version")).where(
        WorkRelease.tenant_id == tenant_id,
    ).group_by(WorkRelease.plan_id).subquery()
    filters = [ProductionPlan.tenant_id == tenant_id, WorkRelease.tenant_id == tenant_id,
               WorkReleaseAssignment.tenant_id == tenant_id, ProductionOrder.tenant_id == tenant_id,
               ProductionPlan.status == ("completed" if category == "completed" else "published"),
               WorkReleaseAssignment.station_id == station.id]
    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filters.append(or_(ProductionOrder.code.ilike(pattern), ProductionPlan.code.ilike(pattern),
                           Product.name.ilike(pattern)))

    def plan_join(statement):
        return (statement.select_from(ProductionPlan)
                .join(latest, latest.c.plan_id == ProductionPlan.id)
                .join(WorkRelease, and_(WorkRelease.plan_id == ProductionPlan.id,
                                        WorkRelease.version == latest.c.version))
                .join(WorkReleaseAssignment, WorkReleaseAssignment.release_id == WorkRelease.id)
                .join(ProductionOrder, ProductionOrder.id == WorkRelease.order_id)
                .outerjoin(Product, and_(Product.id == WorkRelease.product_id,
                                         Product.tenant_id == tenant_id))
                .where(*filters))

    candidates = plan_join(select(
        ProductionPlan.id.label("plan_id"), ProductionPlan.created_at.label("created_at"),
    )).distinct().subquery()
    reports = select(
        ProductionReport.release_id.label("release_id"),
        ProductionReport.operation_id.label("operation_id"),
        func.sum(ProductionReport.good_qty + ProductionReport.defect_qty).label("completed_qty"),
    ).where(ProductionReport.tenant_id == tenant_id,
            ProductionReport.is_deleted == False).group_by(  # noqa: E712
                ProductionReport.release_id, ProductionReport.operation_id,
            ).subquery()
    with ErpTenantUnitOfWork(session, tenant_id):
        total = session.exec(select(func.count()).select_from(candidates)).one()
        page_ids = select(candidates.c.plan_id).order_by(
            candidates.c.created_at.desc(), candidates.c.plan_id,
        ).offset((page - 1) * page_size).limit(page_size).subquery()
        rows = session.exec(
            select(ProductionPlan, WorkRelease, WorkReleaseAssignment,
                   ProductionOrder, ProductionPlanGroup, Product.name, Product.model,
                   reports.c.completed_qty)
            .select_from(page_ids)
            .join(ProductionPlan, ProductionPlan.id == page_ids.c.plan_id)
            .join(latest, latest.c.plan_id == ProductionPlan.id)
            .join(WorkRelease, and_(WorkRelease.plan_id == ProductionPlan.id,
                                    WorkRelease.version == latest.c.version,
                                    WorkRelease.tenant_id == tenant_id))
            .join(WorkReleaseAssignment, and_(
                WorkReleaseAssignment.release_id == WorkRelease.id,
                WorkReleaseAssignment.station_id == station.id,
                WorkReleaseAssignment.tenant_id == tenant_id,
            ))
            .join(ProductionOrder, and_(ProductionOrder.id == WorkRelease.order_id,
                                        ProductionOrder.tenant_id == tenant_id))
            .outerjoin(ProductionPlanGroup, and_(ProductionPlanGroup.id == ProductionPlan.group_id,
                                                 ProductionPlanGroup.tenant_id == tenant_id))
            .outerjoin(Product, and_(Product.id == WorkRelease.product_id,
                                     Product.tenant_id == tenant_id))
            .outerjoin(reports, and_(reports.c.release_id == WorkRelease.id,
                                     reports.c.operation_id == WorkReleaseAssignment.operation_id))
            .order_by(ProductionPlan.created_at.desc(), ProductionPlan.id,
                      WorkReleaseAssignment.ordinal)
        ).all()

    plans: dict[uuid.UUID, tuple[ProductionPlan, WorkRelease, ProductionOrder,
                                 ProductionPlanGroup | None, str | None, str | None,
                                 list[tuple[WorkReleaseAssignment, int]]]] = {}
    for plan, release, assignment, order, group, product_name, product_model, completed in rows:
        if plan.id not in plans:
            plans[plan.id] = (plan, release, order, group, product_name, product_model, [])
        plans[plan.id][6].append((assignment, int(completed or 0)))
    now = get_datetime_utc()
    items = []
    for plan, release, order, group, product_name, product_model, progress in plans.values():
        assignment, completed = next((entry for entry in progress if entry[1] < plan.quantity), progress[0])
        can_switch = bool(plan.status == "published" and release.is_active
                          and (plan.end_at is None or now < plan.end_at)
                          and any(count < release.quantity for _, count in progress))
        items.append({
            "planId": str(plan.id), "planCode": plan.code, "releaseId": str(release.id),
            "orderId": str(order.id), "orderCode": order.code, "orderQty": order.quantity,
            "dueDate": order.due_date, "productName": product_name or "",
            "productModel": product_model if product_name is not None else "",
            "operationId": str(assignment.operation_id),
            "operationName": str(next((item.get("operation_name") or "" for item in plan.assignments
                                       if item.get("station_id") == str(station.id)
                                       and item.get("operation_id") == str(assignment.operation_id)), "")),
            "planQty": plan.quantity,
            "completedQty": completed, "status": plan.status,
            "groupName": group.name if group else "", "startAt": plan.start_at,
            "endAt": plan.end_at, "canSwitch": can_switch,
            "isCurrent": bool(release.id == (station.selected_release_id or station.current_release_id)),
        })
    return {"items": items, "total": total}
