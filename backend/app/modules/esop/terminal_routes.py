"""Tenant-resolved device activation, binding, tasks and media."""

import mimetypes
import uuid
from datetime import UTC, timedelta
from ipaddress import ip_address
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError
from sqlmodel import Session, col, select

from app.core.cache import redis_cache
from app.core.clock import get_datetime_utc
from app.modules.esop.catalog_cache import cached_catalog
from app.modules.esop.infrastructure.device_auth import (
    DeviceIdentity,
    activate_device,
    resolve_device,
)
from app.modules.esop.infrastructure.device_installation import installation_device_code
from app.modules.esop.infrastructure.models import (
    Advertisement,
    Broadcast,
    OperationFileRendition,
    ProductionLine,
    ProductionOrder,
    ProductionPlan,
    ProductionReport,
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
    ActivateInput,
    DeviceIdentityPublic,
    InstallationInput,
    InstallationPublic,
    ListTerminals,
    StaffLoginInput,
    StationBindInput,
    TerminalNameInput,
    TerminalPublic,
)
from app.modules.product_directory import product_directory_for_tenant
from app.platform.web_api import (
    CurrentPrincipal,
    CurrentTenant,
    SessionDep,
    authenticate_terminal_staff,
    get_channel_customer_tenants,
    get_file_asset_directory,
    get_terminal_staff_profile,
    preview_authorized_file,
    require_module_access,
)

router = APIRouter(prefix="/esop", tags=["esop-terminal"])


def get_device_identity(
    session: SessionDep,
    x_device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> DeviceIdentity:
    return resolve_device(session, x_device_token or "")


DeviceDep = Annotated[DeviceIdentity, Depends(get_device_identity)]


def _terminal(session: Session, identity: DeviceIdentity) -> Terminal:
    terminal = session.get(Terminal, identity.terminal_id)
    if terminal is None or not terminal.is_active or terminal.tenant_id != identity.tenant_id:
        raise HTTPException(status_code=401, detail="Invalid device credential")
    return terminal


def _active_tasks(session: Session, terminal: Terminal, *, include_completed: bool = False,
                  advance_cursor: bool = False) -> list[tuple[WorkRelease, dict[str, object]]]:
    if terminal.station_id is None:
        return []
    from app.modules.esop.plan_scheduler import station_can_start_plan
    releases = session.exec(select(WorkRelease).where(WorkRelease.is_active == True)).all()  # noqa: E712
    station = session.get(Station, terminal.station_id)
    manual_release_id = station.selected_release_id if station else None
    plans = {release.plan_id: session.get(ProductionPlan, release.plan_id) for release in releases}
    releases.sort(key=lambda release: (
        0 if release.id == manual_release_id else
        1 if station and release.id == station.current_release_id else 2,
        release.published_at,
        str(plans[release.plan_id].group_id) if plans[release.plan_id] else "",
        (plans[release.plan_id].group_position or 0) if plans[release.plan_id] else 0,
        str(release.id),
    ))
    selected = None
    completed_task = None
    for release in releases:
        plan = plans[release.plan_id]
        if plan and release.id != manual_release_id and not station_can_start_plan(session, plan, terminal.station_id):
            continue
        reports = session.exec(select(ProductionReport).where(
            ProductionReport.release_id == release.id, ProductionReport.is_deleted == False,  # noqa: E712
        )).all()
        for assignment in release.assignments:
            if assignment.get("station_id") != str(terminal.station_id):
                continue
            completed = sum(row.good_qty + row.defect_qty for row in reports
                            if str(row.operation_id) == str(assignment["operation_id"]))
            if completed < release.quantity:
                selected = (release, assignment)
                break
            completed_task = (release, assignment)
        if selected:
            break
    chosen = selected or (completed_task if include_completed else None)
    if advance_cursor and manual_release_id and (selected is None or selected[0].id != manual_release_id):
        station = session.exec(select(Station).where(Station.id == terminal.station_id)
                               .with_for_update().execution_options(populate_existing=True)).first()
        if station and station.selected_release_id == manual_release_id:
            station.selected_release_id = None
            station.selected_by = None
            station.selected_at = None
            session.add(station)
            session.flush()
    if chosen and chosen[0].id == manual_release_id:
        return [chosen]
    if chosen and advance_cursor:
        station = session.exec(select(Station).where(Station.id == terminal.station_id)
                               .with_for_update().execution_options(populate_existing=True)).first()
        if station and station.current_release_id != chosen[0].id:
            if station.current_release_id and session.get(WorkRelease, station.current_release_id) is None:
                return []  # A newer cursor can precede this transaction's consistent-read snapshot; retry next poll.
            # Recheck against any cursor advanced by a concurrent poll before persisting.
            plan = plans[chosen[0].plan_id]
            if plan and not station_can_start_plan(session, plan, terminal.station_id):
                return _active_tasks(session, terminal, include_completed=include_completed)
            station.current_release_id = chosen[0].id
            session.add(station)
            session.flush()
    return [chosen] if chosen else []


@router.get("/terminal/production-plans")
def terminal_production_plans(
    session: SessionDep, device: DeviceDep, _current_principal: CurrentPrincipal,
    tenant_context: CurrentTenant, page: int = 1, page_size: int = 30,
    keyword: str = "", category: Literal["active", "completed"] = "active",
) -> dict[str, Any]:
    if tenant_context.tenant_id != device.tenant_id:
        raise HTTPException(status_code=403, detail="员工与设备不属于同一租户")
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _terminal(session, device)
        if terminal.station_id is None:
            return {"items": [], "total": 0}
        station = session.get(Station, terminal.station_id)
        if station is None:
            return {"items": [], "total": 0}
        from app.modules.terminal_plan_query import terminal_plan_page
        return terminal_plan_page(session, device.tenant_id, station, category=category,
                                  keyword=keyword, page=page, page_size=page_size)


@router.post("/terminal/production-plans/{release_id}/select")
def select_terminal_production_plan(
    release_id: uuid.UUID, session: SessionDep, device: DeviceDep,
    current_principal: CurrentPrincipal, tenant_context: CurrentTenant,
) -> dict[str, str]:
    if tenant_context.tenant_id != device.tenant_id:
        raise HTTPException(status_code=403, detail="员工与设备不属于同一租户")
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _terminal(session, device)
        if terminal.station_id is None:
            raise HTTPException(status_code=409, detail="终端尚未绑定工位")
        release = session.exec(select(WorkRelease).where(WorkRelease.id == release_id)
                               .with_for_update().execution_options(populate_existing=True)).first()
        if release is None or release.tenant_id != device.tenant_id:
            raise HTTPException(status_code=404, detail="排产任务不存在")
        plan = session.get(ProductionPlan, release.plan_id)
        if not release.is_active or plan is None or plan.status != "published":
            raise HTTPException(status_code=409, detail="只有已发布且运行中的排产可以切换")
        if plan.end_at and get_datetime_utc() >= plan.end_at:
            raise HTTPException(status_code=409, detail="排产结束时间已过")
        assignments = [item for item in release.assignments
                       if item.get("station_id") == str(terminal.station_id)]
        if not assignments:
            raise HTTPException(status_code=403, detail="该排产未分配到本工位")
        if not any(current_assignment(session, release, item) is not None for item in assignments):
            raise HTTPException(status_code=409, detail="该排产的作业指导书不可用")
        reports = session.exec(select(ProductionReport).where(
            ProductionReport.release_id == release.id,
            ProductionReport.is_deleted == False,  # noqa: E712
        )).all()
        if all(sum(row.good_qty + row.defect_qty for row in reports
                   if str(row.operation_id) == str(item["operation_id"])) >= release.quantity
               for item in assignments):
            raise HTTPException(status_code=409, detail="本工位的排产数量已完成")
        station = session.exec(select(Station).where(Station.id == terminal.station_id)
                               .with_for_update().execution_options(populate_existing=True)).first()
        if station is None:
            raise HTTPException(status_code=404, detail="工位不存在")
        station.selected_release_id = release.id
        station.selected_by = current_principal.id
        station.selected_at = get_datetime_utc()
        session.add(station)
        session.commit()
        return {"releaseId": str(release.id)}


def current_assignment(session: Session, release: WorkRelease, assignment: dict[str, object]) -> dict[str, object] | None:
    """Resolve display content from the latest approved product SOP at read time."""
    version = session.exec(select(ProductSopVersion).where(
        ProductSopVersion.product_id == release.product_id,
        ProductSopVersion.status == "approved",
    ).order_by(ProductSopVersion.version.desc())).first()
    if version is None:
        return {key: value for key, value in assignment.items() if key != "_attachments"} if not release.product_sop_version_id else None
    operation = next((item for item in version.operations
                      if str(item.get("id")) == str(assignment["operation_id"])), None)
    if not operation or not operation.get("sop_id"):
        return None
    sop = session.get(SopDocument, uuid.UUID(str(operation["sop_id"])))
    if sop is None or sop.status != "approved" or sop.product_id != release.product_id:
        return None
    return {
        **assignment,
        "operation_name": str(operation["name"]),
        "sop_id": str(sop.id), "sop_title": sop.title, "sop_version": sop.version,
        "product_sop_version_id": str(version.id),
        "_attachments": operation.get("attachments", []),
    }


@router.post("/terminal/installation", response_model=InstallationPublic)
def register_terminal_installation(
    session: SessionDep, request: Request, body: InstallationInput,
) -> InstallationPublic:
    address = request.client.host if request.client else "unknown"
    attempts = redis_cache.incr(
        redis_cache.build_key("esop-installation", address), ttl_seconds=60,
    )
    if attempts is None:
        raise HTTPException(status_code=503, detail="Device number service is unavailable")
    if attempts > 60:
        raise HTTPException(status_code=429, detail="Too many device number requests")
    code = installation_device_code(session, body.installationId)
    session.commit()
    return InstallationPublic(deviceCode=code)


@router.post("/terminal/activate", response_model=DeviceIdentityPublic)
def activate_terminal(
    session: SessionDep, request: Request, body: ActivateInput,
    x_device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> DeviceIdentityPublic:
    address = request.client.host if request.client else "unknown"
    attempts = redis_cache.incr(
        redis_cache.build_key("esop-activation", address), ttl_seconds=60
    )
    if attempts is None:
        raise HTTPException(status_code=503, detail="Activation service is unavailable")
    if attempts > 60:
        raise HTTPException(status_code=429, detail="Too many activation attempts")
    identity, token = activate_device(
        session, key=body.key, device_code=body.deviceCode.strip(), tenant_code=body.tenantCode,
        old_token=x_device_token,
    )
    return DeviceIdentityPublic(
        deviceToken=token, tenantId=identity.tenant_id, deviceId=identity.terminal_id,
    )


@router.get("/terminal/profile")
def terminal_profile(
    session: SessionDep, device: DeviceDep, appVersion: str = "", request: Request = None
) -> dict[str, Any]:
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _terminal(session, device)
        terminal.last_seen_at = get_datetime_utc()
        if request is not None:
            candidate = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            candidate = candidate or (request.client.host if request.client else "")
            try:
                terminal.last_ip = str(ip_address(candidate)) if candidate else terminal.last_ip
            except ValueError:
                pass
        if terminal.device_code == "WEB":
            terminal.app_version = "Web版"
        elif appVersion:
            terminal.app_version = appVersion[:80]
        session.add(terminal)
        if terminal.station_id is None:
            profile = {"tenantId": str(device.tenant_id), "siteId": "", "siteCode": "", "siteName": "", "lineId": "", "lineName": ""}
        else:
            station = session.get(Station, terminal.station_id)
            if station is None:
                raise HTTPException(status_code=409, detail="Bound station is unavailable")
            line = session.get(ProductionLine, station.line_id)
            if line is None:
                raise HTTPException(status_code=409, detail="Bound line is unavailable")
            profile = {
                "tenantId": str(device.tenant_id),
                "siteId": str(station.id), "siteCode": str(station.position),
                "siteName": station.name or f"工位 {station.position}",
                "lineId": str(line.id), "lineName": line.name,
            }
        tenants = get_channel_customer_tenants(session=session, tenant_ids=[device.tenant_id])
        profile.update({
            "serialNumber": terminal.serial_number,
            "deviceName": terminal.device_name or "",
            "deviceCode": terminal.device_code,
            "tenantCode": next((tenant.code for tenant in tenants if tenant.id == device.tenant_id), ""),
            "tenantName": next((tenant.name for tenant in tenants if tenant.id == device.tenant_id), ""),
        })
        session.commit()
        return profile


@router.post("/terminal/unbind", status_code=204)
def terminal_unbind(_session: SessionDep, _device: DeviceDep) -> None:
    """Keep old clients compatible while prohibiting device-initiated release."""
    raise HTTPException(status_code=403, detail="终端不允许自行解除激活，请联系管理员在后台管理设备")


@router.post("/terminal/staff-login")
def terminal_staff_login(
    session: SessionDep, request: Request, device: DeviceDep, body: StaffLoginInput
) -> dict[str, str]:
    return authenticate_terminal_staff(
        session=session, request=request, tenant_id=device.tenant_id,
        username=body.username or body.empNo or "", password=body.password,
    )


@router.get("/terminal/staff-profile")
def terminal_staff_profile(
    session: SessionDep, device: DeviceDep,
    current_principal: CurrentPrincipal, tenant_context: CurrentTenant,
) -> dict[str, str]:
    if device.tenant_id != tenant_context.tenant_id:
        raise HTTPException(status_code=403, detail="Staff and device belong to different tenants")
    return get_terminal_staff_profile(
        session=session, tenant_id=device.tenant_id, user_id=current_principal.id,
    )


def _split_task_media(media: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    videos = [page for page in media if str(page.get("mimeType") or "").lower().startswith("video/")]
    pages = [page for page in media if not str(page.get("mimeType") or "").lower().startswith("video/")]
    return pages, videos


def _snapshot_attachments(assignment: dict[str, object]) -> list[OperationAttachment]:
    """Only use the approved snapshot; old flattened pages lack file boundaries."""
    raw = assignment.get("_attachments")
    if not isinstance(raw, list):
        return []
    attachments = []
    for item in raw:
        try:
            attachments.append(OperationAttachment.model_validate(item))
        except ValidationError:
            continue
    return attachments


def _video_playback_id(session: Session, files, tenant_id: uuid.UUID, original_id: uuid.UUID) -> uuid.UUID:
    rendition = session.exec(select(OperationFileRendition).where(
        OperationFileRendition.tenant_id == tenant_id,
        OperationFileRendition.original_file_id == original_id,
    )).first()
    if rendition is not None and files.get_accessible_file(tenant_id=tenant_id, file_id=rendition.display_file_id) is not None:
        return rendition.display_file_id
    return original_id


def _video_authorization_id(session: Session, files, tenant_id: uuid.UUID, requested_id: uuid.UUID) -> uuid.UUID:
    """Authorize a playback rendition against its original approved business reference."""
    rendition = session.exec(select(OperationFileRendition).where(
        OperationFileRendition.tenant_id == tenant_id,
        OperationFileRendition.display_file_id == requested_id,
    )).first()
    if rendition is not None:
        source = files.get_accessible_file(tenant_id=tenant_id, file_id=rendition.original_file_id)
        if source is not None and source.original_name.rsplit(".", 1)[-1].lower() in {"mp4", "webm", "mov"}:
            return rendition.original_file_id
    return requested_id


def _attachment_payload(assignment: dict[str, object], sop: SopDocument, files, tenant_id: uuid.UUID, session: Session | None = None):
    approved_pages = {str(page.get("file_id")) for page in sop.pages}
    attachments, resources = [], []
    for item in _snapshot_attachments(assignment):
        original = files.get_accessible_file(tenant_id=tenant_id, file_id=item.file_id)
        if original is None:
            continue
        pages = []
        if item.kind in {"image", "pdf", "word", "excel", "ppt"}:
            page_ids = item.display_pages or [item.display_file_id or item.file_id]
            for page_id in page_ids:
                if str(page_id) not in approved_pages:
                    break
                page = files.get_accessible_file(tenant_id=tenant_id, file_id=page_id)
                if page is None:
                    break
                pages.append({"fileId": str(page_id), "url": f"/api/v1/esop/terminal/files/{page_id}",
                              "mimeType": page.content_type or mimetypes.guess_type(page.original_name)[0] or "application/octet-stream"})
            if len(pages) != len(page_ids):
                continue
        playback_id = _video_playback_id(session, files, tenant_id, item.file_id) if item.kind == "video" and session is not None else item.file_id
        playback = files.get_accessible_file(tenant_id=tenant_id, file_id=playback_id) if playback_id != item.file_id else None
        payload = {"id": str(playback_id), "name": item.name, "kind": item.kind,
                   "mimeType": "video/mp4" if playback is not None else item.content_type or mimetypes.guess_type(item.name)[0] or "application/octet-stream",
                   "size": getattr(playback, "size", item.size), "url": f"/api/v1/esop/terminal/files/{playback_id}", "pages": pages}
        (resources if item.kind == "model_resource" else attachments).append(payload)
    return attachments, resources


def _legacy_renditions(session: Session, sop: SopDocument, tenant_id: uuid.UUID) -> list[OperationFileRendition]:
    """Recover original files only when every converted page belongs to this approved SOP."""
    page_ids = {str(page.get("file_id")) for page in sop.pages}
    return [
        item for item in session.exec(select(OperationFileRendition).where(
            OperationFileRendition.tenant_id == tenant_id,
        )).all()
        if item.page_file_ids and set(map(str, item.page_file_ids)) <= page_ids
    ]


def _legacy_attachment_payload(session: Session, sop: SopDocument, files, tenant_id: uuid.UUID) -> list[dict[str, object]]:
    """List recoverable originals and remaining approved pages without guessing file groups."""
    pages = [str(page["file_id"]) for page in sop.pages]
    page_order = {file_id: index for index, file_id in enumerate(pages)}
    result = []
    used = set()
    for rendition in _legacy_renditions(session, sop, tenant_id):
        page_ids = list(map(str, rendition.page_file_ids))
        if len(set(page_ids)) != len(page_ids) or used.intersection(page_ids):
            continue
        original = files.get_accessible_file(tenant_id=tenant_id, file_id=rendition.original_file_id)
        converted = [files.get_accessible_file(tenant_id=tenant_id, file_id=uuid.UUID(file_id))
                     for file_id in page_ids]
        if original is None or any(page is None for page in converted):
            continue
        name = original.original_name
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        kind = {"doc": "word", "docx": "word", "xls": "excel", "xlsx": "excel",
                "ppt": "ppt", "pptx": "ppt", "pdf": "pdf"}.get(extension)
        if kind is None:
            continue
        result.append((min(page_order[file_id] for file_id in page_ids), {
            "id": str(rendition.original_file_id), "name": name, "kind": kind,
            "mimeType": original.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
            "size": original.size,
            "url": f"/api/v1/esop/terminal/files/{rendition.original_file_id}",
            "pages": [{"fileId": file_id, "url": f"/api/v1/esop/terminal/files/{file_id}",
                       "mimeType": page.content_type or "image/png"}
                      for file_id, page in zip(page_ids, converted, strict=True)],
        }))
        used.update(page_ids)
    for index, page in enumerate(sop.pages):
        file_id = str(page["file_id"])
        if file_id in used:
            continue
        asset = files.get_accessible_file(tenant_id=tenant_id, file_id=uuid.UUID(file_id))
        if asset is None:
            continue
        mime_type = asset.content_type or mimetypes.guess_type(asset.original_name)[0] or "application/octet-stream"
        playback_id = _video_playback_id(session, files, tenant_id, uuid.UUID(file_id)) if mime_type.startswith("video/") else uuid.UUID(file_id)
        playback = files.get_accessible_file(tenant_id=tenant_id, file_id=playback_id) if str(playback_id) != file_id else None
        result.append((index, {
            "id": str(playback_id), "name": asset.original_name, "kind": "video" if mime_type.startswith("video/") else "image",
            "mimeType": "video/mp4" if playback is not None else mime_type, "size": getattr(playback, "size", asset.size),
            "url": f"/api/v1/esop/terminal/files/{playback_id}",
            "pages": [] if mime_type.startswith("video/") else [{
                "fileId": file_id, "url": f"/api/v1/esop/terminal/files/{file_id}", "mimeType": mime_type,
            }],
        }))
    return [item for _, item in sorted(result, key=lambda item: item[0])]


@router.get("/terminal/tasks")
def terminal_tasks(session: SessionDep, device: DeviceDep) -> dict[str, Any]:
    with EsopTenantUnitOfWork(session, device.tenant_id):
        from app.modules.esop.plan_scheduler import advance_due_plans
        advance_due_plans(session)
        terminal = _terminal(session, device)
        tasks = _active_tasks(session, terminal, advance_cursor=True)
        session.commit()
        product_ids = {release.product_id for release, _ in tasks}
        directory = product_directory_for_tenant(session, device.tenant_id)
        files = get_file_asset_directory(session)
        products = {id: directory.get(id) for id in product_ids}
        result = []
        for release, stored_assignment in tasks:
            assignment = current_assignment(session, release, stored_assignment)
            if assignment is None:
                continue
            order = session.get(ProductionOrder, release.order_id)
            if order is None:
                continue
            product = products.get(release.product_id)
            sop_id = uuid.UUID(str(assignment["sop_id"]))
            sop = session.get(SopDocument, sop_id)
            if sop is None:
                continue
            media = []
            for page in sop.pages:
                file = files.get_accessible_file(
                    tenant_id=device.tenant_id, file_id=uuid.UUID(str(page["file_id"])),
                )
                content_type = file.content_type if file else None
                if file and content_type in {None, "application/octet-stream"}:
                    content_type = mimetypes.guess_type(file.original_name)[0]
                playback_id = uuid.UUID(str(page["file_id"]))
                if (content_type or "").startswith("video/"):
                    playback_id = _video_playback_id(session, files, device.tenant_id, playback_id)
                    if str(playback_id) != str(page["file_id"]):
                        content_type = "video/mp4"
                media.append({
                    "fileId": str(playback_id), "sort": page["sort"],
                    "caption": page.get("caption"),
                    "mimeType": content_type or "application/octet-stream",
                    "url": f"/api/v1/esop/terminal/files/{playback_id}",
                })
            pages, videos = _split_task_media(media)
            attachments, resources = _attachment_payload(assignment, sop, files, device.tenant_id, session)
            if not assignment.get("_attachments"):
                attachments = _legacy_attachment_payload(session, sop, files, device.tenant_id)
            result.append({
                "id": str(release.id), "releaseId": str(release.id),
                "orderId": str(release.order_id), "orderCode": order.code,
                "productId": str(release.product_id),
                "productCode": product.code if product else "",
                "productName": product.name if product else "",
                "productModel": product.model if product else None,
                "productCategoryId": str(product.category_id) if product and product.category_id else "",
                "productCategoryName": product.category_name if product else "",
                "planQty": release.quantity,
                "operationId": str(assignment["operation_id"]),
                "operationName": assignment["operation_name"],
                "sopId": str(sop_id), "sopVersion": assignment["sop_version"],
                "title": assignment["sop_title"], "displayActive": True,
                "productSopVersionId": assignment.get("product_sop_version_id") or (str(release.product_sop_version_id) if release.product_sop_version_id else None),
                "pages": pages,
                "videos": videos,
                "attachments": attachments, "resources": resources, "defaultAttachmentId": None,
                # Existing Android clients play `attachment`; newer clients may consume all videos.
                "attachment": videos[0]["url"] if videos else "",
            })
        broadcasts = session.exec(
            select(Broadcast).where(Broadcast.is_active == True).order_by(Broadcast.position)  # noqa: E712
        ).all()
        ads = session.exec(select(Advertisement).where(Advertisement.is_active == True)  # noqa: E712
                           .order_by(Advertisement.created_at, Advertisement.id)).all()
        return {
            "serverTime": get_datetime_utc(),
            "advertisements": [{
                "id": str(ad.id), "title": ad.title, "layout": ad.layout,
                "playback": ad.playback, "intervalMinutes": ad.interval_minutes,
                "startsAt": ad.starts_at, "endsAt": ad.ends_at,
                "dailyStart": ad.daily_start, "dailyEnd": ad.daily_end,
                "updatedAt": ad.updated_at,
                "media": [{**item, "url": f"/api/v1/esop/terminal/files/{item['file_id']}" if item.get("file_id") else ""}
                          for item in ad.media],
            } for ad in ads if terminal.station_id],
            "list": result,
            "broadcasts": [{
                "position": item.position,
                "content": item.content,
                "fontSize": item.font_size,
                "backgroundColor": item.background_color,
                "fontColor": item.font_color,
                "updatedAt": item.updated_at,
            } for item in broadcasts],
        }


@router.get("/terminal/sop-catalog")
def terminal_sop_catalog(session: SessionDep, device: DeviceDep) -> dict[str, list[dict[str, object]]]:
    """Authenticate on every request, including cache hits."""
    with EsopTenantUnitOfWork(session, device.tenant_id):
        _terminal(session, device)

    def build():
        # DeviceDep has already SELECTed in the request transaction. Start a fresh read
        # view *after* generations were captured, so an old MySQL RR snapshot cannot
        # populate the latest Redis generation with stale approved guidance.
        with Session(session.get_bind()) as read_session:
            return _build_terminal_sop_catalog(read_session, device)

    return cached_catalog(device.tenant_id, build)


def _build_terminal_sop_catalog(session: Session, device: DeviceIdentity) -> dict[str, list[dict[str, object]]]:
    """Read approved SOPs for active products in the device's tenant."""
    with EsopTenantUnitOfWork(session, device.tenant_id):
        _terminal(session, device)
        directory = product_directory_for_tenant(session, device.tenant_id)
        categories, product_list = directory.tree()
        products = {product.id: product for product in product_list}
        category_names = {category.id: category.name for category in categories}
        product_ids = set(products)
        if not product_ids:
            return {"list": []}
        versions = session.exec(select(ProductSopVersion).where(
            ProductSopVersion.tenant_id == device.tenant_id,
            ProductSopVersion.status == "approved",
            col(ProductSopVersion.product_id).in_(product_ids),
        ).order_by(ProductSopVersion.product_id, ProductSopVersion.version.desc())).all()
        latest = {}
        for version in versions:
            latest.setdefault(version.product_id, version)
        files = get_file_asset_directory(session)
        result = []
        for product_id, version in sorted(latest.items(), key=lambda pair: (
            category_names.get(products[pair[0]].category_id, ""), products[pair[0]].code,
        )):
            product = products[product_id]
            for operation in version.operations:
                sop_id = operation.get("sop_id")
                if not sop_id:
                    continue
                sop = session.get(SopDocument, uuid.UUID(str(sop_id)))
                if sop is None or sop.tenant_id != device.tenant_id or sop.status != "approved" or sop.product_id != product_id:
                    continue
                assignment = {"_attachments": operation.get("attachments", [])}
                attachments, resources = _attachment_payload(assignment, sop, files, device.tenant_id, session)
                if not assignment["_attachments"]:
                    attachments = _legacy_attachment_payload(session, sop, files, device.tenant_id)
                pages = [{"fileId": str(page["file_id"]), "sort": page.get("sort", 0),
                          "url": f"/api/v1/esop/terminal/files/{page['file_id']}"}
                         for page in sop.pages]
                result.append({
                    "productId": str(product_id), "productCode": product.code,
                    "productName": product.name,
                    "productModel": product.model,
                    "productCategoryName": category_names.get(product.category_id, ""),
                    "operationId": str(operation["id"]),
                    "operationName": str(operation["name"]),
                    "title": sop.title, "workCode": sop.title,
                    "sopId": str(sop.id), "sopVersion": sop.version,
                    "pages": pages, "attachments": attachments, "resources": resources,
                })
        return {"list": result}


@router.get("/terminal/files/{file_id}", response_model=None)
def terminal_file(
    session: SessionDep, device: DeviceDep, file_id: uuid.UUID
) -> FileResponse | StreamingResponse:
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _terminal(session, device)
        files = get_file_asset_directory(session)
        authorization_id = _video_authorization_id(session, files, device.tenant_id, file_id)
        active_tasks = _active_tasks(session, terminal)
        for release, stored_assignment in active_tasks:
            assignment = current_assignment(session, release, stored_assignment)
            if assignment is None:
                continue
            sop = session.get(SopDocument, uuid.UUID(str(assignment["sop_id"])))
            snapshot_ids = {
                str(value) for item in _snapshot_attachments(assignment)
                for value in (item.file_id, item.display_file_id, *item.display_pages)
                if value is not None
            }
            if sop and not assignment.get("_attachments"):
                snapshot_ids.update(str(item.original_file_id) for item in _legacy_renditions(
                    session, sop, device.tenant_id
                ))
            if sop and (str(authorization_id) in snapshot_ids or any(page.get("file_id") == str(authorization_id) for page in sop.pages)):
                return preview_authorized_file(
                    session=session, tenant_id=device.tenant_id, file_id=file_id
                )
        _, product_list = product_directory_for_tenant(session, device.tenant_id).tree()
        product_ids = {product.id for product in product_list}
        if product_ids:
            versions = session.exec(select(ProductSopVersion).where(
                ProductSopVersion.tenant_id == device.tenant_id,
                ProductSopVersion.status == "approved",
                col(ProductSopVersion.product_id).in_(product_ids),
            ).order_by(ProductSopVersion.product_id, ProductSopVersion.version.desc())).all()
            latest = {}
            for version in versions:
                latest.setdefault(version.product_id, version)
            for version in latest.values():
                for operation in version.operations:
                    sop_id = operation.get("sop_id")
                    if not sop_id:
                        continue
                    sop = session.get(SopDocument, uuid.UUID(str(sop_id)))
                    if sop is None or sop.tenant_id != device.tenant_id or sop.status != "approved" or sop.product_id != version.product_id:
                        continue
                    file_ids = {str(page.get("file_id")) for page in sop.pages}
                    for item in _snapshot_attachments({"_attachments": operation.get("attachments", [])}):
                        file_ids.update(str(value) for value in
                                        (item.file_id, item.display_file_id, *item.display_pages) if value)
                    if not operation.get("attachments"):
                        file_ids.update(str(item.original_file_id) for item in
                                        _legacy_renditions(session, sop, device.tenant_id))
                    if str(authorization_id) in file_ids:
                        return preview_authorized_file(
                            session=session, tenant_id=device.tenant_id, file_id=file_id
                        )
        ads = session.exec(select(Advertisement).where(Advertisement.is_active == True)).all()  # noqa: E712
        if terminal.station_id and any(str(file_id) == item.get("file_id") for ad in ads for item in ad.media):
            return preview_authorized_file(session=session, tenant_id=device.tenant_id, file_id=file_id)
        raise HTTPException(status_code=404, detail="Task media not found")


def _terminal_public(row: Terminal, now=None) -> TerminalPublic:
    now = now or get_datetime_utc()
    seen = row.last_seen_at
    if seen is not None:
        seen = seen.replace(tzinfo=UTC) if seen.tzinfo is None else seen.astimezone(UTC)
    return TerminalPublic.model_validate(row).model_copy(update={
        "is_online": row.is_active and seen is not None and now - timedelta(seconds=120) <= seen <= now,
    })


@router.get(
    "/terminals",
    dependencies=[Depends(require_module_access("esop", "esop:device:list"))],
    response_model=ListTerminals,
)
def list_terminals(uow: EsopTenantUowDep) -> ListTerminals:
    rows = uow.session.exec(select(Terminal).order_by(Terminal.created_at.desc())).all()
    now = get_datetime_utc()
    return ListTerminals(
        items=[_terminal_public(row, now) for row in rows], total=len(rows),
    )


@router.put(
    "/terminals/{id}/name",
    dependencies=[Depends(require_module_access("esop", "esop:device:bind"))],
    response_model=TerminalPublic,
)
def update_terminal_name(
    uow: EsopTenantUowDep, id: uuid.UUID, body: TerminalNameInput,
) -> TerminalPublic:
    terminal = uow.session.get(Terminal, id)
    if terminal is None or terminal.tenant_id != uow.tenant_id:
        raise HTTPException(status_code=404, detail="Terminal not found")
    name = body.device_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="请输入设备名称")
    terminal.device_name = name
    uow.session.add(terminal)
    uow.session.commit()
    return _terminal_public(terminal)


@router.put(
    "/terminals/{id}/station",
    dependencies=[Depends(require_module_access("esop", "esop:device:bind"))],
    response_model=TerminalPublic,
)
def bind_terminal_station(
    uow: EsopTenantUowDep, id: uuid.UUID, body: StationBindInput
) -> TerminalPublic:
    terminal = uow.session.get(Terminal, id)
    if terminal is None or terminal.tenant_id != uow.tenant_id or not terminal.is_active:
        raise HTTPException(status_code=404, detail="Terminal not found")
    if body.station_id is not None:
        station = uow.session.get(Station, body.station_id)
        if station is None or station.tenant_id != uow.tenant_id:
            raise HTTPException(status_code=404, detail="Station not found")
        # A deleted line cannot acquire a new terminal binding after the reference check.
        line = uow.session.exec(
            select(ProductionLine).where(ProductionLine.id == station.line_id).with_for_update()
        ).first()
        if line is None or line.tenant_id != uow.tenant_id:
            raise HTTPException(status_code=404, detail="工位所属产线不存在")
        bound = uow.session.exec(
            select(Terminal).where(
                Terminal.station_id == body.station_id, Terminal.is_active == True  # noqa: E712
            )
        ).first()
        if bound is not None and bound.id != terminal.id:
            raise HTTPException(status_code=409, detail="Station is already bound")
    terminal.station_id = body.station_id
    uow.session.add(terminal)
    uow.session.commit()
    return _terminal_public(terminal)
