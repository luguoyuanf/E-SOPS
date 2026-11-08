"""Device self-unbind and replacement-key activation on the fixed MySQL.

All synthetic rows remain inside an outer transaction, including route commits.
No shared database fixtures or existing device credentials are used.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.modules.esop.infrastructure.device_auth import (
    _digest,
    activate_device,
    issue_key,
    resolve_device,
)
from app.modules.esop.infrastructure.models import (
    ActivationKey,
    ActivationUnbindLog,
    DeviceCredential,
    Terminal,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.terminal_routes import terminal_profile, terminal_unbind


def test_self_unbind_then_new_key_reactivates_same_terminal(monkeypatch):
    assert settings.DATABASE_TYPE == "mysql"
    assert settings.MYSQL_DB == "esop_fva_test_20261024"
    tenant_id = uuid.uuid4()
    device_code = "reactivation-" + uuid.uuid4().hex
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            ) as session:
                first, first_plaintext = issue_key(
                    session, tenant_id, grant_type="free"
                )
                replacement, replacement_plaintext = issue_key(
                    session, tenant_id, grant_type="free"
                )
                for plaintext in (
                    first_plaintext,
                    replacement_plaintext,
                ):
                    assert len(plaintext) == 8
                    assert not set(plaintext) & set("O0I1")
                session.commit()
                identity, old_token = activate_device(
                    session,
                    key=first_plaintext,
                    device_code=device_code,
                    old_token=None,
                )
                terminal_unbind(session, identity)
                with pytest.raises(HTTPException) as revoked:
                    resolve_device(session, old_token)
                assert revoked.value.status_code == 401
                with EsopTenantUnitOfWork(session, tenant_id):
                    terminal = session.get(Terminal, identity.terminal_id)
                    assert terminal is not None and not terminal.is_active
                    assert terminal.station_id is None
                    logs_before = session.exec(
                        select(ActivationUnbindLog).where(
                            ActivationUnbindLog.terminal_id == identity.terminal_id
                        )
                    ).all()
                    assert len(logs_before) == 1
                    assert logs_before[0].key_id == first.id
                    assert logs_before[0].actor_id == identity.terminal_id
                credential = session.exec(
                    select(DeviceCredential).where(
                        DeviceCredential.device_code == device_code
                    )
                ).one()
                token_hash_before = credential.token_hash
                with pytest.raises(HTTPException) as invalid:
                    activate_device(
                        session, key="invalid!", device_code=device_code, old_token=None
                    )
                assert invalid.value.status_code == 400
                assert (
                    invalid.value.detail
                    == "Activation key must contain exactly 8 letters or digits"
                )
                missing_plaintext = uuid.uuid4().hex[:8].upper()
                while (
                    session.exec(
                        select(ActivationKey.id).where(
                            ActivationKey.key_hash
                            == _digest(f"key:{missing_plaintext}")
                        )
                    ).first()
                    is not None
                ):
                    missing_plaintext = uuid.uuid4().hex[:8].upper()
                with pytest.raises(HTTPException) as missing:
                    activate_device(
                        session,
                        key=missing_plaintext,
                        device_code=device_code,
                        old_token=None,
                    )
                assert missing.value.status_code == 400
                assert (
                    missing.value.detail
                    == "Activation key not found; check letter O and digit 0"
                )
                session.refresh(credential)
                assert credential.token_hash == token_hash_before
                assert credential.tenant_id == tenant_id
                for key_id in (first.id, replacement.id):
                    row = session.get(ActivationKey, key_id)
                    session.refresh(row)
                    assert row.used_at is None and row.used_terminal_id is None
                with EsopTenantUnitOfWork(session, tenant_id):
                    terminal = session.get(Terminal, identity.terminal_id)
                    assert not terminal.is_active and terminal.station_id is None
                    logs_after = session.exec(
                        select(ActivationUnbindLog).where(
                            ActivationUnbindLog.terminal_id == identity.terminal_id
                        )
                    ).all()
                    assert [row.id for row in logs_after] == [
                        row.id for row in logs_before
                    ]
                new_identity, new_token = activate_device(
                    session,
                    key=replacement_plaintext,
                    device_code=device_code,
                    old_token=None,
                )
                assert new_identity == identity
                assert new_token != old_token
                assert resolve_device(session, new_token) == identity
                profile = terminal_profile(
                    session, new_identity, appVersion="reactivation-test"
                )
                assert profile["tenantId"] == str(tenant_id)
                assert profile["siteId"] == "" and profile["lineId"] == ""
                with pytest.raises(HTTPException) as still_revoked:
                    resolve_device(session, old_token)
                assert still_revoked.value.status_code == 401
                released = session.get(ActivationKey, first.id)
                used = session.get(ActivationKey, replacement.id)
                session.refresh(released)
                session.refresh(used)
                assert released.used_at is None and released.used_terminal_id is None
                assert used.used_at is not None
                assert used.used_terminal_id == identity.terminal_id
                with EsopTenantUnitOfWork(session, tenant_id):
                    terminal = session.get(Terminal, identity.terminal_id)
                    assert terminal.is_active
                # Existing issued keys containing ambiguous characters remain valid.
                legacy_plaintext = "O0I1" + uuid.uuid4().hex[:4].upper()
                with monkeypatch.context() as patched:
                    characters = iter(legacy_plaintext)
                    patched.setattr(
                        "app.modules.esop.infrastructure.device_auth.secrets.choice",
                        lambda _: next(characters),
                    )
                    legacy_key, legacy_issued = issue_key(
                        session, tenant_id, grant_type="free"
                    )
                assert legacy_issued == legacy_plaintext
                session.commit()
                legacy_identity, legacy_token = activate_device(
                    session,
                    key=legacy_plaintext,
                    device_code="legacy-" + uuid.uuid4().hex,
                    old_token=None,
                )
                assert legacy_identity.tenant_id == tenant_id
                assert resolve_device(session, legacy_token) == legacy_identity
                session.refresh(legacy_key)
                assert legacy_key.used_terminal_id == legacy_identity.terminal_id
        finally:
            outer.rollback()


@pytest.mark.parametrize("orphan", [False, True])
def test_cross_tenant_reactivation_requires_released_existing_terminal(orphan):
    assert settings.DATABASE_TYPE == "mysql"
    assert settings.MYSQL_DB == "esop_fva_test_20261024"
    old_tenant, new_tenant = uuid.uuid4(), uuid.uuid4()
    device_code = "tenant-rebind-" + uuid.uuid4().hex
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            ) as session:
                old_key, old_plaintext = issue_key(
                    session, old_tenant, grant_type="free"
                )
                new_key, new_plaintext = issue_key(
                    session, new_tenant, grant_type="free"
                )
                session.commit()
                old_identity, old_token = activate_device(
                    session, key=old_plaintext, device_code=device_code, old_token=None
                )
                credential = session.exec(
                    select(DeviceCredential).where(
                        DeviceCredential.device_code == device_code
                    )
                ).one()
                old_hash = credential.token_hash
                with pytest.raises(HTTPException) as active_conflict:
                    activate_device(
                        session,
                        key=new_plaintext,
                        device_code=device_code,
                        old_token=None,
                    )
                assert active_conflict.value.status_code == 409
                session.refresh(credential)
                session.refresh(new_key)
                assert credential.token_hash == old_hash
                assert credential.tenant_id == old_tenant
                assert credential.terminal_id == old_identity.terminal_id
                assert new_key.used_at is None and new_key.used_terminal_id is None
                assert resolve_device(session, old_token) == old_identity
                with EsopTenantUnitOfWork(session, old_tenant):
                    assert (
                        session.exec(
                            select(ActivationUnbindLog).where(
                                ActivationUnbindLog.terminal_id
                                == old_identity.terminal_id
                            )
                        ).all()
                        == []
                    )
                terminal_unbind(session, old_identity)
                with EsopTenantUnitOfWork(session, old_tenant):
                    released_terminal = session.get(Terminal, old_identity.terminal_id)
                    assert (
                        released_terminal is not None
                        and not released_terminal.is_active
                    )
                    logs = session.exec(
                        select(ActivationUnbindLog).where(
                            ActivationUnbindLog.terminal_id == old_identity.terminal_id
                        )
                    ).all()
                    assert len(logs) == 1
                    log_id = logs[0].id
                    if orphan:
                        session.delete(released_terminal)
                        session.commit()
                if orphan:
                    with pytest.raises(HTTPException) as missing_terminal:
                        activate_device(
                            session,
                            key=new_plaintext,
                            device_code=device_code,
                            old_token=None,
                        )
                    assert missing_terminal.value.status_code == 409
                    session.refresh(credential)
                    session.refresh(new_key)
                    assert credential.tenant_id == old_tenant
                    assert credential.terminal_id == old_identity.terminal_id
                    assert new_key.used_at is None and new_key.used_terminal_id is None
                else:
                    new_identity, new_token = activate_device(
                        session,
                        key=new_plaintext,
                        device_code=device_code,
                        old_token=None,
                    )
                    assert new_identity.tenant_id == new_tenant
                    assert new_identity.terminal_id != old_identity.terminal_id
                    assert new_token != old_token
                    assert resolve_device(session, new_token) == new_identity
                    profile = terminal_profile(session, new_identity)
                    assert profile["tenantId"] == str(new_tenant)
                    assert profile["siteId"] == "" and profile["lineId"] == ""
                    session.refresh(credential)
                    assert credential.tenant_id == new_tenant
                    assert credential.terminal_id == new_identity.terminal_id
                    with EsopTenantUnitOfWork(session, old_tenant):
                        historical = session.get(Terminal, old_identity.terminal_id)
                        assert (
                            historical.tenant_id == old_tenant
                            and not historical.is_active
                        )
                        assert historical.station_id is None
                    session.refresh(new_key)
                    assert new_key.used_at is not None
                    assert new_key.used_terminal_id == new_identity.terminal_id
                with pytest.raises(HTTPException) as old_revoked:
                    resolve_device(session, old_token)
                assert old_revoked.value.status_code == 401
                session.refresh(old_key)
                assert old_key.used_at is None and old_key.used_terminal_id is None
                with EsopTenantUnitOfWork(session, old_tenant):
                    historical_log = session.get(ActivationUnbindLog, log_id)
                    assert historical_log.tenant_id == old_tenant
                    assert historical_log.terminal_id == old_identity.terminal_id
                    assert historical_log.key_id == old_key.id
        finally:
            outer.rollback()
