import uuid
from contextlib import nullcontext
from types import SimpleNamespace

from app.platform import storage_provisioning
from app.platform.core.esop_commercial import MIB
from app.platform.core.esop_commercial_models import (
    EsopStorageDefault,
    EsopTenantStorage,
)


def test_missing_setting_defaults_to_100_mib(monkeypatch):
    monkeypatch.setattr(
        storage_provisioning, "PlatformTenantUnitOfWork", lambda *a, **kw: nullcontext()
    )
    session = SimpleNamespace(exec=lambda *a: SimpleNamespace(first=lambda: None))
    assert (
        storage_provisioning.read_storage_default(session=session).capacity_mib == 100
    )


def test_new_account_receives_configured_free_capacity(monkeypatch):
    tenant_id = uuid.uuid4()
    calls = []
    monkeypatch.setattr(
        storage_provisioning,
        "read_storage_default",
        lambda **kw: EsopStorageDefault(capacity_mib=100),
    )
    monkeypatch.setattr(
        storage_provisioning, "_ensure_account", lambda **kw: calls.append(kw)
    )
    storage_provisioning.ensure_esop_storage_account(
        session=SimpleNamespace(get=lambda *a: None), tenant_id=tenant_id
    )
    assert calls[0]["initial_bytes"] == 100 * MIB
    assert EsopTenantStorage(tenant_id=tenant_id).base_bytes == 100 * MIB


def test_existing_account_keeps_original_entitlement(monkeypatch):
    tenant_id = uuid.uuid4()
    existing = EsopTenantStorage(tenant_id=tenant_id, base_bytes=1024 * MIB)

    def unexpected_read(**_kwargs):
        raise AssertionError("Existing entitlement must not be recalculated")

    monkeypatch.setattr(storage_provisioning, "read_storage_default", unexpected_read)
    result = storage_provisioning.ensure_esop_storage_account(
        session=SimpleNamespace(get=lambda *a: existing),
        tenant_id=tenant_id,
    )
    assert result is existing
    assert result.base_bytes == 1024 * MIB
