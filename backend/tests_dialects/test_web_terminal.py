"""Browser terminals reuse device isolation and preserve the administrator boundary."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.modules.esop.infrastructure.device_auth import activate_device, resolve_device
from app.modules.esop.infrastructure.models import (
    DeviceCredential,
    Terminal,
    TerminalInstallation,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.web_terminal import (
    anonymous_web_terminal,
    initialize_web_terminal,
    open_web_terminal,
    web_device_token,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[
        Terminal.__table__, TerminalInstallation.__table__, DeviceCredential.__table__,
    ])
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_unique_web_terminal_per_tenant_and_anonymous_identity(session, monkeypatch):
    monkeypatch.setattr("app.modules.access.evaluate_module_access", lambda **kw: SimpleNamespace(allowed=True))
    owner, other = uuid.uuid4(), uuid.uuid4()
    for tenant in (owner, other, owner):
        initialize_web_terminal(session, tenant)
    session.commit()
    ids = []
    for tenant in (owner, other):
        with EsopTenantUnitOfWork(session, tenant):
            rows = session.exec(select(Terminal)).all()
            assert len(rows) == 1
            row = rows[0]
            assert row.app_version == "Web版"
            assert row.device_code == "WEB" and row.station_id is None
            assert row.serial_number.startswith("SN") and len(row.serial_number) == 10
            ids.append(row.id)
    assert ids[0] != ids[1]
    monkeypatch.setattr("app.modules.esop.terminal_routes.terminal_profile", lambda *args: {"tenantName": "测试租户"})
    response = Response()
    identity = anonymous_web_terminal(ids[0], session, response)
    assert identity.tenantId == owner and identity.deviceId == ids[0]
    assert identity.profile["tenantName"] == "测试租户"
    assert response.headers["cache-control"] == "no-store"
    assert resolve_device(session, identity.deviceToken).tenant_id == owner
    assert web_device_token(ids[0]) != web_device_token(ids[1])


def test_open_requires_admin_and_tenant_scope(session):
    owner, other = uuid.uuid4(), uuid.uuid4()
    initialize_web_terminal(session, owner)
    with EsopTenantUnitOfWork(session, owner) as uow:
        row = session.exec(select(Terminal)).one()
        id = row.id
        principal = SimpleNamespace(id=uuid.uuid4(), is_superuser=False)
        users = SimpleNamespace(is_tenant_administrator=lambda *args: False)
        with pytest.raises(HTTPException) as denied:
            open_web_terminal(id, uow, principal, users)
        assert denied.value.status_code == 403
        users.is_tenant_administrator = lambda *args: True
        assert open_web_terminal(id, uow, principal, users)["path"] == f"/web-terminal/{id}"
    with EsopTenantUnitOfWork(session, other) as uow:
        with pytest.raises(HTTPException) as denied:
            open_web_terminal(id, uow, principal, users)
        assert denied.value.status_code == 404


def test_unknown_inactive_disabled_and_android_identity_are_rejected(session, monkeypatch):
    monkeypatch.setattr("app.modules.access.evaluate_module_access", lambda **kw: SimpleNamespace(allowed=False, error_code="TENANT_MODULE_DISABLED"))
    owner = uuid.uuid4()
    initialize_web_terminal(session, owner)
    with EsopTenantUnitOfWork(session, owner):
        id = session.exec(select(Terminal.id)).one()
    with pytest.raises(HTTPException) as denied:
        anonymous_web_terminal(id, session, Response())
    assert denied.value.status_code == 403
    with EsopTenantUnitOfWork(session, owner):
        row = session.get(Terminal, id)
        row.is_active = False
        session.add(row)
        session.commit()
    with pytest.raises(HTTPException) as denied:
        anonymous_web_terminal(id, session, Response())
    assert denied.value.status_code == 401
    with pytest.raises(HTTPException) as denied:
        anonymous_web_terminal(uuid.uuid4(), session, Response())
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        activate_device(session, key="ABCDEFGH", device_code="WEB", old_token=None)
    assert denied.value.status_code == 400


def test_web_module_access_reads_under_resolved_platform_scope(session, monkeypatch):
    owner = uuid.uuid4()
    initialize_web_terminal(session, owner)
    with EsopTenantUnitOfWork(session, owner):
        terminal_id = session.exec(select(Terminal.id)).one()
    def evaluate(**kwargs):
        assert kwargs["session"].info["platform_tenant_id"] == owner
        return SimpleNamespace(allowed=True)
    monkeypatch.setattr("app.modules.access.evaluate_module_access", evaluate)
    assert resolve_device(session, web_device_token(terminal_id)).tenant_id == owner
    assert session.info.get("platform_tenant_id") is None
