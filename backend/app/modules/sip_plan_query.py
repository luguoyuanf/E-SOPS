"""Compose the ESOP SIP list with the live ERP product name in one page query."""

import uuid

from sqlalchemy import and_, func, or_
from sqlmodel import Session, select

from app.modules.erp.infrastructure.models import Product
from app.modules.erp.infrastructure.tenant_uow import ErpTenantUnitOfWork
from app.modules.esop.infrastructure.models import (
    ProductionOrder,
    ProductionPlan,
    ProductionReport,
    SipInspection,
    Station,
    WorkRelease,
    WorkReleaseAssignment,
)


def sip_plan_page(session: Session, tenant_id: uuid.UUID, *, category: str,
                  keyword: str, page: int, page_size: int,
                  station_id: uuid.UUID | None = None) -> dict:
    """Run one joined page query and one matching COUNT inside both tenant scopes."""
    page, page_size = max(1, page), min(100, max(1, page_size))
    latest = select(
        WorkRelease.plan_id, func.max(WorkRelease.version).label("version"),
    ).where(WorkRelease.tenant_id == tenant_id).group_by(WorkRelease.plan_id).subquery()
    filters = [
        ProductionPlan.tenant_id == tenant_id,
        WorkRelease.tenant_id == tenant_id,
        WorkReleaseAssignment.tenant_id == tenant_id,
        ProductionOrder.tenant_id == tenant_id,
        Station.tenant_id == tenant_id,
        ProductionPlan.status == ("completed" if category == "completed" else "published"),
    ]
    if station_id is not None:
        filters.append(WorkReleaseAssignment.station_id == station_id)
    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filters.append(or_(ProductionOrder.code.ilike(pattern),
                           ProductionPlan.code.ilike(pattern), Product.name.ilike(pattern)))

    def joined(statement):
        return (statement
                .join(latest, latest.c.plan_id == ProductionPlan.id)
                .join(WorkRelease, and_(WorkRelease.plan_id == ProductionPlan.id,
                                        WorkRelease.version == latest.c.version))
                .join(WorkReleaseAssignment, WorkReleaseAssignment.release_id == WorkRelease.id)
                .join(ProductionOrder, ProductionOrder.id == WorkRelease.order_id)
                .join(Station, Station.id == WorkReleaseAssignment.station_id)
                .outerjoin(Product, and_(Product.id == WorkRelease.product_id,
                                         Product.tenant_id == tenant_id))
                .where(*filters))

    reports = select(
        ProductionReport.release_id.label("release_id"),
        ProductionReport.operation_id.label("operation_id"),
        ProductionReport.station_id.label("station_id"),
        func.sum(ProductionReport.good_qty).label("good_qty"),
        func.sum(ProductionReport.defect_qty).label("bad_qty"),
    ).where(
        ProductionReport.tenant_id == tenant_id,
        ProductionReport.is_deleted == False,  # noqa: E712
    ).group_by(ProductionReport.release_id, ProductionReport.operation_id, ProductionReport.station_id).subquery()
    inspections = select(
        SipInspection.release_id.label("release_id"),
        SipInspection.operation_id.label("operation_id"),
        SipInspection.station_id.label("station_id"),
        func.sum(SipInspection.quantity).label("checked_qty"),
    ).where(SipInspection.tenant_id == tenant_id).group_by(
        SipInspection.release_id, SipInspection.operation_id, SipInspection.station_id,
    ).subquery()
    with ErpTenantUnitOfWork(session, tenant_id):
        total = session.exec(joined(select(func.count(WorkReleaseAssignment.release_id)).select_from(ProductionPlan))).one()
        statement = joined(select(
            ProductionPlan, WorkRelease, WorkReleaseAssignment, ProductionOrder, Station,
            Product.name, reports.c.good_qty, reports.c.bad_qty, inspections.c.checked_qty,
        ).select_from(ProductionPlan)).outerjoin(reports, and_(
            reports.c.release_id == WorkReleaseAssignment.release_id,
            reports.c.operation_id == WorkReleaseAssignment.operation_id,
            reports.c.station_id == WorkReleaseAssignment.station_id,
        )).outerjoin(inspections, and_(
            inspections.c.release_id == WorkReleaseAssignment.release_id,
            inspections.c.operation_id == WorkReleaseAssignment.operation_id,
            inspections.c.station_id == WorkReleaseAssignment.station_id,
        ))
        if station_id is None:
            statement = statement.order_by(Station.position, Station.id, ProductionPlan.created_at.desc(),
                                           ProductionPlan.id, WorkReleaseAssignment.ordinal)
        else:
            statement = statement.order_by(ProductionPlan.created_at.desc(), ProductionPlan.id,
                                           WorkReleaseAssignment.ordinal)
        rows = session.exec(statement.offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for plan, release, assignment, order, station, product_name, good, bad, checked in rows:
        good, bad, checked = int(good or 0), int(bad or 0), int(checked or 0)
        items.append({
            "releaseId": str(release.id), "planId": str(plan.id), "planCode": plan.code,
            "orderId": str(order.id), "orderCode": order.code,
            "productName": product_name or "", "operationId": str(assignment.operation_id),
            "operationName": assignment.operation_name,
            "stationId": str(station.id), "stationName": station.name or f"{station.position}号工位",
            "planQty": plan.quantity, "goodQty": good, "badQty": bad,
            "reportedQty": good + bad, "inspectedQty": checked,
            "availableQty": max(0, good + bad - checked), "status": plan.status,
        })
    return {"items": items, "total": total}
