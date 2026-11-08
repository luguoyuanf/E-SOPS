"""Default capacity applies on creation, never as a retroactive quota update."""

import uuid
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.platform import storage_provisioning as storage
from app.platform.core import esop_commercial
from app.platform.core.esop_commercial_models import EsopStorageDefault


@pytest.mark.parametrize('value', [0, 1024, 4096])
def test_new_accounts_inherit_admin_configuration(monkeypatch, value):
    session = Mock()
    session.get.return_value = None
    monkeypatch.setattr(storage, 'read_storage_default', lambda **_: EsopStorageDefault(capacity_mib=value))
    create = Mock()
    monkeypatch.setattr(storage, '_ensure_account', create)
    tenant = uuid.uuid4()
    storage.ensure_esop_storage_account(session=session, tenant_id=tenant)
    create.assert_called_once_with(session=session, tenant_id=tenant, initial_bytes=value * 1024 * 1024)


def test_default_change_and_paid_activation_preserve_existing_account(monkeypatch):
    session = Mock()
    account = SimpleNamespace(base_bytes=123)
    session.get.return_value = account
    reader = Mock()
    monkeypatch.setattr(storage, 'read_storage_default', reader)
    assert storage.ensure_paid_activation_storage(session=session, tenant_id=uuid.uuid4()) is account
    assert account.base_bytes == 123
    reader.assert_not_called()


def test_certification_preserves_assigned_capacity(monkeypatch):
    account = SimpleNamespace(base_bytes=0, certified_at=None)
    monkeypatch.setattr(esop_commercial, 'ensure_esop_storage_account', lambda **_: account)
    esop_commercial.certify_esop_tenant(session=Mock(), tenant_id=uuid.uuid4())
    assert account.base_bytes == 0 and account.certified_at is not None


@pytest.mark.parametrize('value', [-1, 0.5, 'invalid', 8589934592])
def test_default_rejects_invalid_capacities(value):
    with pytest.raises(ValidationError):
        EsopStorageDefault(capacity_mib=value)


@pytest.mark.parametrize('configured, expected', [(None, 1024), ('2048', 2048), ('0', 0)])
def test_read_platform_default_without_creating_records(monkeypatch, configured, expected):
    monkeypatch.setattr(storage, 'PlatformTenantUnitOfWork', lambda *_args, **_kwargs: nullcontext())
    session = Mock()
    session.exec.return_value.first.return_value = None if configured is None else SimpleNamespace(value=configured)
    assert storage.read_storage_default(session=session).capacity_mib == expected
    session.add.assert_not_called()


def test_invalid_stored_setting_fails_closed(monkeypatch):
    monkeypatch.setattr(storage, 'PlatformTenantUnitOfWork', lambda *_args, **_kwargs: nullcontext())
    session = Mock()
    session.exec.return_value.first.return_value = SimpleNamespace(value='bad')
    with pytest.raises(HTTPException) as error:
        storage.read_storage_default(session=session)
    assert error.value.status_code == 503
