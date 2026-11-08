import hashlib
import logging
import shutil
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter
from typing import Any, Literal, cast
from urllib.parse import quote, urlsplit, urlunsplit

import boto3
from boto3.exceptions import RetriesExceededError, S3UploadFailedError
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import Session, select

from app.core.config import settings
from app.core.tenancy import DEFAULT_TENANT_ID
from app.platform.core.configuration_models import SystemSetting
from app.platform.infra.file_models import FileStorageChannel
from app.platform.tenant_uow import PlatformTenantUnitOfWork

StorageProvider = Literal["local", "s3", "oss"]
logger = logging.getLogger(f"uvicorn.error.{__name__}")


@dataclass
class StoredFile:
    original_name: str
    stored_name: str
    content_type: str | None
    extension: str | None
    size: int
    sha256: str
    storage_path: str
    storage_provider: StorageProvider


def get_upload_setting(
    session: Session | None,
    key: str,
    default: str,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,  # noqa: ARG001 - compatibility
) -> str:
    if session is None:
        return default
    # tenant_id remains a compatibility argument; configuration is platform-owned.
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        setting = session.exec(
            select(SystemSetting).where(
                SystemSetting.tenant_id == DEFAULT_TENANT_ID,
                SystemSetting.key == key,
            )
        ).first()
        return setting.value if setting else default


def get_upload_max_size_mb(
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> int:
    value = get_upload_setting(
        session,
        "upload.max_size_mb",
        str(settings.UPLOAD_MAX_SIZE_MB),
        tenant_id,
    )
    try:
        return max(1, int(value))
    except ValueError:
        return settings.UPLOAD_MAX_SIZE_MB


def get_upload_allowed_extensions(
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> str:
    return get_upload_setting(
        session,
        "upload.allowed_extensions",
        settings.UPLOAD_ALLOWED_EXTENSIONS,
        tenant_id,
    )


def get_upload_default_public(
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> bool:
    value = get_upload_setting(
        session,
        "upload.default_public",
        "false",
        tenant_id,
    )
    return value.lower() in {"1", "true", "yes"}


def get_presigned_url_expire_seconds(
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> int:
    value = get_upload_setting(
        session,
        "upload.presigned_url_expire_seconds",
        str(settings.S3_PRESIGNED_URL_EXPIRE_SECONDS),
        tenant_id,
    )
    try:
        return max(60, int(value))
    except ValueError:
        return settings.S3_PRESIGNED_URL_EXPIRE_SECONDS


def get_default_storage_channel(
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,  # noqa: ARG001 - compatibility
) -> FileStorageChannel:
    if session is not None:
        with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
            channel = session.exec(
                select(FileStorageChannel)
                .where(
                    FileStorageChannel.tenant_id == DEFAULT_TENANT_ID,
                    FileStorageChannel.is_active,
                    FileStorageChannel.is_default,
                )
                .order_by(FileStorageChannel.created_at)
            ).first()
            if channel:
                if settings.STORAGE_PROVIDER == "oss" and channel.provider != "oss":
                    raise HTTPException(
                        status_code=503, detail="Platform uploads require OSS storage"
                    )
                # Return a snapshot: the caller's tenant scope is restored on exit.
                return FileStorageChannel.model_validate(channel.model_dump())

    return FileStorageChannel(
        tenant_id=DEFAULT_TENANT_ID,
        name="本地存储" if settings.STORAGE_PROVIDER == "local" else "默认对象存储",
        code="local"
        if settings.STORAGE_PROVIDER == "local"
        else f"default-{settings.STORAGE_PROVIDER}",
        provider=settings.STORAGE_PROVIDER,
        endpoint_url=settings.S3_ENDPOINT_URL,
        region=settings.S3_REGION,
        bucket=settings.S3_BUCKET,
        access_key_id=settings.S3_ACCESS_KEY_ID,
        secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        object_prefix=settings.S3_OBJECT_PREFIX,
        addressing_style=settings.S3_ADDRESSING_STYLE,
        auto_create_bucket=settings.S3_AUTO_CREATE_BUCKET,
        is_default=True,
        is_active=True,
    )


def get_upload_root() -> Path:
    upload_root = Path(settings.UPLOAD_DIR)
    if not upload_root.is_absolute():
        upload_root = Path(__file__).resolve().parents[3] / upload_root
    upload_root.mkdir(parents=True, exist_ok=True)
    return upload_root


def get_allowed_extensions(
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> set[str]:
    return {
        extension.strip().lower().lstrip(".")
        for extension in get_upload_allowed_extensions(session, tenant_id).split(",")
        if extension.strip()
    }


def get_extension(filename: str) -> str | None:
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix or None


def validate_upload(
    file: UploadFile,
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
    allowed_extensions: set[str] | None = None,
) -> str | None:
    extension = get_extension(file.filename or "")
    allowed = allowed_extensions if allowed_extensions is not None else get_allowed_extensions(session, tenant_id)
    if allowed and (not extension or extension not in allowed):
        raise HTTPException(status_code=400, detail="File extension is not allowed")
    return extension


def _build_storage_path(
    stored_name: str,
    channel: FileStorageChannel,
    tenant_id: uuid.UUID,
) -> str:
    now = datetime.now(UTC)
    relative_path = (
        Path("tenants")
        / str(tenant_id)
        / str(now.year)
        / f"{now.month:02d}"
        / stored_name
    )
    if channel.provider in {"s3", "oss"}:
        prefix = (channel.object_prefix or "").strip("/")
        if prefix:
            relative_path = Path(prefix) / relative_path
    return str(relative_path).replace("\\", "/")


def _save_to_temporary_file(
    file: UploadFile,
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
    max_size_mb: int | None = None,
) -> tuple[Path, int, str]:
    max_size = (max_size_mb if max_size_mb is not None else get_upload_max_size_mb(session, tenant_id)) * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    temporary_file = NamedTemporaryFile(delete=False)
    temporary_path = Path(temporary_file.name)
    try:
        with temporary_file:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_size:
                    raise HTTPException(status_code=400, detail=f"文件大小不能超过 {max_size // (1024 * 1024)} MB")
                digest.update(chunk)
                temporary_file.write(chunk)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path, size, digest.hexdigest()


def _get_s3_client(channel: FileStorageChannel | None = None) -> Any:
    channel = channel or get_default_storage_channel()
    if not channel.bucket:
        raise HTTPException(status_code=503, detail="S3_BUCKET is not configured")

    endpoint_url = channel.endpoint_url
    config = None
    if channel.provider == "oss":
        if (
            not endpoint_url
            or not channel.access_key_id
            or not channel.secret_access_key
        ):
            raise HTTPException(
                status_code=503,
                detail="OSS endpoint and access credentials are required",
            )
        try:
            endpoint = urlsplit(endpoint_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid OSS endpoint") from exc
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
            or endpoint.username
        ):
            raise HTTPException(
                status_code=400,
                detail="OSS endpoint must be an HTTPS service endpoint without a bucket or path",
            )
        # Alibaba's S3-compatible service uses s3.oss-<region> endpoints.
        if endpoint.hostname.startswith("oss-") and endpoint.hostname.endswith(
            ".aliyuncs.com"
        ):
            endpoint_url = urlunsplit(
                endpoint._replace(netloc="s3." + endpoint.netloc, path="")
            )
        config = Config(
            signature_version="s3",
            s3={"addressing_style": "virtual"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
    elif channel.addressing_style != "auto":
        config = Config(s3={"addressing_style": channel.addressing_style})
    return boto3.client(
        "s3",
        aws_access_key_id=channel.access_key_id,
        aws_secret_access_key=channel.secret_access_key,
        endpoint_url=endpoint_url,
        region_name=channel.region or settings.S3_REGION,
        config=config,
    )


def _ensure_s3_bucket(client: Any, channel: FileStorageChannel) -> None:
    if not channel.bucket:
        raise HTTPException(status_code=503, detail="S3_BUCKET is not configured")
    try:
        client.head_bucket(Bucket=channel.bucket)
        return
    except ClientError:
        if channel.provider == "oss" or not channel.auto_create_bucket:
            raise HTTPException(status_code=503, detail="S3 bucket is not available")
    try:
        create_kwargs: dict[str, object] = {"Bucket": channel.bucket}
        region = channel.region or settings.S3_REGION
        if region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        client.create_bucket(**create_kwargs)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to create S3 bucket"
        ) from exc


def save_upload_file(
    file: UploadFile,
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
    *,
    allowed_extensions: set[str] | None = None,
    max_size_mb: int | None = None,
) -> StoredFile:
    channel = get_default_storage_channel(session, tenant_id)
    extension = validate_upload(file, session, tenant_id, allowed_extensions)
    stored_name = f"{uuid.uuid4().hex}{f'.{extension}' if extension else ''}"
    storage_path = _build_storage_path(stored_name, channel, tenant_id)
    temporary_path, size, sha256 = _save_to_temporary_file(
        file,
        session,
        tenant_id,
        max_size_mb,
    )

    try:
        if session is not None:
            from app.core.quotas import ensure_file_quota

            ensure_file_quota(session=session, tenant_id=tenant_id, incoming_size=size)
        if channel.provider == "local":
            destination = get_local_file_path(storage_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temporary_path), destination)
        else:
            client = _get_s3_client(channel)
            # Existing OSS buckets are validated by PUT itself. A HEAD per original
            # and rendered page adds a network roundtrip and needs extra permission.
            if channel.provider != "oss":
                _ensure_s3_bucket(client, channel)
            extra_args: dict[str, str] = {}
            if file.content_type:
                extra_args["ContentType"] = file.content_type
            started = perf_counter()
            with temporary_path.open("rb") as source:
                client.upload_fileobj(
                    source,
                    channel.bucket,
                    storage_path,
                    ExtraArgs=extra_args or None,
                )
            logger.info("file_storage stage=object_write provider=%s bytes=%d duration_ms=%.1f",
                        channel.provider, size, (perf_counter() - started) * 1000)
    except HTTPException:
        raise
    except (BotoCoreError, ClientError, S3UploadFailedError, RetriesExceededError) as exc:
        raise HTTPException(status_code=503, detail="文件存储暂时失败，请稍后重试") from exc
    finally:
        temporary_path.unlink(missing_ok=True)

    return StoredFile(
        original_name=file.filename or stored_name,
        stored_name=stored_name,
        content_type=file.content_type,
        extension=extension,
        size=size,
        sha256=sha256,
        storage_path=storage_path,
        storage_provider=cast(StorageProvider, channel.provider),
    )


def get_local_file_path(storage_path: str) -> Path:
    upload_root = get_upload_root().resolve()
    file_path = (upload_root / storage_path).resolve()
    if upload_root not in file_path.parents and file_path != upload_root:
        raise HTTPException(status_code=400, detail="Invalid file path")
    return file_path


def delete_stored_file(
    storage_provider: str,
    storage_path: str,
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> None:
    if storage_provider == "local":
        get_local_file_path(storage_path).unlink(missing_ok=True)
        return
    if storage_provider not in {"s3", "oss"}:
        raise HTTPException(status_code=400, detail="Unsupported storage provider")
    channel = get_default_storage_channel(session, tenant_id)
    try:
        _get_s3_client(channel).delete_object(Bucket=channel.bucket, Key=storage_path)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to delete stored file"
        ) from exc


def delete_local_file(storage_path: str) -> None:
    """Compatibility helper for existing internal callers."""
    delete_stored_file("local", storage_path)


def _stream_s3_object(
    storage_path: str,
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> Iterator[bytes]:
    channel = get_default_storage_channel(session, tenant_id)
    try:
        response = _get_s3_client(channel).get_object(
            Bucket=channel.bucket, Key=storage_path
        )
        body = response["Body"]
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=404, detail="File content not found") from exc

    def chunks() -> Iterator[bytes]:
        try:
            while chunk := body.read(1024 * 1024):
                yield chunk
        finally:
            body.close()

    # Resolve storage credentials while the caller's authorized tenant scope is active.
    return chunks()


def get_file_download_response(
    *,
    storage_provider: str,
    storage_path: str,
    filename: str,
    content_type: str | None,
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> FileResponse | StreamingResponse:
    if storage_provider == "local":
        file_path = get_local_file_path(storage_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File content not found")
        return FileResponse(file_path, filename=filename, media_type=content_type)
    if storage_provider not in {"s3", "oss"}:
        raise HTTPException(status_code=400, detail="Unsupported storage provider")
    return StreamingResponse(
        _stream_s3_object(storage_path, session, tenant_id),
        media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}"},
    )


def get_presigned_download_url(
    *,
    storage_provider: str,
    storage_path: str,
    fallback_url: str,
    content_type: str | None = None,
    session: Session | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> str:
    # OSS default domains reject APK/IPA query-signed URLs; retain API authorization.
    if storage_provider == "local" or (
        storage_provider == "oss"
        and (
            Path(storage_path).suffix.lower() in {".apk", ".ipa"}
            or content_type
            in {"application/vnd.android.package-archive", "application/iphone"}
        )
    ):
        return fallback_url
    if storage_provider not in {"s3", "oss"}:
        raise HTTPException(status_code=400, detail="Unsupported storage provider")
    channel = get_default_storage_channel(session, tenant_id)
    try:
        return _get_s3_client(channel).generate_presigned_url(
            "get_object",
            Params={"Bucket": channel.bucket, "Key": storage_path},
            ExpiresIn=get_presigned_url_expire_seconds(session, tenant_id),
        )
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to create a download URL"
        ) from exc


def get_terminal_download_url(*, storage_path: str) -> str:
    """Return the fixed URL of a package in the dedicated R2 download bucket."""
    origin = settings.TERMINAL_DOWNLOAD_ORIGIN or ""
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
        or parsed.username or parsed.password or parsed.port
    ):
        raise HTTPException(status_code=503, detail="Terminal download domain is not configured")
    return f"{origin.rstrip('/')}/{quote(storage_path, safe='/')}"


def copy_file_to_uploads(source: Path, filename: str) -> StoredFile:
    # Test helper and future internal import utility.
    class LocalUpload:
        def __init__(self, path: Path, name: str) -> None:
            self.filename = name
            self.content_type = None
            self.file = path.open("rb")

    upload = LocalUpload(source, filename)
    try:
        return save_upload_file(cast(UploadFile, upload))
    finally:
        upload.file.close()


def read_stored_file_bytes(
    *, storage_provider: str, storage_path: str, session: Session,
    tenant_id: uuid.UUID, max_bytes: int,
) -> bytes:
    """Bounded internal reads for authorized conversion, without public URLs."""
    if storage_provider == "local":
        path = get_local_file_path(storage_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="文件内容不存在")
        with path.open("rb") as source:
            data = source.read(max_bytes + 1)
    elif storage_provider in {"s3", "oss"}:
        chunks = _stream_s3_object(storage_path, session, tenant_id)
        output = bytearray()
        try:
            for chunk in chunks:
                output.extend(chunk)
                if len(output) > max_bytes:
                    raise HTTPException(status_code=413, detail="文件超出转换大小限制")
        finally:
            chunks.close()
        data = bytes(output)
    else:
        raise HTTPException(status_code=400, detail="不支持的文件存储类型")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="文件超出转换大小限制")
    return data
