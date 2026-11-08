"""Idempotent offline report intake and tenant-local trace queries."""

import csv
import hashlib
import io
import json
import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import func, select

from app.core.clock import get_datetime_utc
from app.core.export_datetime import (
    ExportTimezoneHeader,
    export_datetime,
    export_timezone,
)
from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import (
    AlarmEvent,
    AlarmTypePreference,
    ProductionLine,
    ProductionOrder,
    ProductionPlan,
    ProductionPlanGroup,
    ProductionReport,
    ProductionReportRevision,
    ProductSopVersion,
    SopDocument,
    Station,
    Terminal,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import (
    EsopTenantUnitOfWork,
    EsopTenantUowDep,
)
from app.modules.esop.public_api.dto import OperationAttachment
from app.modules.esop.public_api.terminal_dto import (
    AlarmInput,
    AlarmPublic,
    ListAlarms,
    ListOrderProgress,
    ListReports,
    OrderOperationProgress,
    OrderProgress,
    ReportCorrectionInput,
    ReportCorrectionOptions,
    ReportFilterOption,
    ReportFilterOptions,
    ReportInput,
    ReportPublic,
    ReportRevisionList,
    ReportRevisionPublic,
    ReportSopPreview,
    ReportStationOption,
    WebReportInput,
    WebReportOptions,
    WebReportTask,
)
from app.modules.esop.terminal_routes import DeviceDep
from app.modules.product_directory import product_directory_for_tenant
from app.platform.public_api.files import FileDirectRead
from app.platform.web_api import (
    AlarmTypeDirectoryDep,
    CurrentPrincipal,
    CurrentTenant,
    FileAssetDirectoryDep,
    SessionDep,
    UserDirectoryDep,
    normalize_pagination,
    require_module_access,
)

router = APIRouter(prefix="/esop", tags=["esop-report"])


def _report_sop(uow: EsopTenantUowDep, report_id: uuid.UUID) -> SopDocument:
    report = uow.session.get(ProductionReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报工记录不存在")
    sop = uow.session.get(SopDocument, report.sop_id)
    if sop is None or sop.version != report.sop_version or sop.operation_id != report.operation_id:
        raise HTTPException(status_code=404, detail="当时报工的 SOP 版本不存在")
    return sop


def _report_sop_attachments(uow: EsopTenantUowDep, sop: SopDocument, files: FileAssetDirectoryDep) -> list[OperationAttachment]:
    versions = uow.session.exec(select(ProductSopVersion).where(
        ProductSopVersion.product_id == sop.product_id,
        ProductSopVersion.status == "approved",
    )).all()
    for version in versions:
        for operation in version.operations:
            if operation.get("sop_id") == str(sop.id) and operation.get("id") == str(sop.operation_id):
                return [OperationAttachment.model_validate(item) for item in operation.get("attachments", [])]
    # Legacy SOPs retain flattened pages rather than an operation snapshot.
    attachments = []
    for page in sorted(sop.pages, key=lambda item: item.get("sort", 0)):
        file = files.get_accessible_file(tenant_id=uow.tenant_id, file_id=uuid.UUID(str(page["file_id"])))
        if file is None:
            continue
        content_type = file.content_type or "application/octet-stream"
        kind = "pdf" if content_type == "application/pdf" else "video" if content_type.startswith("video/") else "image"
        attachments.append(OperationAttachment(file_id=file.id, name=str(page.get("caption") or file.original_name),
                                               kind=kind, content_type=content_type, size=file.size))
    return attachments


@router.get("/reports/{report_id}/sop", response_model=ReportSopPreview,
            dependencies=[Depends(require_module_access("esop", "esop:report:list"))])
def report_sop_preview(report_id: uuid.UUID, uow: EsopTenantUowDep, files: FileAssetDirectoryDep) -> ReportSopPreview:
    sop = _report_sop(uow, report_id)
    return ReportSopPreview(product_id=sop.product_id, operation_id=sop.operation_id, title=sop.title,
                            version=sop.version, attachments=_report_sop_attachments(uow, sop, files))


@router.get("/reports/{report_id}/sop/files/{file_id}/access", response_model=FileDirectRead,
            dependencies=[Depends(require_module_access("esop", "esop:report:list"))])
def report_sop_file_access(report_id: uuid.UUID, file_id: uuid.UUID, uow: EsopTenantUowDep,
                           files: FileAssetDirectoryDep) -> FileDirectRead:
    sop = _report_sop(uow, report_id)
    attachments = _report_sop_attachments(uow, sop, files)
    allowed = {value for item in attachments for value in [item.file_id, item.display_file_id, *item.display_pages] if value}
    if file_id not in allowed:
        raise HTTPException(status_code=404, detail="当时 SOP 不包含此文件")
    return files.direct_read_url(tenant_id=uow.tenant_id, file_id=file_id)


def _validate_report_quantities(input_qty: int, good_qty: int, defect_qty: int) -> None:
    if input_qty <= 0:
        raise HTTPException(status_code=422, detail="请填写大于零的投入数量")
    if good_qty + defect_qty != input_qty:
        raise HTTPException(status_code=422, detail="良品数量与不良数量之和必须等于投入数量")


def _lock_release_for_report_write(session, release_id: uuid.UUID) -> None:
    # Serialize writes against the release; reporting may exceed the plan target.
    release = session.exec(select(WorkRelease).where(WorkRelease.id == release_id).with_for_update()
                           .execution_options(populate_existing=True)).first()
    if release is None:
        raise HTTPException(status_code=404, detail="排产任务不存在")


def _record_station_release(session, station_id: uuid.UUID, release_id: uuid.UUID) -> None:
    station = session.exec(select(Station).where(Station.id == station_id).with_for_update()
                           .execution_options(populate_existing=True)).first()
    if station is not None:
        if station.selected_release_id is None:
            station.current_release_id = release_id
            session.add(station)


def _lock_report_release(session, report_id: uuid.UUID) -> None:
    report = session.get(ProductionReport, report_id)
    if report is not None:
        session.exec(select(WorkRelease).where(WorkRelease.id == report.release_id).with_for_update()).first()


def _hash_request(body: ReportInput | AlarmInput, *, staff_id: uuid.UUID | None = None) -> str:
    payload = body.model_dump(mode="json")
    if isinstance(body, AlarmInput) and body.typeCode is None:
        payload.pop("typeCode", None)  # Keep hashes stable for retries from older APKs.
    if staff_id is not None:
        payload["staffUserId"] = str(staff_id)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _occurred_at(value: datetime | None) -> datetime:
    if value is None:
        return get_datetime_utc()
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=422, detail="occurredAt must include a timezone")
    return value


def _terminal(session: SessionDep, device: DeviceIdentity) -> Terminal:
    terminal = session.get(Terminal, device.terminal_id)
    if terminal is None or not terminal.is_active or terminal.tenant_id != device.tenant_id:
        raise HTTPException(status_code=401, detail="Invalid device credential")
    return terminal


def _release_assignment(
    session: SessionDep, *, release_id: uuid.UUID, terminal: Terminal,
    order_id: uuid.UUID | None = None, sop_id: uuid.UUID | None = None,
) -> tuple[WorkRelease, dict[str, object]]:
    if terminal.station_id is None:
        raise HTTPException(status_code=409, detail="Terminal has no station")
    station = session.exec(select(Station).where(Station.id == terminal.station_id).with_for_update()
                           .execution_options(populate_existing=True)).first()
    if station and station.selected_release_id and station.selected_release_id != release_id:
        raise HTTPException(status_code=409, detail="当前工位已切换排产，请刷新后重新报工")
    return _station_assignment(
        session, release_id=release_id, station_id=terminal.station_id,
        order_id=order_id, sop_id=sop_id,
    )


def _station_assignment(
    session: SessionDep, *, release_id: uuid.UUID, station_id: uuid.UUID,
    order_id: uuid.UUID | None = None, sop_id: uuid.UUID | None = None,
    operation_id: uuid.UUID | None = None,
) -> tuple[WorkRelease, dict[str, object]]:
    release = session.get(WorkRelease, release_id)
    if release is None or release.tenant_id != session.info.get("esop_tenant_id"):
        raise HTTPException(status_code=404, detail="Released task not found")
    if not release.is_active:
        raise HTTPException(status_code=409, detail="排产未运行或已暂停")
    from app.modules.esop.plan_scheduler import station_can_start_plan
    plan = session.get(ProductionPlan, release.plan_id)
    station = session.get(Station, station_id)
    if plan and (station is None or station.selected_release_id != release_id) and not station_can_start_plan(session, plan, station_id):
        raise HTTPException(status_code=409, detail="请先完成任务组中本工位的上一排产")
    if order_id is not None and release.order_id != order_id:
        raise HTTPException(status_code=422, detail="Order does not match released task")
    from app.modules.esop.terminal_routes import current_assignment
    assignment = next((
        current for item in release.assignments
        if item.get("station_id") == str(station_id)
        and (operation_id is None or item.get("operation_id") == str(operation_id))
        if (current := current_assignment(session, release, item)) is not None
        and (sop_id is None or current.get("sop_id") == str(sop_id))
    ), None)
    if assignment is None:
        raise HTTPException(status_code=403, detail="工位、工序或 SOP 不属于当前可报工任务")
    return release, assignment


def _progress(session: SessionDep, order: ProductionOrder) -> OrderProgress:
    totals = OrderProgress(
        order_id=order.id, quantity=order.quantity,
        input_total=0, good_total=0, bad_total=0,
    )
    releases = session.exec(
        select(WorkRelease).where(WorkRelease.order_id == order.id)
    ).all()
    operation_names: dict[str, str] = {}
    if order.product_sop_version_id is not None:
        version = session.get(ProductSopVersion, order.product_sop_version_id)
        if version is not None:
            operation_names = {str(item["id"]): str(item.get("name") or item.get("code") or item["id"])
                               for item in version.operations}
    if order.operation_ids is not None:
        active_plan_ids = {plan.id for plan in session.exec(select(ProductionPlan).where(
            ProductionPlan.order_id == order.id, ProductionPlan.status != "cancelled",
        )).all()}
        latest = {}
        for release in releases:
            if release.plan_id in active_plan_ids and (
                release.plan_id not in latest or release.version > latest[release.plan_id].version
            ):
                latest[release.plan_id] = release
        releases = list(latest.values())
    operation_ids = list(order.operation_ids or [])
    bad_by_operation: dict[str, int] = dict.fromkeys(operation_ids, 0)
    good_by_operation: dict[str, int] = dict.fromkeys(operation_ids, 0)
    for release in releases:
        if not release.assignments:
            continue
        for assignment in release.assignments:
            operation_id = str(assignment["operation_id"])
            operation_names.setdefault(operation_id, str(assignment.get("operation_name") or operation_id))
            if order.operation_ids is None and operation_id not in bad_by_operation:
                operation_ids.append(operation_id)
                bad_by_operation[operation_id] = 0
                good_by_operation[operation_id] = 0
        first = order.operation_ids[0] if order.operation_ids else str(release.assignments[0]["operation_id"])
        last = order.operation_ids[-1] if order.operation_ids else str(release.assignments[-1]["operation_id"])
        reports = session.exec(
            select(ProductionReport).where(ProductionReport.release_id == release.id, ProductionReport.is_deleted == False)  # noqa: E712
        ).all()
        totals.input_total += sum(row.input_qty for row in reports if str(row.operation_id) == first)
        if order.operation_ids is None:
            totals.good_total += sum(row.good_qty for row in reports if str(row.operation_id) == last)
        for report in reports:
            operation_id = str(report.operation_id)
            if operation_id in bad_by_operation:
                bad_by_operation[operation_id] += report.defect_qty
                good_by_operation[operation_id] += report.good_qty
    if order.operation_ids is not None:
        totals.good_total = min(good_by_operation.values(), default=0)
    totals.bad_total = sum(bad_by_operation.values())
    totals.operations = [OrderOperationProgress(
        operation_id=uuid.UUID(operation_id),
        operation_name=operation_names.get(operation_id, operation_id),
        completed_total=good_by_operation[operation_id] + bad_by_operation[operation_id],
        bad_total=bad_by_operation[operation_id],
        completion_rate=round(min(100, (good_by_operation[operation_id] + bad_by_operation[operation_id])
                                  / order.quantity * 100), 1),
    ) for operation_id in operation_ids]
    totals.completion_rate = round(
        sum(item.completion_rate for item in totals.operations) / len(totals.operations), 1
    ) if totals.operations else 0.0
    return totals


@router.post(
    "/terminal/reports",
    response_model=ReportPublic,
)
def submit_report(
    session: SessionDep, device: DeviceDep,
    current_principal: CurrentPrincipal, tenant_context: CurrentTenant,
    users: UserDirectoryDep, body: ReportInput,
) -> ReportPublic:
    if tenant_context.tenant_id != device.tenant_id:
        raise HTTPException(status_code=403, detail="Staff and device tenant differ")
    digest = _hash_request(body, staff_id=current_principal.id)
    occurred_at = _occurred_at(body.occurredAt)
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _terminal(session, device)
        existing = session.exec(
            select(ProductionReport).where(
                ProductionReport.terminal_id == terminal.id,
                ProductionReport.request_id == body.requestId,
            )
        ).first()
        if existing is not None:
            if existing.request_hash != digest:
                raise HTTPException(status_code=409, detail="Report request ID was reused with different content")
            return ReportPublic.model_validate(existing)
        _validate_report_quantities(body.inputQty, body.goodQty, body.defectQty)
        session.exec(select(WorkRelease).where(WorkRelease.id == body.releaseId).with_for_update()).first()
        existing = session.exec(select(ProductionReport).where(
            ProductionReport.terminal_id == terminal.id, ProductionReport.request_id == body.requestId,
        ).with_for_update().execution_options(populate_existing=True)).first()
        if existing is not None:
            if existing.request_hash != digest:
                raise HTTPException(status_code=409, detail="报工请求编号已用于不同内容")
            return ReportPublic.model_validate(existing)
        release, assignment = _release_assignment(
            session, release_id=body.releaseId, terminal=terminal,
            order_id=body.orderId, sop_id=body.sopId,
        )
        _lock_release_for_report_write(session, release.id)
        order = session.get(ProductionOrder, body.orderId)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        staff = users.get_users([current_principal.id])
        if not staff or not staff[0].is_active:
            raise HTTPException(status_code=403, detail="Staff account is inactive")
        row = ProductionReport(
            tenant_id=device.tenant_id, terminal_id=terminal.id,
            request_id=body.requestId, request_hash=digest,
            staff_user_id=current_principal.id,
            staff_name=staff[0].full_name or staff[0].email or str(current_principal.id),
            release_id=release.id, order_id=order.id, order_code=order.code,
            station_id=terminal.station_id,
            station_position=int(assignment["station_position"]),
            operation_id=uuid.UUID(str(assignment["operation_id"])),
            sop_id=body.sopId, sop_version=int(assignment["sop_version"]),
            sop_title=str(assignment["sop_title"]),
            input_qty=body.inputQty, good_qty=body.goodQty,
            defect_qty=body.defectQty, occurred_at=occurred_at,
        )
        session.add(row)
        try:
            _record_station_release(session, terminal.station_id, release.id)
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.exec(
                select(ProductionReport).where(
                    ProductionReport.terminal_id == terminal.id,
                    ProductionReport.request_id == body.requestId,
                )
            ).first()
            if existing is None or existing.request_hash != digest:
                raise HTTPException(status_code=409, detail="Report request conflict")
            return ReportPublic.model_validate(existing)
        from app.modules.esop.plan_scheduler import advance_due_plans
        advance_due_plans(session)
        return ReportPublic.model_validate(row)


def _alarm_public(session, row: AlarmEvent) -> AlarmPublic:
    result = AlarmPublic.model_validate(row)
    if row.release_id is None:
        return result
    release = session.get(WorkRelease, row.release_id)
    if release is None:
        return result
    result.plan_id = release.plan_id
    result.order_id = release.order_id
    plan = session.get(ProductionPlan, release.plan_id)
    order = session.get(ProductionOrder, release.order_id)
    result.plan_code = plan.code if plan else None
    result.order_code = order.code if order else None
    return result


@router.post("/terminal/alarms", response_model=AlarmPublic)
def submit_alarm(
    session: SessionDep, device: DeviceDep, body: AlarmInput,
    directory: AlarmTypeDirectoryDep,
    principal: CurrentPrincipal, tenant: CurrentTenant,
) -> AlarmPublic:
    if tenant.tenant_id != device.tenant_id:
        raise HTTPException(status_code=403, detail="员工和设备不属于同一租户")
    digest = _hash_request(body, staff_id=principal.id)
    occurred_at = _occurred_at(body.occurredAt)
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _terminal(session, device)
        existing = session.exec(
            select(AlarmEvent).where(
                AlarmEvent.terminal_id == terminal.id,
                AlarmEvent.request_id == body.requestId,
            )
        ).first()
        if existing is not None:
            if existing.request_hash != digest:
                raise HTTPException(status_code=409, detail="Alarm request ID was reused with different content")
            return _alarm_public(session, existing)
        if terminal.station_id is None:
            raise HTTPException(status_code=409, detail="Terminal has no station")
        from app.modules.esop.terminal_routes import _active_tasks
        tasks = _active_tasks(session, terminal)
        release_id = tasks[0][0].id if tasks else None
        type_name = None
        if body.typeCode:
            global_types = directory.list_global()
            tenant_types = directory.list_tenant(device.tenant_id)
            chosen = next((item for item in (*global_types, *tenant_types)
                           if item.code == body.typeCode and item.active), None)
            preference = session.exec(select(AlarmTypePreference).where(
                AlarmTypePreference.type_code == body.typeCode,
            )).first()
            if chosen is None or (preference is not None and not preference.enabled):
                raise HTTPException(status_code=422, detail="报警类型不存在或已停用")
            type_name = chosen.name
        elif not (body.reason or "").strip():
            raise HTTPException(status_code=422, detail="请选择报警类型")
        row = AlarmEvent(
            tenant_id=device.tenant_id, terminal_id=terminal.id,
            station_id=terminal.station_id, request_id=body.requestId,
            request_hash=digest, release_id=release_id,
            level=body.level, reason=(body.reason or "").strip() or type_name or "工位手动报警",
            type_code=body.typeCode, type_name=type_name, occurred_at=occurred_at,
            staff_user_id=principal.id,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.exec(
                select(AlarmEvent).where(
                    AlarmEvent.terminal_id == terminal.id,
                    AlarmEvent.request_id == body.requestId,
                )
            ).first()
            if existing is None or existing.request_hash != digest:
                raise HTTPException(status_code=409, detail="Alarm request conflict")
            return _alarm_public(session, existing)
        return _alarm_public(session, row)


@router.get("/terminal/alarms", response_model=ListAlarms)
def terminal_alarms(session: SessionDep, device: DeviceDep, principal: CurrentPrincipal,
                    tenant: CurrentTenant, page: int = 1, page_size: int = 20,
                    type_code: str | None = None,
                    status: Literal["unresolved", "resolved"] | None = None) -> ListAlarms:
    if tenant.tenant_id != device.tenant_id:
        raise HTTPException(status_code=403, detail="员工和设备不属于同一租户")
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    with EsopTenantUnitOfWork(session, device.tenant_id):
        _terminal(session, device)
        filters = [AlarmEvent.staff_user_id == principal.id]
        if type_code:
            filters.append(AlarmEvent.type_code == type_code)
        if status == "resolved":
            filters.append(AlarmEvent.resolved_at.is_not(None))
        elif status == "unresolved":
            filters.append(AlarmEvent.resolved_at.is_(None))
        total = session.exec(select(func.count()).select_from(AlarmEvent).where(*filters)).one()
        rows = session.exec(select(AlarmEvent).where(*filters).order_by(
            AlarmEvent.occurred_at.desc(), AlarmEvent.id.desc(),
        ).offset((page - 1) * page_size).limit(page_size)).all()
        return ListAlarms(items=[_alarm_public(session, row) for row in rows], total=total)


def _resolve_alarm(session, alarm_id, principal, *, staff_only=False):
    statement = select(AlarmEvent).where(AlarmEvent.id == alarm_id)
    if staff_only:
        statement = statement.where(AlarmEvent.staff_user_id == principal.id)
    row = session.exec(statement.with_for_update()).first()
    if row is None:
        raise HTTPException(status_code=404, detail="报警记录不存在")
    if row.resolved_at is None:
        row.resolved_at = get_datetime_utc()
        row.resolved_by = principal.id
        session.add(row)
        session.commit()
    return _alarm_public(session, row)


@router.post("/terminal/alarms/{alarm_id}/resolve", response_model=AlarmPublic)
def resolve_own_alarm(alarm_id: uuid.UUID, session: SessionDep, device: DeviceDep,
                      principal: CurrentPrincipal, tenant: CurrentTenant) -> AlarmPublic:
    if tenant.tenant_id != device.tenant_id:
        raise HTTPException(status_code=403, detail="员工和设备不属于同一租户")
    with EsopTenantUnitOfWork(session, device.tenant_id):
        _terminal(session, device)
        return _resolve_alarm(session, alarm_id, principal, staff_only=True)


@router.post("/alarms/{alarm_id}/resolve", response_model=AlarmPublic,
             dependencies=[Depends(require_module_access("esop", "esop:alarm:resolve"))])
def resolve_alarm(alarm_id: uuid.UUID, uow: EsopTenantUowDep,
                  principal: CurrentPrincipal) -> AlarmPublic:
    return _resolve_alarm(uow.session, alarm_id, principal)


@router.get("/terminal/orders")
def terminal_orders(session: SessionDep, device: DeviceDep) -> list[dict[str, Any]]:
    from app.modules.esop.terminal_routes import _active_tasks

    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _terminal(session, device)
        tasks = _active_tasks(session, terminal, include_completed=True, advance_cursor=True)
        session.commit()
        directory = product_directory_for_tenant(session, device.tenant_id)
        rows = []
        seen: set[tuple] = set()
        from app.modules.esop.terminal_routes import current_assignment
        for release, stored in tasks:
            assignment = current_assignment(session, release, stored)
            if assignment is None:
                continue
            key = (release.id, assignment["operation_id"])
            if key in seen:
                continue
            seen.add(key)
            order = session.get(ProductionOrder, release.order_id)
            if order is None:
                continue
            product = directory.get(order.product_id)
            progress = _progress(session, order)
            from app.modules.esop.production_routes import _plan_metrics
            reports = session.exec(select(ProductionReport).where(ProductionReport.release_id == release.id, ProductionReport.is_deleted == False)).all()  # noqa: E712
            completion = _plan_metrics(release.assignments, reports, release.quantity)[3]
            operation_reports = [row for row in reports if str(row.operation_id) == str(assignment["operation_id"])]
            plan = session.get(ProductionPlan, release.plan_id)
            group = session.get(ProductionPlanGroup, plan.group_id) if plan and plan.group_id else None
            rows.append({
                "id": str(order.id), "orderCode": order.code,
                "releaseId": str(release.id), "sopId": str(assignment["sop_id"]),
                "planCode": plan.code if plan else "", "completionRate": completion,
                "groupName": group.name if group else "", "switchMode": group.switch_mode if group else "together",
                "groupPaused": group.is_paused if group else False,
                "operationInputQty": sum(row.input_qty for row in operation_reports),
                "operationGoodQty": sum(row.good_qty for row in operation_reports),
                "operationDefectQty": sum(row.defect_qty for row in operation_reports),
                "operationName": str(assignment["operation_name"]),
                "productCode": product.code if product else "",
                "productName": product.name if product else "",
                "productModel": product.model if product else None,
                "planQty": release.quantity,
                "inputQty": progress.input_total,
                "outputGoodQty": progress.good_total,
                "outputDefectQty": progress.bad_total,
                "siteRole": "BOTH", "status": "COMPLETED" if sum(row.good_qty + row.defect_qty for row in operation_reports) >= release.quantity else "IN_PROGRESS",
            })
        return rows


def _report_statement(
    *, order_id: uuid.UUID | None, station_id: uuid.UUID | None,
    sop_id: uuid.UUID | None, staff_user_id: uuid.UUID | None,
    start_at: datetime | None, end_at: datetime | None, line_id: uuid.UUID | None = None,
):
    statement = select(ProductionReport).where(ProductionReport.is_deleted == False)  # noqa: E712
    if line_id:
        statement = statement.where(ProductionReport.release_id.in_(
            select(WorkRelease.id).where(WorkRelease.line_id == line_id)
        ))
    if order_id:
        statement = statement.where(ProductionReport.order_id == order_id)
    if station_id:
        statement = statement.where(ProductionReport.station_id == station_id)
    if sop_id:
        statement = statement.where(ProductionReport.sop_id == sop_id)
    if staff_user_id:
        statement = statement.where(ProductionReport.staff_user_id == staff_user_id)
    if start_at:
        statement = statement.where(ProductionReport.occurred_at >= _occurred_at(start_at))
    if end_at:
        statement = statement.where(ProductionReport.occurred_at <= _occurred_at(end_at))
    return statement.order_by(ProductionReport.occurred_at.desc())


def _can_select_staff(principal: CurrentPrincipal, uow: EsopTenantUowDep, users: UserDirectoryDep) -> bool:
    return principal.is_superuser or users.is_tenant_administrator(principal.id, uow.tenant_id)


@router.get(
    "/reports/entry-options",
    dependencies=[Depends(require_module_access("esop", "esop:report:create"))],
    response_model=WebReportOptions,
)
def web_report_options(
    uow: EsopTenantUowDep, principal: CurrentPrincipal, users: UserDirectoryDep,
) -> WebReportOptions:
    from app.modules.esop.terminal_routes import current_assignment
    can_select = _can_select_staff(principal, uow, users)
    staff = users.list_tenant_options(uow.tenant_id)
    active = {row.id for row in users.get_users([row.id for row in staff]) if row.is_active}
    staff = [row for row in staff if row.id in active and (can_select or row.id == principal.id)]
    plans = {row.id: row for row in uow.session.exec(select(ProductionPlan)).all()}
    lines = {row.id: row.name for row in uow.session.exec(select(ProductionLine)).all()}
    orders = {row.id: row.code for row in uow.session.exec(select(ProductionOrder)).all()}
    stations = {row.id: row for row in uow.session.exec(select(Station)).all()}
    tasks = []
    now = get_datetime_utc()
    for release in uow.session.exec(select(WorkRelease).where(WorkRelease.is_active == True)).all():  # noqa: E712
        plan = plans.get(release.plan_id)
        if plan is None or plan.status != "published" or (plan.end_at and plan.end_at <= now):
            continue
        for item in release.assignments:
            from app.modules.esop.plan_scheduler import station_can_start_plan
            if not station_can_start_plan(uow.session, plan, uuid.UUID(str(item["station_id"]))):
                continue
            station = stations.get(uuid.UUID(str(item["station_id"])))
            assignment = current_assignment(uow.session, release, item)
            if station is None or assignment is None:
                continue
            tasks.append(WebReportTask(
                release_id=release.id, order_code=orders.get(release.order_id, ""),
                plan_code=plan.code, line_name=lines.get(release.line_id, ""),
                station_id=station.id, station_name=station.name or f"{station.position} 号工位",
                operation_id=uuid.UUID(str(assignment["operation_id"])),
                operation_name=str(assignment.get("operation_name", "工序")),
                sop_id=uuid.UUID(str(assignment["sop_id"])),
                sop_title=str(assignment["sop_title"]), sop_version=int(assignment["sop_version"]),
            ))
    return WebReportOptions(
        can_select_staff=can_select, current_user_id=principal.id,
        staff=[ReportFilterOption(value=row.id, label=row.label) for row in staff], tasks=tasks,
    )


@router.post(
    "/reports", dependencies=[Depends(require_module_access("esop", "esop:report:create"))],
    response_model=ReportPublic,
)
def submit_web_report(
    body: WebReportInput, uow: EsopTenantUowDep, principal: CurrentPrincipal,
    users: UserDirectoryDep,
) -> ReportPublic:
    staff_id = body.staff_user_id or principal.id
    if staff_id != principal.id and not _can_select_staff(principal, uow, users):
        raise HTTPException(status_code=403, detail="普通用户只能为当前登录人报工")
    digest = hashlib.sha256(json.dumps(
        {**body.model_dump(mode="json"), "staff_user_id": str(staff_id)}, sort_keys=True,
    ).encode()).hexdigest()

    def existing_report(*, lock: bool = False):
        statement = select(ProductionReport).where(
            ProductionReport.submitted_by == principal.id,
            ProductionReport.request_id == str(body.request_id),
        )
        return uow.session.exec(statement.with_for_update() if lock else statement).first()

    existing = existing_report()
    if existing is not None:
        if existing.request_hash != digest:
            raise HTTPException(status_code=409, detail="报工请求编号已用于不同内容")
        return ReportPublic.model_validate(existing)
    _validate_report_quantities(body.input_qty, body.good_qty, body.defect_qty)
    release = uow.session.exec(select(WorkRelease).where(
        WorkRelease.id == body.release_id,
    ).with_for_update()).first()
    if release is None:
        raise HTTPException(status_code=404, detail="Released task not found")
    existing = existing_report(lock=True)
    if existing is not None:
        if existing.request_hash != digest:
            raise HTTPException(status_code=409, detail="报工请求编号已用于不同内容")
        return ReportPublic.model_validate(existing)
    plan = uow.session.get(ProductionPlan, release.plan_id)
    if plan is None or plan.status != "published" or (plan.end_at and plan.end_at <= get_datetime_utc()):
        raise HTTPException(status_code=409, detail="排产未运行或已到期")
    release, assignment = _station_assignment(
        uow.session, release_id=body.release_id, station_id=body.station_id,
        operation_id=body.operation_id, sop_id=body.sop_id,
    )
    _lock_release_for_report_write(uow.session, release.id)
    members = {row.id: row for row in users.list_tenant_options(uow.tenant_id)}
    staff = users.get_users([staff_id]) if staff_id in members else []
    if not staff or not staff[0].is_active:
        raise HTTPException(status_code=403, detail="请选择当前租户的启用员工")
    order = uow.session.get(ProductionOrder, release.order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    row = ProductionReport(
        tenant_id=uow.tenant_id, terminal_id=None, submitted_by=principal.id,
        request_id=str(body.request_id), request_hash=digest,
        staff_user_id=staff_id, staff_name=members[staff_id].label,
        release_id=release.id, order_id=order.id, order_code=order.code,
        station_id=body.station_id, station_position=int(assignment["station_position"]),
        operation_id=body.operation_id, sop_id=body.sop_id,
        sop_version=int(assignment["sop_version"]), sop_title=str(assignment["sop_title"]),
        input_qty=body.input_qty, good_qty=body.good_qty, defect_qty=body.defect_qty,
    )
    uow.session.add(row)
    try:
        _record_station_release(uow.session, body.station_id, release.id)
        uow.session.commit()
    except IntegrityError:
        uow.session.rollback()
        existing = existing_report()
        if existing is None or existing.request_hash != digest:
            raise HTTPException(status_code=409, detail="报工请求冲突")
        return ReportPublic.model_validate(existing)
    from app.modules.esop.plan_scheduler import advance_due_plans
    result = ReportPublic.model_validate(row)
    advance_due_plans(uow.session)
    return result


def _can_correct_reports(principal: CurrentPrincipal, uow: EsopTenantUowDep, users: UserDirectoryDep) -> bool:
    return principal.is_superuser or users.can_correct_production_reports(principal.id, uow.tenant_id)


@router.get(
    "/reports/correction-options",
    dependencies=[Depends(require_module_access("esop", "esop:report:list"))],
    response_model=ReportCorrectionOptions,
)
def report_correction_options(
    uow: EsopTenantUowDep, principal: CurrentPrincipal, users: UserDirectoryDep,
) -> ReportCorrectionOptions:
    can_edit = _can_correct_reports(principal, uow, users)
    staff = users.list_tenant_options(uow.tenant_id) if can_edit else []
    active = {user.id for user in users.get_users([row.id for row in staff]) if user.is_active}
    return ReportCorrectionOptions(
        can_edit=can_edit,
        staff=[ReportFilterOption(value=row.id, label=row.label) for row in staff if row.id in active],
    )


def _correction_snapshot(row: ProductionReport) -> dict:
    return {
        "staff_user_id": str(row.staff_user_id), "staff_name": row.staff_name, "is_deleted": row.is_deleted,
        "input_qty": row.input_qty, "good_qty": row.good_qty, "defect_qty": row.defect_qty,
    }


@router.patch(
    "/reports/{report_id}",
    dependencies=[Depends(require_module_access("esop", "esop:report:list"))],
    response_model=ReportPublic,
)
def correct_report(
    report_id: uuid.UUID, body: ReportCorrectionInput,
    uow: EsopTenantUowDep, principal: CurrentPrincipal, users: UserDirectoryDep,
) -> ReportPublic:
    if not _can_correct_reports(principal, uow, users):
        raise HTTPException(status_code=403, detail="仅租户管理员和经理岗位可修改报工")
    _lock_report_release(uow.session, report_id)
    row = uow.session.exec(select(ProductionReport).where(
        ProductionReport.id == report_id,
    ).with_for_update()).first()
    if row is None:
        raise HTTPException(status_code=404, detail="报工记录不存在")
    if row.is_deleted:
        raise HTTPException(status_code=409, detail="报工已删除，不能修改")
    if row.revision != body.expected_revision:
        raise HTTPException(status_code=409, detail="报工记录已更新，请刷新后重新修改")
    _validate_report_quantities(body.input_qty, body.good_qty, body.defect_qty)
    _lock_release_for_report_write(uow.session, row.release_id)
    from app.modules.esop.sip_routes import ensure_report_inspection_balance
    ensure_report_inspection_balance(uow.session, row, body.good_qty + body.defect_qty)
    before = _correction_snapshot(row)
    after = {**before, "staff_user_id": str(body.staff_user_id),
             "input_qty": body.input_qty, "good_qty": body.good_qty, "defect_qty": body.defect_qty}
    members = {member.id: member for member in users.list_tenant_options(uow.tenant_id)}
    if body.staff_user_id != row.staff_user_id:
        staff = users.get_users([body.staff_user_id]) if body.staff_user_id in members else []
        if not staff or not staff[0].is_active:
            raise HTTPException(status_code=403, detail="请选择当前租户的启用员工")
        after["staff_name"] = members[body.staff_user_id].label
    if before == after:
        raise HTTPException(status_code=422, detail="未修改报工内容")
    actor = members.get(principal.id)
    names = users.get_users([principal.id]) if actor is None else []
    actor_name = actor.label if actor else (
        (names[0].full_name or names[0].email or str(principal.id)) if names else str(principal.id)
    )
    for key, value in after.items():
        setattr(row, key, uuid.UUID(value) if key == "staff_user_id" else value)
    row.revision += 1
    history = ProductionReportRevision(
        tenant_id=uow.tenant_id, report_id=row.id, revision=row.revision,
        reason=body.reason, changed_by=principal.id, changed_by_name=actor_name,
        before=before, after=after,
    )
    # The correction and its history commit together; completed plan state stays unchanged.
    uow.session.add_all([row, history])
    uow.session.commit()
    return ReportPublic.model_validate(row)


@router.get(
    "/reports/{report_id}/revisions",
    dependencies=[Depends(require_module_access("esop", "esop:report:list"))],
    response_model=ReportRevisionList,
)
def report_revisions(report_id: uuid.UUID, uow: EsopTenantUowDep) -> ReportRevisionList:
    row = uow.session.get(ProductionReport, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="报工记录不存在")
    revisions = uow.session.exec(select(ProductionReportRevision).where(
        ProductionReportRevision.report_id == report_id,
    ).order_by(ProductionReportRevision.revision.desc())).all()
    return ReportRevisionList(
        items=[ReportRevisionPublic.model_validate(item) for item in revisions], total=len(revisions),
    )


@router.get(
    "/reports/filter-options",
    dependencies=[Depends(require_module_access("esop", "esop:report:list"))],
    response_model=ReportFilterOptions,
)
def report_filter_options(uow: EsopTenantUowDep, users: UserDirectoryDep) -> ReportFilterOptions:
    orders = uow.session.exec(select(ProductionOrder).order_by(ProductionOrder.code)).all()
    lines = uow.session.exec(select(ProductionLine).order_by(ProductionLine.code)).all()
    stations = uow.session.exec(select(Station).order_by(Station.position)).all()
    line_names = {line.id: line.name for line in lines}
    return ReportFilterOptions(
        orders=[ReportFilterOption(value=row.id, label=row.code) for row in orders],
        lines=[ReportFilterOption(value=row.id, label=row.name) for row in lines],
        stations=[ReportStationOption(
            value=row.id, line_id=row.line_id,
            label=f"{line_names.get(row.line_id, '')} / {row.name or f'{row.position} 号工位'}",
        ) for row in stations],
        staff=[ReportFilterOption(value=row.id, label=row.label)
               for row in users.list_tenant_options(uow.tenant_id)],
    )


@router.get(
    "/reports", dependencies=[Depends(require_module_access("esop", "esop:report:list"))],
    response_model=ListReports,
)
def list_reports(
    uow: EsopTenantUowDep, order_id: uuid.UUID | None = None,
    line_id: uuid.UUID | None = None,
    station_id: uuid.UUID | None = None, sop_id: uuid.UUID | None = None,
    staff_user_id: uuid.UUID | None = None, start_at: datetime | None = None,
    end_at: datetime | None = None, page: int = 1, page_size: int = 50,
) -> ListReports:
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    rows = uow.session.exec(_report_statement(
        order_id=order_id, station_id=station_id, sop_id=sop_id, line_id=line_id,
        staff_user_id=staff_user_id, start_at=start_at, end_at=end_at,
    )).all()
    return ListReports(
        items=[ReportPublic.model_validate(row) for row in rows[(page - 1) * page_size:page * page_size]],
        total=len(rows),
    )


@router.get(
    "/reports/export", dependencies=[Depends(require_module_access("esop", "esop:report:export"))],
    response_model=None,
)
def export_reports(
    uow: EsopTenantUowDep, order_id: uuid.UUID | None = None,
    line_id: uuid.UUID | None = None,
    station_id: uuid.UUID | None = None, sop_id: uuid.UUID | None = None,
    staff_user_id: uuid.UUID | None = None, start_at: datetime | None = None,
    end_at: datetime | None = None,
    x_export_timezone: ExportTimezoneHeader = None,
) -> StreamingResponse:
    timezone = export_timezone(x_export_timezone)
    rows = uow.session.exec(_report_statement(
        order_id=order_id, station_id=station_id, sop_id=sop_id, line_id=line_id,
        staff_user_id=staff_user_id, start_at=start_at, end_at=end_at,
    )).all()
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "订单编号", "工位位置", "员工姓名", "SOP标题", "SOP版本",
        "投入数量", "良品数量", "不良数量", "报工时间",
    ])
    for row in rows:
        writer.writerow([
            row.order_code, row.station_position, row.staff_name,
            row.sop_title, row.sop_version, row.input_qty,
            row.good_qty, row.defect_qty, export_datetime(row.occurred_at, timezone),
        ])
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('报工记录.csv')}"},
    )


@router.get(
    "/alarms", dependencies=[Depends(require_module_access("esop", "esop:alarm:list"))],
    response_model=ListAlarms,
)
def list_alarms(uow: EsopTenantUowDep, users: UserDirectoryDep) -> ListAlarms:
    rows = uow.session.exec(
        select(AlarmEvent, Terminal.device_name, Terminal.serial_number, Station.name, Station.position)
        .outerjoin(Terminal, AlarmEvent.terminal_id == Terminal.id)
        .outerjoin(Station, AlarmEvent.station_id == Station.id)
        .order_by(AlarmEvent.occurred_at.desc())
    ).all()
    staff = {user.id: user.full_name or user.email for user in users.get_users(
        {row.staff_user_id for row, *_ in rows if row.staff_user_id is not None},
    )}
    items = [_alarm_public(uow.session, row).model_copy(update={
        "staff_name": staff.get(row.staff_user_id),
        "terminal_name": terminal_name or serial_number,
        "station_name": station_name or (f"{position} 号工位" if position is not None else None),
    }) for row, terminal_name, serial_number, station_name, position in rows]
    return ListAlarms(items=items, total=len(items))


@router.get(
    "/orders/progress", dependencies=[Depends(require_module_access("esop", "esop:order:list"))],
    response_model=ListOrderProgress,
)
def list_order_progress(uow: EsopTenantUowDep) -> ListOrderProgress:
    orders = uow.session.exec(select(ProductionOrder)).all()
    rows = [_progress(uow.session, order) for order in orders]
    return ListOrderProgress(items=rows, total=len(rows))
