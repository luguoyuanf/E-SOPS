"""Upload overhead/error regressions with no replacement database or real objects."""

import io
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from boto3.exceptions import S3UploadFailedError
from fastapi import HTTPException, UploadFile

from app.platform.infra import file_directory, storage_impl


def _oss_upload(monkeypatch, tmp_path, error=None):
    channel = SimpleNamespace(provider="oss", object_prefix="test", bucket="test-bucket")
    client = Mock()
    client.upload_fileobj.side_effect = error
    monkeypatch.setattr(storage_impl, "get_default_storage_channel", lambda *_: channel)
    monkeypatch.setattr(storage_impl, "validate_upload", lambda *_: "mp4")
    monkeypatch.setattr(storage_impl, "_get_s3_client", lambda *_: client)
    temporary = tmp_path / "upload.mp4"
    temporary.write_bytes(b"video")
    monkeypatch.setattr(storage_impl, "_save_to_temporary_file", lambda *_: (temporary, 5, "0" * 64))
    return client, temporary


def test_oss_upload_does_not_require_bucket_head_permission(monkeypatch, tmp_path):
    client, temporary = _oss_upload(monkeypatch, tmp_path)
    file = UploadFile(file=io.BytesIO(b"video"), filename="test.mp4")
    stored = storage_impl.save_upload_file(file, tenant_id=uuid.uuid4())
    assert stored.size == 5 and stored.storage_provider == "oss"
    client.head_bucket.assert_not_called()
    client.upload_fileobj.assert_called_once()
    assert not temporary.exists()


def test_managed_transfer_failure_is_retryable_chinese_error(monkeypatch, tmp_path):
    _, temporary = _oss_upload(monkeypatch, tmp_path, S3UploadFailedError("upstream details"))
    file = UploadFile(file=io.BytesIO(b"video"), filename="test.mp4")
    with pytest.raises(HTTPException) as error:
        storage_impl.save_upload_file(file, tenant_id=uuid.uuid4())
    assert error.value.status_code == 503
    assert error.value.detail == "文件存储暂时失败，请稍后重试"
    assert "upstream" not in error.value.detail and not temporary.exists()


def test_asset_url_and_quota_are_persisted_in_one_transaction(monkeypatch):
    stored = storage_impl.StoredFile(
        original_name="test.mp4", stored_name="test.mp4", content_type="video/mp4",
        extension="mp4", size=5, sha256="0" * 64, storage_path="private/test.mp4", storage_provider="oss",
    )
    monkeypatch.setattr(file_directory, "save_upload_file", lambda *_args, **_kwargs: stored)
    quota = Mock()
    monkeypatch.setattr(file_directory, "ensure_file_quota", quota)
    session = Mock()
    tenant = uuid.uuid4()
    result = file_directory.store_tenant_file(
        session=session, tenant_id=tenant, uploader_id=uuid.uuid4(),
        file=UploadFile(file=io.BytesIO(b"video"), filename="test.mp4"),
    )
    quota.assert_called_once_with(session=session, tenant_id=tenant, incoming_size=5, current_read=True)
    assert result.public_url == f"/api/v1/files/{result.id}/download"
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(result)


def test_traditional_quota_failure_rolls_back_before_object_cleanup(monkeypatch):
    stored = storage_impl.StoredFile(original_name="test.png", stored_name="test.png", content_type="image/png",
        extension="png", size=5, sha256="0"*64, storage_path="private/test.png", storage_provider="oss")
    monkeypatch.setattr(file_directory, "save_upload_file", lambda *_args, **_kwargs: stored)
    monkeypatch.setattr(file_directory.direct_files, "lock_file_quota", lambda *_: None)
    def reject(**_kwargs):
        raise HTTPException(status_code=409, detail="空间不足")
    monkeypatch.setattr(file_directory, "ensure_file_quota", reject)
    session = Mock()
    cleaned = []
    def cleanup(*_args):
        session.rollback.assert_called_once()
        cleaned.append(True)
    monkeypatch.setattr(file_directory, "delete_stored_file", cleanup)
    with pytest.raises(HTTPException) as error:
        file_directory.store_tenant_file(session=session, tenant_id=uuid.uuid4(), uploader_id=uuid.uuid4(),
            file=UploadFile(file=io.BytesIO(b"image"), filename="test.png"))
    assert error.value.status_code == 409 and cleaned == [True]


def test_traditional_commit_failure_also_releases_quota_lock(monkeypatch):
    stored = storage_impl.StoredFile(original_name="test.png", stored_name="test.png", content_type="image/png",
        extension="png", size=5, sha256="0"*64, storage_path="private/test.png", storage_provider="oss")
    monkeypatch.setattr(file_directory, "save_upload_file", lambda *_args, **_kwargs: stored)
    monkeypatch.setattr(file_directory.direct_files, "lock_file_quota", lambda *_: None)
    monkeypatch.setattr(file_directory, "ensure_file_quota", lambda **_kwargs: None)
    session = Mock()
    session.commit.side_effect = RuntimeError("ambiguous commit")
    with pytest.raises(RuntimeError):
        file_directory.store_tenant_file(session=session, tenant_id=uuid.uuid4(), uploader_id=uuid.uuid4(),
            file=UploadFile(file=io.BytesIO(b"image"), filename="test.png"))
    session.rollback.assert_called_once()
