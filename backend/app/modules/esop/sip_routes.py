"""Quantity-only SIP inspection of already reported order pieces."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import select

from app.modules.esop.infrastructure.models import (
    ProductionPlan,
    ProductionReport,
    SipInspection,
    Station,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import (
    EsopTenantUnitOfWork,
    EsopTenantUowDep,
)
from app.modules.esop.terminal_routes import DeviceDep, _terminal
from app.modules.sip_plan_query import sip_plan_page
from app.platform.web_api import (
    CurrentPrincipal,
    CurrentTenant,
    SessionDep,
    require_module_access,
)

router = APIRouter(prefix="/esop", tags=["esop-sip"])


class SipInput(BaseModel):
    requestId: str = Field(min_length=1, max_length=100)
    releaseId: uuid.UUID
    operationId: uuid.UUID
    quantity: int = Field(ge=1)


def _reported(session, release_id: uuid.UUID, operation_id: uuid.UUID, station_id: uuid.UUID):
    return session.exec(select(ProductionReport).where(
        ProductionReport.release_id == release_id,
        ProductionReport.operation_id == operation_id,
        ProductionReport.station_id == station_id,
        ProductionReport.is_deleted == False,  # noqa: E712
    ).order_by(ProductionReport.created_at, ProductionReport.id)).all()


def _inspections(session, release_id: uuid.UUID, operation_id: uuid.UUID, station_id: uuid.UUID):
    return session.exec(select(SipInspection).where(
        SipInspection.release_id == release_id,
        SipInspection.operation_id == operation_id,
        SipInspection.station_id == station_id,
    ).order_by(SipInspection.created_at, SipInspection.id)).all()


def _item(row: SipInspection) -> dict:
    return {
        "id": str(row.id), "requestId": row.request_id,
        "releaseId": str(row.release_id), "operationId": str(row.operation_id),
        "stationId": str(row.station_id), "quantity": row.quantity,
        "staffUserId": str(row.staff_user_id), "createdAt": row.created_at,
        "reportAllocations": row.report_allocations,
    }


def ensure_report_inspection_balance(session, report: ProductionReport, new_total: int) -> None:
    """Keep existing SIP allocations valid when a report is corrected or deleted."""
    inspections = session.exec(select(SipInspection).where(
        SipInspection.release_id == report.release_id,
        SipInspection.operation_id == report.operation_id,
        SipInspection.station_id == report.station_id,
    )).all()
    allocated = sum(
        int(part["quantity"])
        for inspection in inspections
        for part in inspection.report_allocations
        if part.get("reportId") == str(report.id)
    )
    if allocated > new_total:
        raise HTTPException(status_code=409, detail="该报工已有点检数量，修改或删除后会造成点检超量")


@router.get("/terminal/sip/plans")
def terminal_sip_plans(session: SessionDep, device: DeviceDep, _principal: CurrentPrincipal,
                       tenant: CurrentTenant, category: Literal["active", "completed"] = "active",
                       keyword: str = "", page: int = 1, page_size: int = 30) -> dict:
    if tenant.tenant_id != device.tenant_id:
        raise HTTPException(status_code=403, detail="员工与设备不属于同一租户")
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _terminal(session, device)
        if terminal.station_id is None:
            return {"items": [], "total": 0}
        return sip_plan_page(session, device.tenant_id, category=category, keyword=keyword,
                             page=page, page_size=page_size, station_id=terminal.station_id)


@router.get("/terminal/sip/inspections")
def terminal_sip_inspections(release_id: uuid.UUID, operation_id: uuid.UUID,
                             session: SessionDep, device: DeviceDep,
                             _principal: CurrentPrincipal, tenant: CurrentTenant) -> dict:
    if tenant.tenant_id != device.tenant_id:
        raise HTTPException(status_code=403, detail="员工与设备不属于同一租户")
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _terminal(session, device)
        if terminal.station_id is None:
            return {"items": []}
        return {"items": [_item(row) for row in _inspections(
            session, release_id, operation_id, terminal.station_id,
        )]}


@router.post("/terminal/sip/inspections")
def submit_sip(body: SipInput, session: SessionDep, device: DeviceDep,
               principal: CurrentPrincipal, tenant: CurrentTenant) -> dict:
    if tenant.tenant_id != device.tenant_id:
        raise HTTPException(status_code=403, detail="员工与设备不属于同一租户")
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _terminal(session, device)
        if terminal.station_id is None:
            raise HTTPException(status_code=409, detail="终端尚未绑定工位")
        release = session.exec(select(WorkRelease).where(
            WorkRelease.id == body.releaseId,
        ).with_for_update()).first()
        station = session.exec(select(Station).where(
            Station.id == terminal.station_id,
        ).with_for_update()).first()
        if station is None:
            raise HTTPException(status_code=409, detail="工位不存在")
        existing = session.exec(select(SipInspection).where(
            SipInspection.terminal_id == terminal.id,
            SipInspection.request_id == body.requestId,
        )).first()
        if existing is not None:
            if (existing.release_id, existing.operation_id, existing.quantity) != (
                body.releaseId, body.operationId, body.quantity,
            ):
                raise HTTPException(status_code=409, detail="点检请求编号已用于不同内容")
            return _item(existing)
        plan = session.get(ProductionPlan, release.plan_id) if release else None
        if release is None or plan is None or plan.status not in ("published", "completed"):
            raise HTTPException(status_code=404, detail="排产任务不存在")
        if not any(item.get("station_id") == str(station.id)
                   and item.get("operation_id") == str(body.operationId)
                   for item in release.assignments):
            raise HTTPException(status_code=403, detail="此排产未分配给当前工位")
        reports = _reported(session, release.id, body.operationId, station.id)
        used = {}
        for inspection in _inspections(session, release.id, body.operationId, station.id):
            for part in inspection.report_allocations:
                report_id = str(part["reportId"])
                used[report_id] = used.get(report_id, 0) + int(part["quantity"])
        remaining, allocations = body.quantity, []
        for report in reports:
            amount = report.good_qty + report.defect_qty - used.get(str(report.id), 0)
            take = min(remaining, max(0, amount))
            if take:
                allocations.append({"reportId": str(report.id), "quantity": take})
                remaining -= take
            if remaining == 0:
                break
        if remaining:
            raise HTTPException(status_code=409, detail="点检数量超过可点检的有效报工数量")
        row = SipInspection(
            tenant_id=device.tenant_id, release_id=release.id,
            operation_id=body.operationId, station_id=station.id,
            terminal_id=terminal.id, staff_user_id=principal.id,
            request_id=body.requestId, quantity=body.quantity,
            report_allocations=allocations,
        )
        session.add(row)
        session.commit()
        return _item(row)


@router.get("/sip/inspections", dependencies=[Depends(require_module_access("esop", "esop:sip:list"))])
def admin_sip_inspections(uow: EsopTenantUowDep, release_id: uuid.UUID | None = None,
                          operation_id: uuid.UUID | None = None,
                          station_id: uuid.UUID | None = None,
                          page: int = 1, page_size: int = 30) -> dict:
    conditions = [SipInspection.tenant_id == uow.tenant_id]
    if release_id is not None:
        conditions.append(SipInspection.release_id == release_id)
    if operation_id is not None:
        conditions.append(SipInspection.operation_id == operation_id)
    if station_id is not None:
        conditions.append(SipInspection.station_id == station_id)
    page, page_size = max(1, page), min(100, max(1, page_size))
    total = uow.session.exec(select(func.count(SipInspection.id)).where(*conditions)).one()
    query = select(SipInspection).where(*conditions).order_by(SipInspection.created_at.desc())
    rows = uow.session.exec(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_item(row) for row in rows], "total": total}


@router.get("/sip/plans", dependencies=[Depends(require_module_access("esop", "esop:sip:list"))])
def admin_sip_plans(uow: EsopTenantUowDep, category: Literal["active", "completed"] = "active",
                    keyword: str = "", page: int = 1, page_size: int = 30) -> dict:
    return sip_plan_page(uow.session, uow.tenant_id, category=category, keyword=keyword,
                         page=page, page_size=page_size)
