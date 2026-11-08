"""Server serial allocation on the fixed online MySQL; fixtures roll back."""

import hashlib
import re
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session, select
from starlette.requests import Request

from app.core.config import settings
from app.core.database import engine
from app.modules.esop import terminal_routes
from app.modules.esop.infrastructure import device_installation
from app.modules.esop.infrastructure.models import (
    DeviceCredential,
    TerminalInstallation,
)
from app.modules.esop.public_api.terminal_dto import InstallationInput


def test_server_serial_is_idempotent_unique_and_grants_no_authorization(monkeypatch):
    assert settings.DATABASE_TYPE == "mysql"
    assert settings.MYSQL_DB == "esop_fva_test_20261024"
    first_id, second_id = uuid.uuid4().hex, uuid.uuid4().hex
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                first = device_installation.installation_device_code(session, first_id)
                assert re.fullmatch(r"SN[0-9]{8}", first)
                assert device_installation.installation_device_code(session, first_id) == first
                # Force a real unique-key collision, then allow another random number.
                random_number = device_installation.secrets.randbelow
                choices = [int(first[2:])]
                monkeypatch.setattr(
                    device_installation.secrets, "randbelow",
                    lambda limit: choices.pop() if choices else random_number(limit),
                )
                second = device_installation.installation_device_code(session, second_id)
                assert second != first
                rows = session.exec(select(TerminalInstallation).where(
                    TerminalInstallation.installation_hash.in_([
                        hashlib.sha256(value.encode()).hexdigest() for value in (first_id, second_id)
                    ]),
                )).all()
                assert len(rows) == 2
                assert all(row.installation_hash not in (first_id, second_id) for row in rows)
                assert session.exec(select(DeviceCredential).where(
                    DeviceCredential.device_code.in_([first, second]),
                )).all() == []
        finally:
            outer.rollback()


def test_installation_input_and_rate_limit_fail_before_database_access(monkeypatch):
    for value in ("short", "x" * 121, "contains invalid space"):
        with pytest.raises(ValidationError):
            InstallationInput(installationId=value)
    body = InstallationInput(installationId=uuid.uuid4().hex)
    request = Request({"type": "http", "client": ("127.0.0.1", 1234)})
    for attempts, status in ((None, 503), (61, 429)):
        monkeypatch.setattr(terminal_routes.redis_cache, "incr", lambda *args, value=attempts, **kwargs: value)
        with pytest.raises(HTTPException) as error:
            terminal_routes.register_terminal_installation(None, request, body)
        assert error.value.status_code == status
