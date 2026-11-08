"""Private OSS form uploads: signed staging keys, verified metadata, immutable final keys."""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
import jwt
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.core.quotas import ensure_file_quota
from app.platform.core.tenancy_models import Tenant
from app.platform.infra.file_models import FileAsset
from app.platform.infra.storage_impl import (
    _build_storage_path,
    _get_s3_client,
    get_allowed_extensions,
    get_default_storage_channel,
    get_extension,
    get_presigned_url_expire_seconds,
    get_upload_max_size_mb,
)
from app.platform.public_api.files import (
    FileDirectRead,
    FileDirectUpload,
    FileDirectUploadRequest,
)

_AUDIENCE = "platform-private-file-upload"


def lock_file_quota(session: Session, tenant_id: uuid.UUID) -> None:
    """Serialize all Platform file registrations for a tenant, including direct uploads."""
    session.exec(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()).one()


def _channel(session, tenant_id):
    channel = get_default_storage_channel(session, tenant_id)
    if channel.provider != "oss" or not channel.bucket or not channel.access_key_id or not channel.secret_access_key:
        raise HTTPException(status_code=503, detail="当前存储渠道不支持 OSS 直传")
    endpoint = urlsplit(channel.endpoint_url or "")
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.path not in {"", "/"} or endpoint.query or endpoint.fragment or endpoint.username:
        raise HTTPException(status_code=503, detail="OSS 直传地址配置无效")
    return channel


def _channel_fingerprint(channel):
    # Tickets bind configuration identity, but never contain credentials.
    return hashlib.sha256(json.dumps([channel.code, channel.bucket, channel.endpoint_url, channel.object_prefix]).encode()).hexdigest()


def begin_direct_upload(session, tenant_id, uploader_id, request: FileDirectUploadRequest) -> FileDirectUpload:
    if "/" in request.name or "\\" in request.name or request.name in {".", ".."}:
        raise HTTPException(status_code=422, detail="上传文件名无效")
    extension = get_extension(request.name)
    allowed = get_allowed_extensions(session, tenant_id)
    if not extension or (allowed and extension not in allowed):
        raise HTTPException(status_code=422, detail="不支持的上传文件格式")
    max_bytes = get_upload_max_size_mb(session, tenant_id) * 1024 * 1024
    if request.size > max_bytes:
        raise HTTPException(status_code=413, detail=f"文件大小不能超过 {max_bytes // (1024 * 1024)} MB")
    ensure_file_quota(session=session, tenant_id=tenant_id, incoming_size=request.size)
    channel = _channel(session, tenant_id)
    file_id = uuid.uuid4()
    stored_name = f"{file_id.hex}.{extension}"
    prefix = (channel.object_prefix or "").strip("/")
    staging_key = "/".join(filter(None, [prefix, "direct-pending", "tenants", str(tenant_id), stored_name]))
    final_key = _build_storage_path(stored_name, channel, tenant_id)
    expiry = get_datetime_utc() + timedelta(seconds=min(300, get_presigned_url_expire_seconds(session, tenant_id)))
    fields = {
        "key": staging_key,
        "success_action_status": "201",
        "x-oss-content-type": request.content_type,
        "x-oss-object-acl": "private",
        "x-oss-forbid-overwrite": "true",
        "x-oss-meta-upload-id": str(file_id),
        "x-oss-meta-sha256": request.sha256,
    }
    policy = {
        "expiration": expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "conditions": [{"bucket": channel.bucket}, ["content-length-range", request.size, request.size], *[{key: value} for key, value in fields.items()]],
    }
    encoded = base64.b64encode(json.dumps(policy, separators=(",", ":")).encode()).decode()
    fields.update({"OSSAccessKeyId": channel.access_key_id, "policy": encoded,
                   "Signature": base64.b64encode(hmac.new(channel.secret_access_key.encode(), encoded.encode(), hashlib.sha1).digest()).decode()})
    endpoint = urlsplit(channel.endpoint_url)
    host = endpoint.hostname.removeprefix("s3.")
    url = urlunsplit(("https", f"{channel.bucket}.{host}", "/", "", ""))
    ticket = jwt.encode({
        "aud": _AUDIENCE, "exp": expiry, "sub": str(uploader_id), "tenant_id": str(tenant_id),
        "file_id": str(file_id), "channel": _channel_fingerprint(channel), "staging": staging_key, "final": final_key,
        "name": request.name, "size": request.size, "content_type": request.content_type,
        "md5": request.md5, "sha256": request.sha256,
    }, settings.SECRET_KEY, algorithm="HS256")
    return FileDirectUpload(file_id=file_id, ticket=ticket, url=url, method="POST", fields=fields, expires_at=expiry)


def _ticket(session, tenant_id, uploader_id, ticket):
    try:
        claims = jwt.decode(ticket, settings.SECRET_KEY, algorithms=["HS256"], audience=_AUDIENCE,
                            options={"require": ["exp", "aud", "sub", "tenant_id", "file_id", "channel", "staging", "final", "name", "size", "content_type", "md5", "sha256"]})
        if claims["tenant_id"] != str(tenant_id) or claims["sub"] != str(uploader_id):
            raise ValueError("scope")
        file_id = uuid.UUID(claims["file_id"])
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=403, detail="上传凭证无效或已过期，请重新上传") from exc
    channel = _channel(session, tenant_id)
    if claims["channel"] != _channel_fingerprint(channel):
        raise HTTPException(status_code=409, detail="存储配置已变更，请重新上传")
    return claims, channel, file_id


def _head_direct_object(channel, key):
    """Native OSS HEAD preserves Content-Md5, stripped by the S3 compatibility API."""
    date = format_datetime(get_datetime_utc(), usegmt=True)
    canonical = f"HEAD\n\n\n{date}\n/{channel.bucket}/{key}"
    signature = base64.b64encode(hmac.new(channel.secret_access_key.encode(), canonical.encode(), hashlib.sha1).digest()).decode()
    host = urlsplit(channel.endpoint_url).hostname.removeprefix("s3.")
    url = urlunsplit(("https", f"{channel.bucket}.{host}", "/" + quote(key, safe="/"), "", ""))
    try:
        response = httpx.head(url, headers={"Date": date, "Authorization": f"OSS {channel.access_key_id}:{signature}"},
                              timeout=httpx.Timeout(15, connect=5), follow_redirects=False)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="文件校验暂不可用，请稍后重试") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=422, detail="文件尚未上传完成，请重试确认")
    if response.status_code != 200:
        raise HTTPException(status_code=503, detail="文件校验暂不可用，请稍后重试")
    try:
        size = int(response.headers["content-length"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="上传文件校验失败，请重新上传") from exc
    return {
        "ContentLength": size, "ContentType": response.headers.get("content-type"), "ETag": response.headers.get("etag"),
        "Metadata": {name.removeprefix("x-oss-meta-"): value for name, value in response.headers.items() if name.startswith("x-oss-meta-")},
        "ResponseMetadata": {"HTTPHeaders": dict(response.headers)},
    }


def complete_direct_upload(session, tenant_id, uploader_id, ticket) -> FileAsset:
    try:
        claims, channel, file_id = _ticket(session, tenant_id, uploader_id, ticket)
        lock_file_quota(session, tenant_id)
        existing = session.exec(select(FileAsset).where(FileAsset.id == file_id, FileAsset.tenant_id == tenant_id).with_for_update()).first()
        if existing is not None:
            if existing.uploader_id != uploader_id:
                raise HTTPException(status_code=403, detail="无权确认该文件")
            # The audit writer uses a separate session with a tenant foreign key.
            session.commit()
            session.refresh(existing)
            return existing
        ensure_file_quota(session=session, tenant_id=tenant_id, incoming_size=claims["size"], current_read=True)
        client = _get_s3_client(channel)
        head = _head_direct_object(channel, claims["staging"])
        headers = head.get("ResponseMetadata", {}).get("HTTPHeaders", {})
        metadata = head.get("Metadata", {})
        valid = (
            head.get("ContentLength") == claims["size"]
            and head.get("ContentType") == claims["content_type"]
            and headers.get("content-md5", headers.get("Content-Md5")) == claims["md5"]
            and metadata.get("upload-id") == str(file_id)
            and metadata.get("sha256") == claims["sha256"]
            and bool(head.get("ETag"))
        )
        if not valid:
            raise HTTPException(status_code=422, detail="上传文件校验失败，请重新上传")
        try:
            # The browser can only write staging. A replay cannot modify this final object.
            client.copy_object(Bucket=channel.bucket, Key=claims["final"],
                               CopySource={"Bucket": channel.bucket, "Key": claims["staging"]},
                               CopySourceIfMatch=head["ETag"], MetadataDirective="COPY", ACL="private")
        except (BotoCoreError, ClientError) as exc:
            raise HTTPException(status_code=503, detail="文件确认暂时失败，请稍后重试") from exc
        asset = FileAsset(id=file_id, tenant_id=tenant_id, uploader_id=uploader_id,
                          original_name=claims["name"], stored_name=Path(claims["final"]).name,
                          extension=get_extension(claims["name"]), content_type=claims["content_type"],
                          size=claims["size"], sha256=claims["sha256"], storage_provider="oss", storage_path=claims["final"],
                          public_url=f"/api/v1/files/{file_id}/download", is_public=False)
        session.add(asset)
        session.commit()
        session.refresh(asset)
        # A cleanup failure must not turn a committed upload into an apparent failure.
        try:
            client.delete_object(Bucket=channel.bucket, Key=claims["staging"])
        except (BotoCoreError, ClientError):
            pass  # The direct-pending prefix's lifecycle removes abandoned staging objects.
        return asset
    except Exception:
        session.rollback()
        raise


def abort_direct_upload(session, tenant_id, uploader_id, ticket) -> None:
    claims, channel, _ = _ticket(session, tenant_id, uploader_id, ticket)
    try:
        _get_s3_client(channel).delete_object(Bucket=channel.bucket, Key=claims["staging"])
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=503, detail="临时上传清理失败，请稍后重试") from exc


def direct_read_url(session, tenant_id, asset: FileAsset) -> FileDirectRead:
    if asset.storage_provider != "oss":
        raise HTTPException(status_code=409, detail="该文件尚未存储到 OSS，不能直接访问")
    channel = _channel(session, tenant_id)
    ttl = min(300, get_presigned_url_expire_seconds(session, tenant_id))
    expiry = (get_datetime_utc() + timedelta(seconds=ttl)).replace(microsecond=0)
    expires = str(int(expiry.timestamp()))
    # OSS default domains reject Content-Type overrides; use the object's metadata.
    resource = f"/{channel.bucket}/{asset.storage_path}"
    canonical = f"GET\n\n\n{expires}\n{resource}"
    signature = base64.b64encode(hmac.new(channel.secret_access_key.encode(), canonical.encode(), hashlib.sha1).digest()).decode()
    parameters = {"OSSAccessKeyId": channel.access_key_id, "Expires": expires, "Signature": signature}
    host = urlsplit(channel.endpoint_url).hostname.removeprefix("s3.")
    query = "&".join(f"{quote(key, safe='')}={quote(value, safe='')}" for key, value in parameters.items())
    url = urlunsplit(("https", f"{channel.bucket}.{host}", "/" + quote(asset.storage_path, safe="/"), query, ""))
    return FileDirectRead(url=url, expires_at=expiry)
