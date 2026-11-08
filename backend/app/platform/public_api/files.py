"""Stable file-asset lookup contracts for business modules."""

import base64
import uuid
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FileAssetSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    original_name: str
    content_type: str | None = None
    size: int
    sha256: str


class FileDirectUploadRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+$")
    size: int = Field(gt=0)
    md5: str = Field(min_length=24, max_length=24)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("md5")
    @classmethod
    def valid_md5(cls, value: str) -> str:
        try:
            digest = base64.b64decode(value, validate=True)
        except ValueError as exc:
            raise ValueError("MD5 必须为 Base64 编码") from exc
        if len(digest) != 16:
            raise ValueError("MD5 摘要长度无效")
        return value


class FileDirectUpload(BaseModel):
    file_id: uuid.UUID
    ticket: str
    url: str
    method: str = "POST"
    fields: dict[str, str]
    expires_at: datetime


class FileDirectRead(BaseModel):
    url: str
    expires_at: datetime


class FileAssetDirectory(Protocol):
    def get_accessible_file(
        self, *, tenant_id: uuid.UUID, file_id: uuid.UUID
    ) -> FileAssetSummary | None: ...

    def read_file_bytes(
        self, *, tenant_id: uuid.UUID, file_id: uuid.UUID, max_bytes: int = 50 * 1024 * 1024
    ) -> bytes: ...

    def discard_upload(self, *, tenant_id: uuid.UUID, file_id: uuid.UUID, uploader_id: uuid.UUID) -> None: ...

    def begin_direct_upload(
        self, *, tenant_id: uuid.UUID, uploader_id: uuid.UUID, request: FileDirectUploadRequest,
    ) -> FileDirectUpload: ...

    def complete_direct_upload(
        self, *, tenant_id: uuid.UUID, uploader_id: uuid.UUID, ticket: str,
    ) -> FileAssetSummary: ...

    def abort_direct_upload(
        self, *, tenant_id: uuid.UUID, uploader_id: uuid.UUID, ticket: str,
    ) -> None: ...

    def direct_read_url(self, *, tenant_id: uuid.UUID, file_id: uuid.UUID) -> FileDirectRead: ...

    def direct_uploaded_read_url(
        self, *, tenant_id: uuid.UUID, file_id: uuid.UUID, uploader_id: uuid.UUID,
    ) -> FileDirectRead: ...
