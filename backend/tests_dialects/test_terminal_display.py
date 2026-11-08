"""Visible terminal names and numbers preserve the device credential identity."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.modules.esop.infrastructure.models import Terminal
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.terminal_dto import TerminalNameInput
from app.modules.esop.terminal_routes import update_terminal_name


def test_rename_terminal_keeps_identity_and_rejects_other_tenant() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[Terminal.__table__])
    owner, outsider = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as session:
        with EsopTenantUnitOfWork(session, owner):
            terminal = Terminal(tenant_id=owner, device_code="legacy-identity-123",
                                serial_number="SN12345678")
            terminal_id = terminal.id
            session.add(terminal)
            session.commit()
        with EsopTenantUnitOfWork(session, outsider) as uow:
            with pytest.raises(HTTPException) as missing:
                update_terminal_name(uow, terminal_id, TerminalNameInput(device_name="其他租户"))
            assert missing.value.status_code == 404
        with EsopTenantUnitOfWork(session, owner) as uow:
            with pytest.raises(HTTPException) as empty:
                update_terminal_name(uow, terminal_id, TerminalNameInput(device_name="   "))
            assert empty.value.status_code == 422
            result = update_terminal_name(uow, terminal_id, TerminalNameInput(device_name="  装配屏  "))
            assert (result.serial_number, result.device_name) == ("SN12345678", "装配屏")
            assert result.device_code == "legacy-identity-123"
