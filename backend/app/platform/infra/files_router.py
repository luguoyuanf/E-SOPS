import uuid
from contextlib import nullcontext
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlmodel import col, func, or_, select

from app.api.deps import (
    CurrentTenant,
    CurrentUser,
    OptionalCurrentUser,
    OptionalTenantId,
    PlatformConfigurationTenant,
    PlatformReadTenant,
    SessionDep,
    get_current_active_superuser,
    normalize_pagination,
    require_permission,
)
from app.core.clock import get_datetime_utc
from app.core.quotas import get_file_usage, get_storage_limit
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.modules.references import assert_no_references
from app.platform.core.configuration_models import SystemSetting
from app.platform.core.identity_models import UserPublic
from app.platform.infra.file_directory import store_tenant_file
from app.platform.infra.file_models import (
    FileAsset,
    FileAssetPublic,
    FileAssetsPublic,
    FileDownloadUrl,
    FileStorageChannel,
    FileStorageChannelCreate,
    FileStorageChannelPublic,
    FileStorageChannelsPublic,
    FileStorageChannelUpdate,
    FileStorageUsagePublic,
    StorageConfigPublic,
    UploadConfigPublic,
    UploadConfigUpdate,
)
from app.platform.infra.storage import (
    _ensure_s3_bucket,
    _get_s3_client,
    delete_stored_file,
    get_default_storage_channel,
    get_file_download_response,
    get_presigned_download_url,
    get_presigned_url_expire_seconds,
    get_upload_allowed_extensions,
    get_upload_default_public,
    get_upload_max_size_mb,
)
from app.platform.tenant_uow import PlatformGlobalUnitOfWork, PlatformTenantUnitOfWork

router = APIRouter(prefix="/files", tags=["files"])


def mask_storage_channel(channel: FileStorageChannel) -> FileStorageChannelPublic:
    data = FileStorageChannelPublic.model_validate(channel)
    if data.secret_access_key:
        data.secret_access_key = "******"
    return data


def ensure_supported_provider(provider: str) -> None:
    if provider not in {"local", "s3", "oss"}:
        raise HTTPException(status_code=400, detail="Unsupported storage provider")


def ensure_channel_code_unique(
    *,
    session: SessionDep,
    tenant_id: uuid.UUID,
    code: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    statement = select(FileStorageChannel).where(
        FileStorageChannel.tenant_id == tenant_id,
        FileStorageChannel.code == code,
    )
    if exclude_id:
        statement = statement.where(FileStorageChannel.id != exclude_id)
    if session.exec(statement).first():
        raise HTTPException(
            status_code=409, detail="Storage channel code already exists"
        )


def clear_default_storage_channels(
    *,
    session: SessionDep,
    tenant_id: uuid.UUID,
    exclude_id: uuid.UUID | None = None,
) -> None:
    statement = select(FileStorageChannel).where(
        FileStorageChannel.tenant_id == tenant_id,
        FileStorageChannel.is_default,
    )
    if exclude_id:
        statement = statement.where(FileStorageChannel.id != exclude_id)
    for channel in session.exec(statement).all():
        channel.is_default = False
        channel.updated_at = get_datetime_utc()
        session.add(channel)


def ensure_upload_setting(
    *,
    session: SessionDep,
    tenant_id: uuid.UUID,
    key: str,
    name: str,
    value: str,
    value_type: str,
) -> SystemSetting:
    setting = session.exec(
        select(SystemSetting).where(
            SystemSetting.tenant_id == tenant_id,
            SystemSetting.key == key,
        )
    ).first()
    if not setting:
        setting = SystemSetting(
            tenant_id=tenant_id,
            key=key,
            name=name,
            value=value,
            value_type=value_type,
            group="upload",
            is_public=False,
            is_system=True,
        )
    else:
        setting.value = value
        setting.value_type = value_type
        setting.updated_at = get_datetime_utc()
    session.add(setting)
    return setting


@router.get("/storage-usage", response_model=FileStorageUsagePublic)
def read_current_storage_usage(
    session: SessionDep, tenant_context: CurrentTenant,
) -> FileStorageUsagePublic:
    tenant_id = tenant_context.tenant_id
    _, used = get_file_usage(session=session, tenant_id=tenant_id)
    limit = get_storage_limit(session=session, tenant_id=tenant_id)
    return FileStorageUsagePublic(
        used_bytes=used,
        limit_bytes=limit,
        remaining_bytes=max(0, limit - used) if limit is not None else None,
        warning=limit is not None and used * 10 >= limit * 9,
    )


@router.get(
    "",
    dependencies=[Depends(require_permission("system:file:list"))],
    response_model=FileAssetsPublic,
)
def read_files(
    session: SessionDep,
    read_tenant: PlatformReadTenant,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    storage_provider: str | None = None,
    is_public: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Any:
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    filters = [FileAsset.tenant_id == read_tenant] if read_tenant else []
    if keyword:
        pattern = f"%{keyword}%"
        filters.append(
            or_(
                col(FileAsset.original_name).ilike(pattern),
                col(FileAsset.content_type).ilike(pattern),
                col(FileAsset.extension).ilike(pattern),
            )
        )
    if storage_provider:
        filters.append(FileAsset.storage_provider == storage_provider)
    if is_public is not None:
        filters.append(FileAsset.is_public == is_public)

    if created_from is not None:
        filters.append(FileAsset.created_at >= created_from)
    if created_to is not None:
        filters.append(FileAsset.created_at <= created_to)
    count_statement = select(func.count()).select_from(FileAsset)
    if filters:
        count_statement = count_statement.where(*filters)
    count = session.exec(count_statement).one()

    statement = select(FileAsset)
    if filters:
        statement = statement.where(*filters)
    statement = (
        statement.order_by(col(FileAsset.created_at).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    files = session.exec(statement).all()
    return FileAssetsPublic(
        items=[FileAssetPublic.model_validate(file_asset) for file_asset in files],
        total=count,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/upload",
    dependencies=[Depends(require_permission("system:file:upload"))],
    response_model=FileAssetPublic,
)
def upload_file(
    session: SessionDep,
    current_user: CurrentUser,
    tenant_context: CurrentTenant,
    file: UploadFile = File(...),
    is_public: bool | None = None,
) -> Any:
    return store_tenant_file(
        session=session,
        tenant_id=tenant_context.tenant_id,
        uploader_id=current_user.id,
        file=file,
        is_public=(
            is_public
            if is_public is not None
            else get_upload_default_public(session, tenant_context.tenant_id)
        ),
    )


@router.get(
    "/storage-config",
    dependencies=[Depends(require_permission("system:file:list"))],
    response_model=StorageConfigPublic,
)
def read_storage_config(
    session: SessionDep,
    tenant_context: CurrentTenant,
) -> StorageConfigPublic:
    channel = get_default_storage_channel(session, tenant_context.tenant_id)
    return StorageConfigPublic(
        provider=channel.provider,
        channel_id=channel.id,
        channel_name=channel.name,
        max_size_mb=get_upload_max_size_mb(session, tenant_context.tenant_id),
        allowed_extensions=get_upload_allowed_extensions(
            session,
            tenant_context.tenant_id,
        ),
        default_public=get_upload_default_public(
            session,
            tenant_context.tenant_id,
        ),
        s3_bucket=channel.bucket if channel.provider in {"s3", "oss"} else None,
        s3_endpoint_url=(
            channel.endpoint_url if channel.provider in {"s3", "oss"} else None
        ),
        presigned_url_expire_seconds=(
            get_presigned_url_expire_seconds(
                session,
                tenant_context.tenant_id,
            )
            if channel.provider in {"s3", "oss"}
            else None
        ),
    )


@router.get(
    "/storage-channels",
    dependencies=[
        Depends(require_permission("system:file:channel:list")),
        Depends(get_current_active_superuser),
    ],
    response_model=FileStorageChannelsPublic,
)
def read_storage_channels(
    session: SessionDep,
    read_tenant: PlatformReadTenant,  # noqa: ARG001 - legacy filter is ignored
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    provider: str | None = None,
    is_active: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Any:
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        page, page_size = normalize_pagination(page=page, page_size=page_size)
        filters = [FileStorageChannel.tenant_id == DEFAULT_TENANT_ID]
        if keyword:
            pattern = f"%{keyword}%"
            filters.append(
                or_(
                    col(FileStorageChannel.name).ilike(pattern),
                    col(FileStorageChannel.code).ilike(pattern),
                    col(FileStorageChannel.bucket).ilike(pattern),
                )
            )
        if provider:
            filters.append(FileStorageChannel.provider == provider)
        if is_active is not None:
            filters.append(FileStorageChannel.is_active == is_active)

        if created_from is not None:
            filters.append(FileStorageChannel.created_at >= created_from)
        if created_to is not None:
            filters.append(FileStorageChannel.created_at <= created_to)
        count_statement = select(func.count()).select_from(FileStorageChannel)
        if filters:
            count_statement = count_statement.where(*filters)
        count = session.exec(count_statement).one()

        statement = select(FileStorageChannel)
        if filters:
            statement = statement.where(*filters)
        statement = (
            statement.order_by(
                col(FileStorageChannel.is_default).desc(),
                col(FileStorageChannel.created_at),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        channels = session.exec(statement).all()
        return FileStorageChannelsPublic(
            items=[mask_storage_channel(channel) for channel in channels],
            total=count,
            page=page,
            page_size=page_size,
        )


@router.post(
    "/storage-channels",
    dependencies=[Depends(require_permission("system:file:channel:create"))],
    response_model=FileStorageChannelPublic,
)
def create_storage_channel(
    *,
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,
    channel_in: FileStorageChannelCreate,
) -> Any:
    ensure_supported_provider(channel_in.provider)
    ensure_channel_code_unique(
        session=session,
        tenant_id=tenant_context.tenant_id,
        code=channel_in.code,
    )
    channel = FileStorageChannel.model_validate(
        channel_in,
        update={"tenant_id": tenant_context.tenant_id},
    )
    if channel.is_default:
        clear_default_storage_channels(
            session=session,
            tenant_id=tenant_context.tenant_id,
        )
    session.add(channel)
    session.commit()
    session.refresh(channel)
    return mask_storage_channel(channel)


@router.get(
    "/storage-channels/{channel_id}",
    dependencies=[Depends(require_permission("system:file:channel:update"))],
    response_model=FileStorageChannelPublic,
)
def read_storage_channel(
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,
    response: Response,
    channel_id: uuid.UUID,
) -> FileStorageChannelPublic:
    """Only the authorized platform editor receives credentials for one channel."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    channel = session.exec(
        select(FileStorageChannel).where(
            FileStorageChannel.id == channel_id,
            FileStorageChannel.tenant_id == tenant_context.tenant_id,
        )
    ).first()
    if channel is None:
        raise HTTPException(status_code=404, detail="Storage channel not found")
    return FileStorageChannelPublic.model_validate(channel)


@router.patch(
    "/storage-channels/{channel_id}",
    dependencies=[Depends(require_permission("system:file:channel:update"))],
    response_model=FileStorageChannelPublic,
)
def update_storage_channel(
    *,
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,
    channel_id: uuid.UUID,
    channel_in: FileStorageChannelUpdate,
) -> Any:
    channel = session.exec(
        select(FileStorageChannel).where(
            FileStorageChannel.id == channel_id,
            FileStorageChannel.tenant_id == tenant_context.tenant_id,
        )
    ).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Storage channel not found")

    update_data = channel_in.model_dump(exclude_unset=True)
    if "provider" in update_data and update_data["provider"] is not None:
        ensure_supported_provider(update_data["provider"])
    if "code" in update_data and update_data["code"] != channel.code:
        ensure_channel_code_unique(
            session=session,
            tenant_id=tenant_context.tenant_id,
            code=update_data["code"],
            exclude_id=channel.id,
        )
    if update_data.get("is_default"):
        clear_default_storage_channels(
            session=session,
            tenant_id=tenant_context.tenant_id,
            exclude_id=channel.id,
        )

    channel.sqlmodel_update(update_data)
    channel.updated_at = get_datetime_utc()
    session.add(channel)
    session.commit()
    session.refresh(channel)
    return mask_storage_channel(channel)


@router.post(
    "/storage-channels/{channel_id}/test",
    dependencies=[Depends(require_permission("system:file:channel:update"))],
)
def test_storage_channel(
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,
    channel_id: uuid.UUID,
) -> dict[str, str]:
    channel = session.exec(
        select(FileStorageChannel).where(
            FileStorageChannel.id == channel_id,
            FileStorageChannel.tenant_id == tenant_context.tenant_id,
        )
    ).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Storage channel not found")
    if channel.provider == "local":
        return {"message": "Storage channel is available"}
    if channel.provider not in {"s3", "oss"}:
        raise HTTPException(status_code=400, detail="Unsupported storage provider")
    client = _get_s3_client(channel)
    _ensure_s3_bucket(client, channel)
    return {"message": "Storage channel is available"}


@router.delete(
    "/storage-channels/{channel_id}",
    dependencies=[Depends(require_permission("system:file:channel:delete"))],
    status_code=204,
)
def delete_storage_channel(
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,
    channel_id: uuid.UUID,
) -> None:
    channel = session.exec(
        select(FileStorageChannel).where(
            FileStorageChannel.id == channel_id,
            FileStorageChannel.tenant_id == tenant_context.tenant_id,
        )
    ).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Storage channel not found")
    if channel.is_default:
        raise HTTPException(
            status_code=400, detail="Cannot delete default storage channel"
        )
    session.delete(channel)
    session.commit()
    return None


@router.get(
    "/upload-config",
    dependencies=[
        Depends(require_permission("system:file:config:list")),
        Depends(get_current_active_superuser),
    ],
    response_model=UploadConfigPublic,
)
def read_upload_config(
    session: SessionDep,
    tenant_context: CurrentTenant,
) -> UploadConfigPublic:
    return UploadConfigPublic(
        max_size_mb=get_upload_max_size_mb(session, tenant_context.tenant_id),
        allowed_extensions=get_upload_allowed_extensions(
            session,
            tenant_context.tenant_id,
        ),
        default_public=get_upload_default_public(
            session,
            tenant_context.tenant_id,
        ),
        presigned_url_expire_seconds=get_presigned_url_expire_seconds(
            session,
            tenant_context.tenant_id,
        ),
    )


@router.patch(
    "/upload-config",
    dependencies=[Depends(require_permission("system:file:config:update"))],
    response_model=UploadConfigPublic,
)
def update_upload_config(
    *,
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,
    config_in: UploadConfigUpdate,
) -> UploadConfigPublic:
    update_data = config_in.model_dump(exclude_unset=True)
    setting_specs = {
        "max_size_mb": ("upload.max_size_mb", "上传大小限制 MB", "number"),
        "allowed_extensions": ("upload.allowed_extensions", "允许上传扩展名", "string"),
        "default_public": ("upload.default_public", "默认公开访问", "boolean"),
        "presigned_url_expire_seconds": (
            "upload.presigned_url_expire_seconds",
            "下载链接有效期秒数",
            "number",
        ),
    }
    for field, value in update_data.items():
        key, name, value_type = setting_specs[field]
        ensure_upload_setting(
            session=session,
            tenant_id=tenant_context.tenant_id,
            key=key,
            name=name,
            value=str(value).lower() if isinstance(value, bool) else str(value),
            value_type=value_type,
        )
    session.commit()
    return read_upload_config(session, tenant_context)


@router.get("/{file_id}", response_model=FileAssetPublic)
def read_file(
    session: SessionDep,
    current_user: CurrentUser,
    read_tenant: PlatformReadTenant,
    file_id: uuid.UUID,
) -> Any:
    file_asset = session.exec(
        select(FileAsset).where(
            FileAsset.id == file_id,
            (FileAsset.tenant_id == read_tenant) if read_tenant else True,
        )
    ).first()
    if not file_asset:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        assert_no_references(
            session=session,
            reference_type="file",
            reference_id=file_id,
            tenant_id=file_asset.tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not current_user.is_superuser and file_asset.uploader_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return file_asset


@router.get("/{file_id}/download-url", response_model=FileDownloadUrl)
def read_file_download_url(
    session: SessionDep,
    current_user: CurrentUser,
    read_tenant: PlatformReadTenant,
    file_id: uuid.UUID,
) -> FileDownloadUrl:
    file_asset = session.exec(
        select(FileAsset).where(
            FileAsset.id == file_id,
            (FileAsset.tenant_id == read_tenant) if read_tenant else True,
        )
    ).first()
    if not file_asset:
        raise HTTPException(status_code=404, detail="File not found")
    if (
        not file_asset.is_public
        and not current_user.is_superuser
        and file_asset.uploader_id != current_user.id
    ):
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    fallback_url = f"/api/v1/files/{file_asset.id}/download"
    url = get_presigned_download_url(
        storage_provider=file_asset.storage_provider,
        storage_path=file_asset.storage_path,
        fallback_url=fallback_url,
        content_type=file_asset.content_type,
        session=session,
        tenant_id=file_asset.tenant_id,
    )
    return FileDownloadUrl(
        url=url,
        expires_in=(
            get_presigned_url_expire_seconds(session, file_asset.tenant_id)
            if url != fallback_url
            else None
        ),
    )


@router.get("/avatars/{file_id}")
def download_user_avatar(session: SessionDep, file_id: uuid.UUID) -> Any:
    """Public badge images must be attached avatars, never arbitrary tenant files."""
    from app.platform.core.identity_models import User

    path = f"/api/v1/files/avatars/{file_id}"
    if session.exec(select(User.id).where(User.avatar_url == path)).first() is None:
        raise HTTPException(status_code=404, detail="头像不存在")
    # Public avatar links carry no tenant token; resolve only an explicitly public image.
    with PlatformGlobalUnitOfWork(session):
        asset = session.exec(select(FileAsset).where(
            FileAsset.id == file_id, FileAsset.is_public,
            FileAsset.extension.in_(["gif", "jpeg", "jpg", "png", "webp"]),
        )).first()
        if asset is None:
            raise HTTPException(status_code=404, detail="头像不存在")
        return get_file_download_response(
            storage_provider=asset.storage_provider, storage_path=asset.storage_path,
            filename=asset.original_name, content_type=asset.content_type,
            session=session, tenant_id=asset.tenant_id,
        )


@router.get("/{file_id}/download")
def download_file(
    session: SessionDep,
    current_user: OptionalCurrentUser,
    request_tenant_id: OptionalTenantId,
    file_id: uuid.UUID,
) -> Any:
    scope = (
        PlatformGlobalUnitOfWork(session)
        if current_user and current_user.is_superuser
        else nullcontext()
    )
    with scope:
        file_asset = session.get(FileAsset, file_id)
        if not file_asset:
            raise HTTPException(status_code=404, detail="File not found")
        if (
            current_user
            and not current_user.is_superuser
            and request_tenant_id != file_asset.tenant_id
        ):
            raise HTTPException(
                status_code=403, detail="The user doesn't have enough privileges"
            )
        if not file_asset.is_public and (
            not current_user
            or (
                not current_user.is_superuser
                and file_asset.uploader_id != current_user.id
            )
        ):
            raise HTTPException(
                status_code=403, detail="The user doesn't have enough privileges"
            )

        return get_file_download_response(
            storage_provider=file_asset.storage_provider,
            storage_path=file_asset.storage_path,
            filename=file_asset.original_name,
            content_type=file_asset.content_type,
            session=session,
            tenant_id=file_asset.tenant_id,
        )


@router.delete(
    "/{file_id}",
    dependencies=[Depends(require_permission("system:file:delete"))],
    status_code=204,
)
def delete_file(
    session: SessionDep,
    tenant_context: CurrentTenant,
    file_id: uuid.UUID,
) -> None:
    file_asset = session.exec(
        select(FileAsset).where(
            FileAsset.id == file_id,
            FileAsset.tenant_id == tenant_context.tenant_id,
        )
    ).first()
    if not file_asset:
        raise HTTPException(status_code=404, detail="File not found")
    delete_stored_file(
        file_asset.storage_provider,
        file_asset.storage_path,
        session,
        file_asset.tenant_id,
    )
    session.delete(file_asset)
    session.commit()
    return None


@router.post("/avatar", response_model=UserPublic)
def upload_avatar(
    session: SessionDep,
    current_user: CurrentUser,
    tenant_context: CurrentTenant,
    file: UploadFile = File(...),
) -> Any:
    from app.platform.infra.file_directory import save_user_avatar

    return save_user_avatar(
        session=session, tenant_id=tenant_context.tenant_id,
        actor=current_user, user=current_user, file=file,
    )
