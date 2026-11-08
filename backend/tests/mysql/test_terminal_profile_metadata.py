"""Display metadata follows the authenticated device; synthetic rows roll back."""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from sqlmodel import Session

from app.core.config import settings
from app.core.database import engine
from app.modules.esop import terminal_routes
from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import (
    ProductionLine,
    Station,
    Terminal,
    Workshop,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork


@pytest.mark.parametrize("bound", [False, True])
def test_terminal_profile_metadata_refresh_and_tenant_boundary(monkeypatch, bound):
    assert settings.DATABASE_TYPE == "mysql"
    assert settings.MYSQL_DB == "esop_fva_test_20261024"
    tenant_id, foreign_tenant_id = uuid.uuid4(), uuid.uuid4()
    tenant_name = ["当前租户"]
    directory_calls = []

    def tenant_directory(*, session, tenant_ids):
        assert isinstance(session, Session)
        directory_calls.append(tenant_ids)
        # Even an over-broad directory result must not supply another tenant's name.
        return [
            SimpleNamespace(id=foreign_tenant_id, name="其他租户机密名称"),
            SimpleNamespace(id=tenant_id, name=tenant_name[0]),
        ]

    monkeypatch.setattr(terminal_routes, "get_channel_customer_tenants", tenant_directory)
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                with EsopTenantUnitOfWork(session, tenant_id):
                    station_id = None
                    if bound:
                        workshop = Workshop(tenant_id=tenant_id, code=uuid.uuid4().hex, name="车间")
                        session.add(workshop)
                        session.flush()
                        line = ProductionLine(
                            tenant_id=tenant_id, workshop_id=workshop.id,
                            code=uuid.uuid4().hex, name="产线",
                        )
                        session.add(line)
                        session.flush()
                        station = Station(
                            tenant_id=tenant_id, line_id=line.id, position=1,
                            name="工位", row=1, column=1,
                        )
                        session.add(station)
                        session.flush()
                        station_id = station.id
                    terminal = Terminal(
                        tenant_id=tenant_id, device_code="profile-" + uuid.uuid4().hex,
                        device_name="设备初始名称" if bound else None, station_id=station_id,
                    )
                    session.add(terminal)
                    session.commit()
                    identity = DeviceIdentity(tenant_id, terminal.id)
                    serial, device_code = terminal.serial_number, terminal.device_code
                with EsopTenantUnitOfWork(session, foreign_tenant_id):
                    foreign = Terminal(
                        tenant_id=foreign_tenant_id, device_code="foreign-" + uuid.uuid4().hex,
                        device_name="其他租户机密设备",
                    )
                    session.add(foreign)
                    session.commit()
                    foreign_id = foreign.id
                request = Request({"type": "http", "headers": [(b"x-forwarded-for", b"192.0.2.18")], "client": ("127.0.0.1", 1234)})
                profile = terminal_routes.terminal_profile(session, identity, request=request)
                assert profile["serialNumber"] == serial
                assert profile["deviceName"] == ("设备初始名称" if bound else "")
                assert profile["deviceCode"] == device_code
                assert profile["tenantName"] == tenant_name[0]
                assert profile["siteId"] == (str(station_id) if bound else "")
                assert profile["lineName"] == ("产线" if bound else "")
                assert directory_calls == [[tenant_id]]
                with EsopTenantUnitOfWork(session, tenant_id):
                    listed = terminal_routes.list_terminals(SimpleNamespace(session=session))
                    current_row = next(row for row in listed.items if row.id == terminal.id)
                    assert current_row.is_online is True
                    assert current_row.last_ip == "192.0.2.18"
                    current = session.get(Terminal, identity.terminal_id)
                    current.last_seen_at -= timedelta(seconds=121)
                    session.add(current)
                    session.flush()
                    stale = terminal_routes.list_terminals(SimpleNamespace(session=session))
                    assert next(row for row in stale.items if row.id == terminal.id).is_online is False
                with EsopTenantUnitOfWork(session, tenant_id):
                    current = session.get(Terminal, identity.terminal_id)
                    current.device_name = "后台重命名后的设备"
                    session.add(current)
                    session.commit()
                tenant_name[0] = "后台重命名后的租户"
                refreshed = terminal_routes.terminal_profile(session, identity)
                assert refreshed["deviceName"] == "后台重命名后的设备"
                assert refreshed["tenantName"] == tenant_name[0]
                assert refreshed["serialNumber"] == serial
                assert refreshed["deviceCode"] == device_code
                assert directory_calls == [[tenant_id], [tenant_id]]
                with pytest.raises(HTTPException) as rejected:
                    terminal_routes.terminal_profile(session, DeviceIdentity(tenant_id, foreign_id))
                assert rejected.value.status_code == 401
                assert directory_calls == [[tenant_id], [tenant_id]]
        finally:
            outer.rollback()
