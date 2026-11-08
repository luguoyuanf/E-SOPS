"""Platform implementation of the public file-asset directory."""

import uuid

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import Session, select

from app.core.clock import get_datetime_utc
from app.core.quotas import ensure_file_quota
from app.platform.core.identity_models import User
from app.platform.infra import direct_files
from app.platform.infra.file_models import FileAsset
from app.platform.infra.storage import (
    delete_stored_file,
    get_file_download_response,
    read_stored_file_bytes,
    save_upload_file,
)
from app.platform.public_api.files import (
    FileAssetSummary,
    FileDirectRead,
    FileDirectUpload,
    FileDirectUploadRequest,
)
from app.platform.tenant_uow import PlatformTenantUnitOfWork


class SqlFileAssetDirectory:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_accessible_file(
        self, *, tenant_id: uuid.UUID, file_id: uuid.UUID
    ) -> FileAssetSummary | None:
        with PlatformTenantUnitOfWork(self._session, tenant_id):
            asset = self._session.exec(
                select(FileAsset).where(
                    FileAsset.id == file_id,
                    FileAsset.tenant_id == tenant_id,
                )
            ).first()
            if asset is None:
                return None
            return FileAssetSummary(
                id=asset.id,
                original_name=asset.original_name,
                content_type=asset.content_type,
                size=asset.size,
                sha256=asset.sha256,
            )

    def read_file_bytes(
        self,
        *,
        tenant_id: uuid.UUID,
        file_id: uuid.UUID,
        max_bytes: int = 50 * 1024 * 1024,
    ) -> bytes:
        with PlatformTenantUnitOfWork(self._session, tenant_id):
            asset = self._session.exec(
                select(FileAsset).where(
                    FileAsset.id == file_id, FileAsset.tenant_id == tenant_id
                )
            ).first()
            if asset is None:
                raise HTTPException(status_code=404, detail="文件不存在")
            if asset.size > max_bytes:
                raise HTTPException(status_code=413, detail="文件超出转换大小限制")
            return read_stored_file_bytes(
                storage_provider=asset.storage_provider,
                storage_path=asset.storage_path,
                session=self._session,
                tenant_id=tenant_id,
                max_bytes=max_bytes,
            )

    def discard_upload(
        self, *, tenant_id: uuid.UUID, file_id: uuid.UUID, uploader_id: uuid.UUID
    ) -> None:
        """Compensate an unpublished upload batch; never accept IDs from an HTTP caller."""
        with PlatformTenantUnitOfWork(self._session, tenant_id):
            asset = self._session.exec(
                select(FileAsset).where(
                    FileAsset.id == file_id,
                    FileAsset.tenant_id == tenant_id,
                    FileAsset.uploader_id == uploader_id,
                )
            ).first()
            if asset is None:
                return
            delete_stored_file(
                asset.storage_provider, asset.storage_path, self._session, tenant_id
            )
            self._session.delete(asset)
            self._session.commit()

    def begin_direct_upload(
        self, *, tenant_id: uuid.UUID, uploader_id: uuid.UUID, request: FileDirectUploadRequest,
    ) -> FileDirectUpload:
        with PlatformTenantUnitOfWork(self._session, tenant_id):
            return direct_files.begin_direct_upload(self._session, tenant_id, uploader_id, request)

    def complete_direct_upload(
        self, *, tenant_id: uuid.UUID, uploader_id: uuid.UUID, ticket: str,
    ) -> FileAssetSummary:
        with PlatformTenantUnitOfWork(self._session, tenant_id):
            asset = direct_files.complete_direct_upload(self._session, tenant_id, uploader_id, ticket)
            return FileAssetSummary.model_validate(asset, from_attributes=True)

    def abort_direct_upload(
        self, *, tenant_id: uuid.UUID, uploader_id: uuid.UUID, ticket: str,
    ) -> None:
        with PlatformTenantUnitOfWork(self._session, tenant_id):
            direct_files.abort_direct_upload(self._session, tenant_id, uploader_id, ticket)

    def direct_read_url(self, *, tenant_id: uuid.UUID, file_id: uuid.UUID) -> FileDirectRead:
        with PlatformTenantUnitOfWork(self._session, tenant_id):
            asset = self._session.exec(select(FileAsset).where(
                FileAsset.id == file_id, FileAsset.tenant_id == tenant_id,
            )).first()
            if asset is None:
                raise HTTPException(status_code=404, detail="文件不存在")
            return direct_files.direct_read_url(self._session, tenant_id, asset)


    def direct_uploaded_read_url(
        self, *, tenant_id: uuid.UUID, file_id: uuid.UUID, uploader_id: uuid.UUID,
    ) -> FileDirectRead:
        """Allow an uploader to preview their own upload before saving a business reference."""
        with PlatformTenantUnitOfWork(self._session, tenant_id):
            asset = self._session.exec(select(FileAsset).where(
                FileAsset.id == file_id, FileAsset.tenant_id == tenant_id,
                FileAsset.uploader_id == uploader_id,
            )).first()
            if asset is None:
                raise HTTPException(status_code=404, detail="文件不存在")
            return direct_files.direct_read_url(self._session, tenant_id, asset)


    def preview_response(
        self, *, tenant_id: uuid.UUID, file_id: uuid.UUID
    ) -> FileResponse | StreamingResponse:
        """Serve a file after the caller has authorized its business reference."""
        with PlatformTenantUnitOfWork(self._session, tenant_id):
            asset = self._session.exec(
                select(FileAsset).where(
                    FileAsset.id == file_id, FileAsset.tenant_id == tenant_id
                )
            ).first()
            if asset is None:
                raise HTTPException(status_code=404, detail="File not found")
            response = get_file_download_response(
                storage_provider=asset.storage_provider,
                storage_path=asset.storage_path,
                filename=asset.original_name,
                content_type=asset.content_type,
                session=self._session,
                tenant_id=tenant_id,
            )
            response.headers["Content-Disposition"] = "inline"
            return response


def store_tenant_file(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    uploader_id: uuid.UUID,
    file: UploadFile,
    is_public: bool = False,
    allowed_extensions: set[str] | None = None,
    max_size_mb: int | None = None,
) -> FileAsset:
    stored = save_upload_file(
        file, session=session, tenant_id=tenant_id,
        allowed_extensions=allowed_extensions, max_size_mb=max_size_mb,
    )
    try:
        direct_files.lock_file_quota(session, tenant_id)
        ensure_file_quota(
            session=session, tenant_id=tenant_id, incoming_size=stored.size, current_read=True,
        )
    except Exception:
        session.rollback()
        delete_stored_file(
            stored.storage_provider, stored.storage_path, session, tenant_id
        )
        raise
    asset = FileAsset(
        tenant_id=tenant_id,
        original_name=stored.original_name,
        stored_name=stored.stored_name,
        content_type=stored.content_type,
        extension=stored.extension,
        size=stored.size,
        sha256=stored.sha256,
        storage_provider=stored.storage_provider,
        storage_path=stored.storage_path,
        public_url=None,
        uploader_id=uploader_id,
        is_public=is_public,
    )
    # UUID exists before flush, so the URL does not need a second transaction.
    asset.public_url = f"/api/v1/files/{asset.id}/download"
    try:
        session.add(asset)
        session.commit()
        session.refresh(asset)
    except Exception:
        # Do not remove content after an ambiguous commit; a retry may find it.
        session.rollback()
        raise
    return asset


def save_user_avatar(
    *, session: Session, tenant_id: uuid.UUID, actor: User, user: User, file: UploadFile,
) -> User:
    """Shared OSS/quota handling for own and administrator-managed avatars."""
    stored_file = save_upload_file(
        file,
        session=session,
        tenant_id=tenant_id,
    )
    try:
        direct_files.lock_file_quota(session, tenant_id)
        ensure_file_quota(
            session=session,
            tenant_id=tenant_id,
            incoming_size=stored_file.size,
            current_read=True,
        )
    except Exception:
        session.rollback()
        delete_stored_file(
            stored_file.storage_provider,
            stored_file.storage_path,
            session,
            tenant_id,
        )
        raise
    if stored_file.extension not in {"gif", "jpeg", "jpg", "png", "webp"}:
        session.rollback()
        delete_stored_file(
            stored_file.storage_provider,
            stored_file.storage_path,
            session,
            tenant_id,
        )
        raise HTTPException(status_code=400, detail="头像必须为图片")

    file_asset = FileAsset(
        tenant_id=tenant_id,
        original_name=stored_file.original_name,
        stored_name=stored_file.stored_name,
        content_type=stored_file.content_type,
        extension=stored_file.extension,
        size=stored_file.size,
        sha256=stored_file.sha256,
        storage_provider=stored_file.storage_provider,
        storage_path=stored_file.storage_path,
        uploader_id=actor.id,
        is_public=True,
    )
    session.add(file_asset)
    session.commit()
    session.refresh(file_asset)
    file_asset.public_url = f"/api/v1/files/{file_asset.id}/download"
    user.avatar_url = f"/api/v1/files/avatars/{file_asset.id}"
    user.updated_at = get_datetime_utc()
    session.add(file_asset)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
