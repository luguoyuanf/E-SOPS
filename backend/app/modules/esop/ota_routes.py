"""Global channel hardware packages with one active release per model."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import select

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import (
    ActivationKey,
    Channel,
    ChannelAdmin,
    ChannelCustomerTenant,
    HardwareModel,
    OtaPackage,
    Terminal,
)
from app.modules.esop.infrastructure.tenant_uow import (
    EsopTenantUnitOfWork,
    EsopTenantUowDep,
)
from app.modules.esop.public_api.ota_dto import (
    ChannelInput,
    ChannelPublic,
    HardwareInput,
    HardwarePublic,
    OtaManifest,
    OtaPackageInput,
    OtaPackagePublic,
)
from app.modules.esop.terminal_routes import DeviceDep
from app.platform.public_api.codes import generate_entity_code
from app.platform.web_api import (
    CurrentPrincipal,
    CurrentTenant,
    FileAssetDirectoryDep,
    SessionDep,
    download_authorized_file,
    get_authorized_file,
    require_module_access,
    upload_authorized_file,
)

router = APIRouter(prefix="/esop", tags=["esop-ota"])
OTA_TYPES = {
    "application/vnd.android.package-archive", "application/octet-stream",
    "application/x-msdownload", "application/vnd.debian.binary-package",
    "application/x-debian-package", "application/x-appimage",
}


def _admin(principal: CurrentPrincipal) -> None:
    if not principal.is_superuser:
        raise HTTPException(status_code=403, detail="Platform administrator required")


def _visible_channels(session: SessionDep, principal: CurrentPrincipal, tenant: CurrentTenant) -> set[uuid.UUID] | None:
    """Resolve download scope from verified identity and persisted channel ownership."""
    if principal.is_superuser:
        return None
    channels = set(session.exec(select(ChannelAdmin.channel_id).where(
        ChannelAdmin.user_id == principal.id,
    )).all())
    channels.update(session.exec(select(ChannelCustomerTenant.channel_id).where(
        ChannelCustomerTenant.tenant_id == tenant.tenant_id,
    )).all())
    return channels


def _hardware(session: SessionDep, channel_id: uuid.UUID, hardware_model_id: uuid.UUID) -> HardwareModel:
    hardware = session.get(HardwareModel, hardware_model_id)
    if hardware is None or hardware.channel_id != channel_id:
        raise HTTPException(status_code=422, detail="Hardware model does not match channel")
    return hardware


@router.get("/channels", dependencies=[Depends(require_module_access("esop", "esop:ota:list"))])
def list_channels(session: SessionDep, principal: CurrentPrincipal, tenant: CurrentTenant) -> dict[str, Any]:
    scope = _visible_channels(session, principal, tenant)
    statement = select(Channel)
    if scope is not None:
        statement = statement.where(Channel.id.in_(scope))
    rows = session.exec(statement.order_by(Channel.code)).all()
    return {"items": [ChannelPublic.model_validate(row) for row in rows], "total": len(rows)}


@router.post("/channels", dependencies=[Depends(require_module_access("esop", "esop:ota:manage"))], response_model=ChannelPublic)
def create_channel(session: SessionDep, principal: CurrentPrincipal, body: ChannelInput) -> ChannelPublic:
    _admin(principal)
    body.code = body.code or generate_entity_code("CH")
    if session.exec(select(Channel.id).where(Channel.code == body.code)).first():
        raise HTTPException(status_code=409, detail="Channel code already exists")
    row = Channel(**body.model_dump())
    session.add(row)
    session.commit()
    return ChannelPublic.model_validate(row)


@router.put("/channels/{id}", dependencies=[Depends(require_module_access("esop", "esop:ota:manage"))], response_model=ChannelPublic)
def update_channel(session: SessionDep, principal: CurrentPrincipal, id: uuid.UUID, body: ChannelInput) -> ChannelPublic:
    _admin(principal)
    row = session.get(Channel, id)
    if row is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    body.code = body.code or row.code
    if row.code != body.code and session.exec(select(Channel.id).where(Channel.code == body.code)).first():
        raise HTTPException(status_code=409, detail="Channel code already exists")
    row.code, row.name = body.code, body.name
    session.add(row)
    session.commit()
    return ChannelPublic.model_validate(row)


@router.get("/hardware-models", dependencies=[Depends(require_module_access("esop", "esop:ota:list"))])
def list_hardware_models(session: SessionDep, principal: CurrentPrincipal, tenant: CurrentTenant, channel_id: uuid.UUID | None = None) -> dict[str, Any]:
    scope = _visible_channels(session, principal, tenant)
    statement = select(HardwareModel)
    if scope is not None:
        statement = statement.where(HardwareModel.channel_id.in_(scope))
    if channel_id:
        statement = statement.where(HardwareModel.channel_id == channel_id)
    rows = session.exec(statement.order_by(HardwareModel.code)).all()
    return {"items": [HardwarePublic.model_validate(row) for row in rows], "total": len(rows)}


@router.post("/hardware-models", dependencies=[Depends(require_module_access("esop", "esop:ota:manage"))], response_model=HardwarePublic)
def create_hardware_model(session: SessionDep, principal: CurrentPrincipal, body: HardwareInput) -> HardwarePublic:
    _admin(principal)
    if session.get(Channel, body.channel_id) is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    body.code = body.code or generate_entity_code("HW")
    if session.exec(select(HardwareModel.id).where(HardwareModel.channel_id == body.channel_id, HardwareModel.code == body.code)).first():
        raise HTTPException(status_code=409, detail="Hardware code already exists")
    row = HardwareModel(**body.model_dump())
    session.add(row)
    session.commit()
    return HardwarePublic.model_validate(row)


@router.put("/hardware-models/{id}", dependencies=[Depends(require_module_access("esop", "esop:ota:manage"))], response_model=HardwarePublic)
def update_hardware_model(session: SessionDep, principal: CurrentPrincipal, id: uuid.UUID, body: HardwareInput) -> HardwarePublic:
    _admin(principal)
    row = session.get(HardwareModel, id)
    if row is None:
        raise HTTPException(status_code=404, detail="Hardware model not found")
    if session.get(Channel, body.channel_id) is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    body.code = body.code or row.code
    if (row.channel_id, row.code) != (body.channel_id, body.code) and session.exec(select(HardwareModel.id).where(HardwareModel.channel_id == body.channel_id, HardwareModel.code == body.code)).first():
        raise HTTPException(status_code=409, detail="Hardware code already exists")
    if (row.channel_id, row.abi) != (body.channel_id, body.abi) and (
        session.exec(select(ActivationKey.id).where(ActivationKey.hardware_model_id == id)).first()
        or session.exec(select(OtaPackage.id).where(OtaPackage.hardware_model_id == id)).first()
    ):
        raise HTTPException(status_code=409, detail="Assigned hardware channel and ABI cannot change")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    session.add(row)
    session.commit()
    return HardwarePublic.model_validate(row)


@router.post("/ota/files/upload", dependencies=[Depends(require_module_access("esop", "esop:ota:manage"))])
def upload_ota_file(
    uow: EsopTenantUowDep, principal: CurrentPrincipal, file: UploadFile = File(...)
) -> dict[str, uuid.UUID]:
    _admin(principal)
    if (file.content_type or "").lower() not in OTA_TYPES:
        raise HTTPException(status_code=422, detail="OTA package must be APK, EXE, DEB or AppImage")
    return {"id": upload_authorized_file(
        session=uow.session, tenant_id=uow.tenant_id,
        uploader_id=principal.id, file=file,
        allowed_extensions={"apk", "exe", "deb", "appimage"}, max_size_mb=512,
    )}


def _package_public(row: OtaPackage, session: SessionDep) -> OtaPackagePublic:
    file = get_authorized_file(session=session, tenant_id=row.file_owner_tenant_id, file_id=row.file_id)
    return OtaPackagePublic.model_validate(row).model_copy(
        update={"file_name": file.original_name if file else ""}
    )


@router.get("/ota/packages", dependencies=[Depends(require_module_access("esop", "esop:ota:list"))])
def list_ota_packages(session: SessionDep, principal: CurrentPrincipal, tenant: CurrentTenant) -> dict[str, Any]:
    scope = _visible_channels(session, principal, tenant)
    statement = select(OtaPackage)
    if scope is not None:
        statement = statement.where(OtaPackage.channel_id.in_(scope), OtaPackage.status == "published")
    rows = session.exec(statement.order_by(OtaPackage.created_at.desc())).all()
    return {"items": [_package_public(row, session) for row in rows], "total": len(rows)}


@router.get("/ota/packages/{id}/download", dependencies=[Depends(require_module_access("esop", "esop:ota:list"))], response_model=None)
def download_installation_package(
    session: SessionDep, principal: CurrentPrincipal, tenant: CurrentTenant, id: uuid.UUID,
) -> FileResponse | StreamingResponse:
    scope = _visible_channels(session, principal, tenant)
    row = session.get(OtaPackage, id)
    if row is None or (scope is not None and (row.channel_id not in scope or row.status != "published")):
        raise HTTPException(status_code=404, detail="OTA package not found")
    return download_authorized_file(session=session, tenant_id=row.file_owner_tenant_id, file_id=row.file_id)


@router.post("/ota/packages", dependencies=[Depends(require_module_access("esop", "esop:ota:manage"))], response_model=OtaPackagePublic)
def create_ota_package(
    uow: EsopTenantUowDep, principal: CurrentPrincipal,
    files: FileAssetDirectoryDep, body: OtaPackageInput,
) -> OtaPackagePublic:
    _admin(principal)
    _hardware(uow.session, body.channel_id, body.hardware_model_id)
    file = files.get_accessible_file(tenant_id=uow.tenant_id, file_id=body.file_id)
    if file is None:
        raise HTTPException(status_code=422, detail="Package file not found in selected tenant")
    if not file.original_name.lower().endswith((".apk", ".exe", ".deb", ".appimage")):
        raise HTTPException(status_code=422, detail="OTA package must be APK, EXE, DEB or AppImage")
    if uow.session.exec(select(OtaPackage.id).where(
        OtaPackage.hardware_model_id == body.hardware_model_id,
        OtaPackage.version == body.version,
    )).first():
        raise HTTPException(status_code=409, detail="Version already exists for model")
    row = OtaPackage(
        **body.model_dump(), file_owner_tenant_id=uow.tenant_id,
        checksum_sha256=file.sha256, file_size=file.size,
    )
    uow.session.add(row)
    uow.session.commit()
    return _package_public(row, uow.session)


@router.post("/ota/packages/{id}/publish", dependencies=[Depends(require_module_access("esop", "esop:ota:publish"))], response_model=OtaPackagePublic)
def publish_ota_package(session: SessionDep, principal: CurrentPrincipal, id: uuid.UUID) -> OtaPackagePublic:
    _admin(principal)
    row = session.get(OtaPackage, id)
    if row is None:
        raise HTTPException(status_code=404, detail="OTA package not found")
    session.exec(
        select(HardwareModel).where(HardwareModel.id == row.hardware_model_id).with_for_update()
    ).one()
    session.refresh(row)
    if row.status == "published":
        raise HTTPException(status_code=409, detail="Package is already published")
    previous = session.exec(select(OtaPackage).where(
        OtaPackage.hardware_model_id == row.hardware_model_id,
        OtaPackage.status == "published",
    )).all()
    for item in previous:
        item.status = "superseded"
        session.add(item)
    row.status = "published"
    row.published_at = get_datetime_utc()
    session.add(row)
    session.commit()
    return _package_public(row, session)


@router.get("/terminal/ota", response_model=OtaManifest | None)
def terminal_ota(session: SessionDep, device: DeviceDep) -> OtaManifest | None:
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = session.get(Terminal, device.terminal_id)
        if terminal is None or not terminal.is_active:
            raise HTTPException(status_code=401, detail="Invalid device credential")
        if terminal.channel_id is None or terminal.hardware_model_id is None:
            return None
        hardware = _hardware(session, terminal.channel_id, terminal.hardware_model_id)
        channel = session.get(Channel, terminal.channel_id)
        row = session.exec(select(OtaPackage).where(
            OtaPackage.hardware_model_id == hardware.id,
            OtaPackage.channel_id == channel.id,
            OtaPackage.status == "published",
        )).first()
        if row is None:
            return None
        url = f"/api/v1/esop/terminal/ota/packages/{row.id}/download"
        return OtaManifest(
            packageId=row.id, channelCode=channel.code, hardwareCode=hardware.code,
            abi=hardware.abi, version=row.version, versionName=row.version,
            versionCode=row.version_code, package=row.package_name, size=row.file_size,
            checksumSha256=row.checksum_sha256, sha256=row.checksum_sha256,
            downloadUrl=url, apkUrl=url,
            publishedAt=row.published_at,
        )


@router.get("/terminal/ota/packages/{id}/download", response_model=None)
def download_ota_package(session: SessionDep, device: DeviceDep, id: uuid.UUID) -> FileResponse | StreamingResponse:
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = session.get(Terminal, device.terminal_id)
        if terminal is None or not terminal.is_active:
            raise HTTPException(status_code=401, detail="Invalid device credential")
        row = session.get(OtaPackage, id)
        if row is None or row.status != "published" or row.channel_id != terminal.channel_id or row.hardware_model_id != terminal.hardware_model_id:
            raise HTTPException(status_code=404, detail="OTA package not found")
        return download_authorized_file(session=session, tenant_id=row.file_owner_tenant_id, file_id=row.file_id)
