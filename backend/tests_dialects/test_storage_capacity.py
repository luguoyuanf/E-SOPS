"""Tenant-wide storage boundaries and rejection before object writes."""

import io
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, UploadFile

from app.core import quotas
from app.platform.infra import file_directory, files_router, storage_impl


@pytest.mark.parametrize(('used', 'limit', 'warning', 'remaining'), [
    (89, 100, False, 11), (90, 100, True, 10),
    (100, 100, True, 0), (101, 100, True, 0),
    (5, None, False, None), (0, 0, True, 0),
])
def test_usage_warning_boundary_and_current_tenant(monkeypatch, used, limit, warning, remaining):
    tenant = uuid.uuid4()
    usage = Mock(return_value=(3, used))
    capacity = Mock(return_value=limit)
    monkeypatch.setattr(files_router, 'get_file_usage', usage)
    monkeypatch.setattr(files_router, 'get_storage_limit', capacity)
    session = Mock()
    result = files_router.read_current_storage_usage(session, SimpleNamespace(tenant_id=tenant))
    assert result.model_dump() == {'used_bytes': used, 'limit_bytes': limit, 'remaining_bytes': remaining, 'warning': warning}
    usage.assert_called_once_with(session=session, tenant_id=tenant)
    capacity.assert_called_once_with(session=session, tenant_id=tenant)


def test_all_file_usage_is_tenant_scoped():
    tenant = uuid.uuid4()
    session = Mock()
    session.exec.return_value.one.return_value = (4, 900)
    assert quotas.get_file_usage(session=session, tenant_id=tenant) == (4, 900)
    query = session.exec.call_args.args[0]
    assert query.compile().params == {'coalesce_2': 0, 'tenant_id_1': tenant}
    assert 'sum(fileasset.size)' in str(query)


@pytest.mark.parametrize('incoming, rejected', [(10, False), (11, True)])
def test_upload_may_fill_but_not_exceed_capacity(monkeypatch, incoming, rejected):
    monkeypatch.setattr(quotas, 'get_tenant_plan', lambda **_: SimpleNamespace(max_file_assets=None))
    monkeypatch.setattr(quotas, 'get_file_usage', lambda **_: (2, 90))
    monkeypatch.setattr(quotas, 'get_storage_limit', lambda **_: 100)
    if rejected:
        with pytest.raises(HTTPException) as error:
            quotas.ensure_file_quota(session=Mock(), tenant_id=uuid.uuid4(), incoming_size=incoming)
        assert error.value.status_code == 409
    else:
        quotas.ensure_file_quota(session=Mock(), tenant_id=uuid.uuid4(), incoming_size=incoming)


def test_over_capacity_does_not_write_oss_and_removes_temporary(monkeypatch, tmp_path):
    temporary = tmp_path / 'upload.pdf'
    temporary.write_bytes(b'content')
    client = Mock()
    monkeypatch.setattr(storage_impl, 'get_default_storage_channel', lambda *_: SimpleNamespace(provider='oss', object_prefix='test'))
    monkeypatch.setattr(storage_impl, 'validate_upload', lambda *_: 'pdf')
    monkeypatch.setattr(storage_impl, '_build_storage_path', lambda *_: 'test/file.pdf')
    monkeypatch.setattr(storage_impl, '_save_to_temporary_file', lambda *_: (temporary, 7, '0' * 64))
    monkeypatch.setattr(storage_impl, '_get_s3_client', client)
    monkeypatch.setattr(quotas, 'ensure_file_quota', Mock(side_effect=HTTPException(409, 'Tenant storage quota exceeded')))
    with pytest.raises(HTTPException) as error:
        storage_impl.save_upload_file(UploadFile(file=io.BytesIO(b'content'), filename='file.pdf'), session=Mock(), tenant_id=uuid.uuid4())
    assert error.value.status_code == 409
    client.assert_not_called()
    assert not temporary.exists()


def test_avatar_registration_also_serializes_quota(monkeypatch):
    tenant = uuid.uuid4()
    session = Mock()
    stored = SimpleNamespace(original_name='avatar.png', stored_name='avatar.png', content_type='image/png', extension='png', size=7, sha256='0' * 64, storage_provider='oss', storage_path='test/avatar.png')
    monkeypatch.setattr(file_directory, 'save_upload_file', lambda *_, **__: stored)
    lock = Mock()
    quota = Mock()
    monkeypatch.setattr(file_directory.direct_files, 'lock_file_quota', lock)
    monkeypatch.setattr(file_directory, 'ensure_file_quota', quota)
    files_router.upload_avatar(session, SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(tenant_id=tenant), UploadFile(file=io.BytesIO(b'content'), filename='avatar.png'))
    lock.assert_called_once_with(session, tenant)
    quota.assert_called_once_with(session=session, tenant_id=tenant, incoming_size=7, current_read=True)
