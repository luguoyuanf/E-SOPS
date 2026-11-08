"""One editable ticker setting per tenant and terminal position."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import (
    Advertisement,
    Broadcast,
    BroadcastRecord,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUowDep
from app.modules.esop.public_api.broadcast_dto import (
    AdvertisementInput,
    AdvertisementPublic,
    BroadcastInput,
    BroadcastPublic,
    BroadcastRecordPublic,
    ListAdvertisements,
    ListBroadcastRecords,
    ListBroadcasts,
)
from app.platform.public_api.files import FileDirectRead
from app.platform.web_api import (
    CurrentPrincipal,
    get_file_asset_directory,
    require_module_access,
    upload_authorized_file,
)

router = APIRouter(prefix="/esop", tags=["esop-broadcast"])


@router.get(
    "/broadcasts",
    dependencies=[Depends(require_module_access("esop", "esop:broadcast:list"))],
    response_model=ListBroadcasts,
)
def list_broadcasts(uow: EsopTenantUowDep) -> ListBroadcasts:
    rows = uow.session.exec(select(Broadcast).order_by(Broadcast.position)).all()
    return ListBroadcasts(items=[BroadcastPublic.model_validate(row) for row in rows], total=len(rows))


@router.put(
    "/broadcasts/{position}",
    dependencies=[Depends(require_module_access("esop", "esop:broadcast:manage"))],
    response_model=BroadcastPublic,
)
def save_broadcast(
    uow: EsopTenantUowDep, position: Literal["top", "bottom"],
    body: BroadcastInput,
) -> BroadcastPublic:
    record = uow.session.exec(select(BroadcastRecord).where(BroadcastRecord.position == position)
                              .order_by(BroadcastRecord.is_active.desc(), BroadcastRecord.created_at.desc())).first()
    _save_broadcast_record(uow, position, body, record.id if record else None)
    row = uow.session.exec(select(Broadcast).where(Broadcast.position == position)).one()
    return BroadcastPublic.model_validate(row)


MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "video/mp4", "video/webm"}


@router.post("/advertisements/files/upload", dependencies=[Depends(require_module_access("esop", "esop:broadcast:manage"))])
def upload_advertisement_file(
    uow: EsopTenantUowDep, principal: CurrentPrincipal, file: UploadFile = File(...),
) -> dict[str, uuid.UUID]:
    if file.content_type not in MEDIA_TYPES:
        raise HTTPException(status_code=422, detail="广告素材仅支持 JPG/PNG/WebP/GIF 和 MP4/WebM")
    return {"id": upload_authorized_file(
        session=uow.session, tenant_id=uow.tenant_id, uploader_id=principal.id, file=file,
    )}


@router.get("/advertisements", response_model=ListAdvertisements,
            dependencies=[Depends(require_module_access("esop", "esop:broadcast:list"))])
def list_advertisements(
    uow: EsopTenantUowDep, keyword: str | None = None,
    status: Literal["active", "paused", "scheduled", "ended"] | None = None,
    created_from: datetime | None = None, created_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ListAdvertisements:
    filters = []
    now = get_datetime_utc()
    if keyword and keyword.strip():
        filters.append(Advertisement.title.contains(keyword.strip(), autoescape=True))
    if status == "paused":
        filters.append(Advertisement.is_active == False)  # noqa: E712
    elif status:
        filters.append(Advertisement.is_active == True)  # noqa: E712
        if status == "scheduled":
            filters.append(Advertisement.starts_at > now)
        elif status == "ended":
            filters.append(Advertisement.ends_at <= now)
        else:
            filters.extend([Advertisement.starts_at <= now, or_(Advertisement.ends_at.is_(None), Advertisement.ends_at > now)])
    _created_filters(filters, Advertisement, created_from, created_to)
    total = uow.session.exec(select(func.count()).select_from(Advertisement).where(*filters)).one()
    rows = uow.session.exec(select(Advertisement).where(*filters).order_by(Advertisement.created_at.desc(), Advertisement.id)
                            .offset((page - 1) * page_size).limit(page_size)).all()
    return ListAdvertisements(items=[AdvertisementPublic.model_validate(row) for row in rows], total=total)


def _save_advertisement(uow, body, row=None):
    values = body.model_dump(mode="json")
    now = get_datetime_utc()
    start = body.starts_at or (row.starts_at if row else now)
    if body.ends_at and body.ends_at <= start:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
    files = get_file_asset_directory(uow.session)
    for index, item in enumerate(body.media):
        if item.kind == "text":
            continue
        asset = files.get_accessible_file(tenant_id=uow.tenant_id, file_id=item.file_id)
        if asset is None or asset.content_type not in MEDIA_TYPES or not asset.content_type.startswith(f"{item.kind}/"):
            raise HTTPException(status_code=422, detail="素材不存在、类型不匹配或不属于当前租户")
        values["media"][index]["name"] = asset.original_name
    values.update(starts_at=start, ends_at=body.ends_at, updated_at=now)
    if row is None:
        row = Advertisement(tenant_id=uow.tenant_id, **values)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    uow.session.add(row)
    uow.session.commit()
    return AdvertisementPublic.model_validate(row)


@router.post("/advertisements", response_model=AdvertisementPublic,
             dependencies=[Depends(require_module_access("esop", "esop:broadcast:manage"))])
def create_advertisement(uow: EsopTenantUowDep, body: AdvertisementInput) -> AdvertisementPublic:
    return _save_advertisement(uow, body)


@router.put("/advertisements/{id}", response_model=AdvertisementPublic,
            dependencies=[Depends(require_module_access("esop", "esop:broadcast:manage"))])
def update_advertisement(uow: EsopTenantUowDep, id: uuid.UUID, body: AdvertisementInput) -> AdvertisementPublic:
    row = uow.session.get(Advertisement, id)
    if row is None:
        raise HTTPException(status_code=404, detail="广告任务不存在")
    return _save_advertisement(uow, body, row)


@router.delete("/advertisements/{id}", dependencies=[Depends(require_module_access("esop", "esop:broadcast:manage"))])
def delete_advertisement(uow: EsopTenantUowDep, id: uuid.UUID) -> dict[str, bool]:
    row = uow.session.get(Advertisement, id)
    if row is None:
        raise HTTPException(status_code=404, detail="广告任务不存在")
    uow.session.delete(row)
    uow.session.commit()
    return {"success": True}


@router.get("/advertisements/files/{file_id}/access", response_model=FileDirectRead,
            dependencies=[Depends(require_module_access("esop", "esop:broadcast:list"))])
def advertisement_file_access(
    uow: EsopTenantUowDep, principal: CurrentPrincipal, file_id: uuid.UUID,
) -> FileDirectRead:
    files = get_file_asset_directory(uow.session)
    rows = uow.session.exec(select(Advertisement)).all()
    if any(item.get("file_id") == str(file_id) for row in rows for item in row.media):
        return files.direct_read_url(tenant_id=uow.tenant_id, file_id=file_id)
    return files.direct_uploaded_read_url(
        tenant_id=uow.tenant_id, file_id=file_id, uploader_id=principal.id,
    )


def _created_filters(filters, model, created_from, created_to):
    for value in (created_from, created_to):
        if value is not None and value.tzinfo is None:
            raise HTTPException(status_code=422, detail="查询时间必须包含时区")
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=422, detail="查询开始时间不能晚于结束时间")
    if created_from:
        filters.append(model.created_at >= created_from)
    if created_to:
        filters.append(model.created_at <= created_to)


@router.get("/broadcast-records/{position}", response_model=ListBroadcastRecords,
            dependencies=[Depends(require_module_access("esop", "esop:broadcast:list"))])
def list_broadcast_records(
    uow: EsopTenantUowDep, position: Literal["top", "bottom"], keyword: str | None = None,
    status: Literal["active", "paused"] | None = None,
    created_from: datetime | None = None, created_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ListBroadcastRecords:
    filters = [BroadcastRecord.position == position]
    if keyword and keyword.strip():
        filters.append(BroadcastRecord.content.contains(keyword.strip(), autoescape=True))
    if status:
        filters.append(BroadcastRecord.is_active == (status == "active"))
    _created_filters(filters, BroadcastRecord, created_from, created_to)
    total = uow.session.exec(select(func.count()).select_from(BroadcastRecord).where(*filters)).one()
    rows = uow.session.exec(select(BroadcastRecord).where(*filters).order_by(BroadcastRecord.created_at.desc(), BroadcastRecord.id)
                            .offset((page - 1) * page_size).limit(page_size)).all()
    return ListBroadcastRecords(items=[BroadcastRecordPublic.model_validate(row) for row in rows], total=total)


def _lock_broadcast_slot(uow, position, body):
    slot = uow.session.exec(select(Broadcast).where(Broadcast.position == position).with_for_update()).first()
    if slot is None:
        slot = Broadcast(tenant_id=uow.tenant_id, position=position, **{**body.model_dump(), "is_active": False})
        uow.session.add(slot)
        try:
            uow.session.flush()
        except IntegrityError as exc:
            uow.session.rollback()
            raise HTTPException(status_code=409, detail="广播位置正在更新，请重试") from exc
    return slot


def _save_broadcast_record(uow, position, body, record_id=None):
    slot = _lock_broadcast_slot(uow, position, body)
    row = None
    if record_id:
        row = uow.session.exec(select(BroadcastRecord).where(BroadcastRecord.id == record_id,
                                BroadcastRecord.position == position).with_for_update()
                                .execution_options(populate_existing=True)).first()
        if row is None:
            raise HTTPException(status_code=404, detail="广播记录不存在")
    was_active = bool(row and row.is_active)
    now = get_datetime_utc()
    if body.is_active:
        active = uow.session.exec(select(BroadcastRecord).where(BroadcastRecord.position == position,
                                  BroadcastRecord.is_active == True).with_for_update()  # noqa: E712
                                  .execution_options(populate_existing=True)).all()
        for item in active:
            item.is_active = False
            item.updated_at = now
            uow.session.add(item)
        for key, value in body.model_dump().items():
            setattr(slot, key, value)
        slot.updated_at = now
    elif was_active:
        slot.is_active = False
        slot.updated_at = now
    if row is None:
        row = BroadcastRecord(tenant_id=uow.tenant_id, position=position, **body.model_dump())
    else:
        for key, value in body.model_dump().items():
            setattr(row, key, value)
        row.updated_at = now
    uow.session.add_all([slot, row])
    uow.session.commit()
    return BroadcastRecordPublic.model_validate(row)


@router.post("/broadcast-records/{position}", response_model=BroadcastRecordPublic,
             dependencies=[Depends(require_module_access("esop", "esop:broadcast:manage"))])
def create_broadcast_record(uow: EsopTenantUowDep, position: Literal["top", "bottom"], body: BroadcastInput) -> BroadcastRecordPublic:
    return _save_broadcast_record(uow, position, body)


@router.put("/broadcast-records/{position}/{id}", response_model=BroadcastRecordPublic,
            dependencies=[Depends(require_module_access("esop", "esop:broadcast:manage"))])
def update_broadcast_record(uow: EsopTenantUowDep, position: Literal["top", "bottom"], id: uuid.UUID,
                            body: BroadcastInput) -> BroadcastRecordPublic:
    # Resolve the reference before creating/locking the position slot.
    row = uow.session.exec(select(BroadcastRecord).where(BroadcastRecord.id == id, BroadcastRecord.position == position)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="广播记录不存在")
    return _save_broadcast_record(uow, position, body, id)


@router.delete("/broadcast-records/{position}/{id}",
               dependencies=[Depends(require_module_access("esop", "esop:broadcast:manage"))])
def delete_broadcast_record(uow: EsopTenantUowDep, position: Literal["top", "bottom"], id: uuid.UUID) -> dict[str, bool]:
    row = uow.session.exec(select(BroadcastRecord).where(BroadcastRecord.id == id, BroadcastRecord.position == position)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="广播记录不存在")
    slot = _lock_broadcast_slot(uow, position, BroadcastInput.model_validate(row, from_attributes=True))
    row = uow.session.exec(select(BroadcastRecord).where(BroadcastRecord.id == id).with_for_update()
                            .execution_options(populate_existing=True)).one()
    if row.is_active:
        slot.is_active = False
        slot.updated_at = get_datetime_utc()
        uow.session.add(slot)
    uow.session.delete(row)
    uow.session.commit()
    return {"success": True}
