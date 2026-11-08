"""Activated devices cannot release their own authorization."""

import uuid
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.modules.esop.infrastructure.device_auth import (
    activate_device,
    issue_key,
    resolve_device,
)
from app.modules.esop.infrastructure.models import (
    ALL_MODELS,
    ActivationKey,
    ActivationUnbindLog,
    Terminal,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.terminal_routes import terminal_unbind


def test_terminal_cannot_release_own_key_and_authorization_is_preserved(monkeypatch):
    monkeypatch.setattr(settings, "ESOP_ACTIVATION_CIPHER_KEY", Fernet.generate_key().decode())
    engine = create_engine(
        "sqlite://", poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS])
    tenant = uuid.uuid4()
    monkeypatch.setattr("app.platform.web_api.resolve_channel_customer_code",
        lambda **kwargs: SimpleNamespace(id=tenant, code="test-tenant", name="Test"))
    with Session(engine) as session:
        key_row, key = issue_key(session, tenant, grant_type="free")
        session.commit()
        device, token = activate_device(session, key=key, device_code="tablet-1", old_token=None, tenant_code="test-tenant")
        with pytest.raises(HTTPException) as denied:
            terminal_unbind(session, device)
        assert denied.value.status_code == 403
        assert "后台" in denied.value.detail
        assert resolve_device(session, token) == device
        with EsopTenantUnitOfWork(session, tenant):
            assert session.get(Terminal, device.terminal_id).is_active
        retained = session.get(ActivationKey, key_row.id)
        assert retained.used_at is not None and retained.used_terminal_id == device.terminal_id
        assert session.exec(select(ActivationUnbindLog)).all() == []
