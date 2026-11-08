"""Private browser-to-OSS controls with no replacement DB or real bucket writes."""

import base64
import hashlib
import hmac
import json
import uuid
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import mysql

from app.core import quotas
from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.platform.infra import direct_files, file_directory
from app.platform.infra.file_models import FileAsset
from app.platform.public_api.files import FileDirectUploadRequest


def _setup(monkeypatch, *, native_head=False):
    tenant, uploader = uuid.uuid4(), uuid.uuid4()
    channel = SimpleNamespace(code="oss", bucket="private-bucket", provider="oss", endpoint_url="https://oss-cn-beijing.aliyuncs.com", object_prefix="app", access_key_id="public-key-id", secret_access_key="never-to-browser")
    client = Mock()
    monkeypatch.setattr(direct_files, "get_default_storage_channel", lambda *_: channel)
    monkeypatch.setattr(direct_files, "get_upload_max_size_mb", lambda *_: 10)
    monkeypatch.setattr(direct_files, "get_allowed_extensions", lambda *_: {"png"})
    monkeypatch.setattr(direct_files, "get_presigned_url_expire_seconds", lambda *_: 3600)
    monkeypatch.setattr(direct_files, "ensure_file_quota", Mock())
    monkeypatch.setattr(direct_files, "lock_file_quota", Mock())
    monkeypatch.setattr(direct_files, "_get_s3_client", lambda *_: client)
    request = FileDirectUploadRequest(name="image.png", content_type="image/png", size=7,
                                     md5=base64.b64encode(hashlib.md5(b"example").digest()).decode(), sha256=hashlib.sha256(b"example").hexdigest())
    session = Mock()
    session.exec.return_value.first.return_value = None
    upload = direct_files.begin_direct_upload(session, tenant, uploader, request)
    claims = jwt.decode(upload.ticket, settings.SECRET_KEY, algorithms=["HS256"], audience="platform-private-file-upload")
    client.head_object.return_value = {
        "ContentLength": 7, "ContentType": "image/png", "ETag": '"opaque-etag"',
        "Metadata": {"upload-id": str(upload.file_id), "sha256": request.sha256},
        "ResponseMetadata": {"HTTPHeaders": {"content-md5": request.md5}},
    }
    if not native_head:
        monkeypatch.setattr(direct_files, "_head_direct_object", lambda *_: client.head_object.return_value)
    return tenant, uploader, channel, client, request, session, upload, claims


def test_native_policy_has_exact_size_private_staging_scope_and_no_secret(monkeypatch):
    _, _, channel, _, _, _, upload, claims = _setup(monkeypatch)
    policy = json.loads(base64.b64decode(upload.fields["policy"]))
    assert ["content-length-range", 7, 7] in policy["conditions"]
    assert {"key": claims["staging"]} in policy["conditions"]
    assert {"x-oss-object-acl": "private"} in policy["conditions"]
    assert {"x-oss-forbid-overwrite": "true"} in policy["conditions"]
    assert {"x-oss-content-type": "image/png"} in policy["conditions"]
    assert claims["staging"].startswith("app/direct-pending/tenants/")
    assert claims["final"] != claims["staging"]
    assert channel.secret_access_key not in upload.model_dump_json()
    signature = base64.b64encode(hmac.new(channel.secret_access_key.encode(), upload.fields["policy"].encode(), hashlib.sha1).digest()).decode()
    assert signature == upload.fields["Signature"]
    assert upload.url == "https://private-bucket.oss-cn-beijing.aliyuncs.com/"
    assert upload.expires_at < get_datetime_utc() + timedelta(seconds=301)


@pytest.mark.parametrize("changed", ["tenant", "uploader", "signature", "expired", "access-token"])
def test_untrusted_or_expired_tickets_never_access_objects(monkeypatch, changed):
    tenant, uploader, _, client, _, session, upload, claims = _setup(monkeypatch)
    ticket = upload.ticket
    if changed == "tenant":
        tenant = uuid.uuid4()
    elif changed == "uploader":
        uploader = uuid.uuid4()
    elif changed == "signature":
        ticket += "tampered"
    elif changed == "expired":
        claims["exp"] = get_datetime_utc() - timedelta(seconds=1)
        ticket = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")
    else:
        ticket = jwt.encode({"sub": str(uploader), "tenant_id": str(tenant), "exp": get_datetime_utc() + timedelta(minutes=1)}, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(HTTPException) as error:
        direct_files.complete_direct_upload(session, tenant, uploader, ticket)
    assert error.value.status_code == 403
    client.head_object.assert_not_called()
    client.copy_object.assert_not_called()


def test_completion_verifies_head_then_copies_immutable_object_without_get(monkeypatch):
    tenant, uploader, channel, client, request, session, upload, claims = _setup(monkeypatch)
    asset = direct_files.complete_direct_upload(session, tenant, uploader, upload.ticket)
    assert asset.id == upload.file_id and asset.sha256 == request.sha256 and not asset.is_public
    assert asset.storage_path == claims["final"]
    client.copy_object.assert_called_once_with(Bucket=channel.bucket, Key=claims["final"],
        CopySource={"Bucket": channel.bucket, "Key": claims["staging"]}, CopySourceIfMatch='"opaque-etag"', MetadataDirective="COPY", ACL="private")
    client.get_object.assert_not_called()
    client.delete_object.assert_called_once_with(Bucket=channel.bucket, Key=claims["staging"])
    session.commit.assert_called_once()
    direct_files.ensure_file_quota.assert_called_with(session=session, tenant_id=tenant, incoming_size=7, current_read=True)


@pytest.mark.parametrize("field,value", [("ContentLength", 8), ("ContentType", "text/html"), ("ETag", None), ("Metadata", {}), ("ResponseMetadata", {})])
def test_metadata_mismatch_is_not_registered(monkeypatch, field, value):
    tenant, uploader, _, client, _, session, upload, _ = _setup(monkeypatch)
    client.head_object.return_value[field] = value
    with pytest.raises(HTTPException) as error:
        direct_files.complete_direct_upload(session, tenant, uploader, upload.ticket)
    assert error.value.status_code == 422
    client.copy_object.assert_not_called()
    session.add.assert_not_called()


def test_completion_retry_returns_registered_asset_without_mutating_object(monkeypatch):
    tenant, uploader, _, client, _, session, upload, _ = _setup(monkeypatch)
    existing = FileAsset(tenant_id=tenant, id=upload.file_id, uploader_id=uploader, original_name="image.png", stored_name="image.png", size=7, sha256="0"*64, storage_path="final", storage_provider="oss")
    session.exec.return_value.first.return_value = existing
    assert direct_files.complete_direct_upload(session, tenant, uploader, upload.ticket) is existing
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(existing)
    client.head_object.assert_not_called()
    client.copy_object.assert_not_called()


def test_abort_only_deletes_staging_even_after_finalize(monkeypatch):
    tenant, uploader, channel, client, _, session, upload, claims = _setup(monkeypatch)
    direct_files.abort_direct_upload(session, tenant, uploader, upload.ticket)
    client.delete_object.assert_called_once_with(Bucket=channel.bucket, Key=claims["staging"])
    session.delete.assert_not_called()


def test_copy_failure_is_chinese_retryable_and_does_not_register(monkeypatch):
    tenant, uploader, _, client, _, session, upload, _ = _setup(monkeypatch)
    client.copy_object.side_effect = ClientError({"Error": {"Code": "PreconditionFailed"}}, "CopyObject")
    with pytest.raises(HTTPException) as error:
        direct_files.complete_direct_upload(session, tenant, uploader, upload.ticket)
    assert error.value.status_code == 503 and "暂时失败" in error.value.detail
    session.add.assert_not_called()


def test_tenant_limit_extension_and_filename_are_checked_before_ticket(monkeypatch):
    tenant, uploader, _, _, request, session, _, _ = _setup(monkeypatch)
    for update, status in [({"size": 11*1024*1024}, 413), ({"name": "../../image.png"}, 422), ({"name": "test.exe"}, 422)]:
        with pytest.raises(HTTPException) as error:
            direct_files.begin_direct_upload(session, tenant, uploader, request.model_copy(update=update))
        assert error.value.status_code == status
    with pytest.raises(ValidationError):
        FileDirectUploadRequest(**{**request.model_dump(), "md5": "wrong"})


def test_direct_read_is_signed_and_never_fetches_content(monkeypatch):
    tenant, _, channel, client, _, session, _, _ = _setup(monkeypatch)
    asset = FileAsset(tenant_id=tenant, original_name="image.png", stored_name="image.png", size=7, sha256="0"*64, storage_path="final/image name.png", storage_provider="oss", content_type="image/png")
    result = direct_files.direct_read_url(session, tenant, asset)
    url = urlsplit(result.url)
    params = {key: value[0] for key, value in parse_qs(url.query).items()}
    assert url.hostname == "private-bucket.oss-cn-beijing.aliyuncs.com"
    assert url.path == "/final/image%20name.png"
    assert not any(key.startswith("response-") for key in params)
    assert params["OSSAccessKeyId"] == channel.access_key_id
    resource = "/private-bucket/final/image name.png"
    canonical = f"GET\n\n\n{params['Expires']}\n{resource}"
    signature = base64.b64encode(hmac.new(channel.secret_access_key.encode(), canonical.encode(), hashlib.sha1).digest()).decode()
    assert params["Signature"] == signature
    assert int(params["Expires"]) == int(result.expires_at.timestamp())
    assert 298 <= int(params["Expires"]) - get_datetime_utc().timestamp() <= 300
    assert channel.secret_access_key not in result.url
    client.generate_presigned_url.assert_not_called()
    client.get_object.assert_not_called()


def test_mysql_usage_is_current_read_for_serialized_uploads():
    session = Mock()
    session.get_bind.return_value.dialect.name = "mysql"
    session.exec.return_value.one.return_value = (2, 100)
    assert quotas.get_file_usage(session=session, tenant_id=uuid.uuid4(), current_read=True) == (2, 100)
    sql = str(session.exec.call_args.args[0].compile(dialect=mysql.dialect()))
    assert sql.endswith("FOR UPDATE")


def test_native_head_uses_oss_signature_and_verified_md5_header(monkeypatch):
    _, _, channel, client, request, _, _, _ = _setup(monkeypatch, native_head=True)
    response = httpx.Response(200, headers={"Content-Length": "7", "Content-Type": "image/png", "Content-Md5": request.md5,
                                            "ETag": '"opaque"', "x-oss-meta-sha256": request.sha256, "x-oss-meta-upload-id": "id"})
    head = Mock(return_value=response)
    monkeypatch.setattr(direct_files.httpx, "head", head)
    result = direct_files._head_direct_object(channel, "private/file name.png")
    assert result["ResponseMetadata"]["HTTPHeaders"]["content-md5"] == request.md5
    assert result["ContentLength"] == 7 and result["Metadata"]["sha256"] == request.sha256
    assert head.call_args.args[0] == "https://private-bucket.oss-cn-beijing.aliyuncs.com/private/file%20name.png"
    headers = head.call_args.kwargs["headers"]
    canonical = f"HEAD\n\n\n{headers['Date']}\n/private-bucket/private/file name.png"
    signature = base64.b64encode(hmac.new(channel.secret_access_key.encode(), canonical.encode(), hashlib.sha1).digest()).decode()
    assert headers["Authorization"] == f"OSS {channel.access_key_id}:{signature}"
    assert head.call_args.kwargs["follow_redirects"] is False
    client.get_object.assert_not_called()
    client.head_object.assert_not_called()


@pytest.mark.parametrize("status,expected", [(404, 422), (403, 503), (500, 503), (301, 503)])
def test_native_head_does_not_follow_redirects_or_leak_oss_errors(monkeypatch, status, expected):
    _, _, channel, _, _, _, _, _ = _setup(monkeypatch, native_head=True)
    monkeypatch.setattr(direct_files.httpx, "head", Mock(return_value=httpx.Response(status)))
    with pytest.raises(HTTPException) as error:
        direct_files._head_direct_object(channel, "test.png")
    assert error.value.status_code == expected
    assert "OSS " not in error.value.detail


def test_native_head_timeout_is_retryable(monkeypatch):
    _, _, channel, _, _, _, _, _ = _setup(monkeypatch, native_head=True)
    monkeypatch.setattr(direct_files.httpx, "head", Mock(side_effect=httpx.ReadTimeout("private upstream details")))
    with pytest.raises(HTTPException) as error:
        direct_files._head_direct_object(channel, "test.png")
    assert error.value.status_code == 503 and "private" not in error.value.detail


def test_failed_quota_releases_the_tenant_lock_before_audit(monkeypatch):
    tenant, uploader, _, client, _, session, upload, _ = _setup(monkeypatch)
    direct_files.ensure_file_quota.side_effect = HTTPException(status_code=409, detail="存储空间已达上限")
    with pytest.raises(HTTPException) as error:
        direct_files.complete_direct_upload(session, tenant, uploader, upload.ticket)
    assert error.value.status_code == 409
    session.rollback.assert_called_once()
    client.copy_object.assert_not_called()


def test_failed_metadata_releases_the_tenant_lock_before_audit(monkeypatch):
    tenant, uploader, _, client, _, session, upload, _ = _setup(monkeypatch)
    client.head_object.return_value["ContentLength"] = 100
    with pytest.raises(HTTPException) as error:
        direct_files.complete_direct_upload(session, tenant, uploader, upload.ticket)
    assert error.value.status_code == 422
    session.rollback.assert_called_once()


def test_failed_copy_releases_the_tenant_lock_before_audit(monkeypatch):
    tenant, uploader, _, client, _, session, upload, _ = _setup(monkeypatch)
    client.copy_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "CopyObject")
    with pytest.raises(HTTPException) as error:
        direct_files.complete_direct_upload(session, tenant, uploader, upload.ticket)
    assert error.value.status_code == 503
    session.rollback.assert_called_once()


@pytest.mark.parametrize("found", [True, False])
def test_unsaved_upload_access_is_scoped_to_tenant_and_uploader(monkeypatch, found):
    tenant, uploader, file_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scope = Mock(side_effect=lambda *_: nullcontext())
    monkeypatch.setattr(file_directory, "PlatformTenantUnitOfWork", scope)
    session = Mock()
    asset = SimpleNamespace(id=file_id, tenant_id=tenant, uploader_id=uploader)
    session.exec.return_value.first.return_value = asset if found else None
    signer = Mock(return_value=SimpleNamespace(url="https://private.example/short-signed-url"))
    monkeypatch.setattr(file_directory.direct_files, "direct_read_url", signer)
    directory = file_directory.SqlFileAssetDirectory(session)
    if found:
        result = directory.direct_uploaded_read_url(tenant_id=tenant, file_id=file_id, uploader_id=uploader)
        assert result.url == "https://private.example/short-signed-url"
        signer.assert_called_once_with(session, tenant, asset)
    else:
        with pytest.raises(HTTPException) as error:
            directory.direct_uploaded_read_url(tenant_id=tenant, file_id=file_id, uploader_id=uploader)
        # Missing, another uploader and another tenant all use this filtered-out result.
        assert error.value.status_code == 404 and error.value.detail == "文件不存在"
        signer.assert_not_called()
    scope.assert_called_once_with(session, tenant)
    query = session.exec.call_args.args[0].compile(dialect=mysql.dialect())
    assert query.params["id_1"] == file_id
    assert query.params["tenant_id_1"] == tenant
    assert query.params["uploader_id_1"] == uploader
