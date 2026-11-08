"""Allocate stable, non-authorizing server device numbers for installations."""

import hashlib
import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.modules.esop.infrastructure.models import (
    DeviceCredential,
    TerminalInstallation,
)


def allocate_terminal_serial(session: Session) -> str:
    for _ in range(10):
        code = f"SN{secrets.randbelow(100_000_000):08d}"
        if session.exec(select(DeviceCredential.id).where(DeviceCredential.device_code == code)).first():
            continue
        try:
            with session.begin_nested():
                session.add(TerminalInstallation(
                    installation_hash=hashlib.sha256(f"reserved:{uuid.uuid4()}".encode()).hexdigest(),
                    device_code=code,
                ))
                session.flush()
            return code
        except IntegrityError:
            continue
    raise HTTPException(status_code=503, detail="Device number allocation is unavailable")


def installation_device_code(session: Session, installation_id: str) -> str:
    digest = hashlib.sha256(installation_id.encode()).hexdigest()
    existing = session.exec(select(TerminalInstallation).where(
        TerminalInstallation.installation_hash == digest,
    )).first()
    if existing is not None:
        return existing.device_code
    for _ in range(10):
        code = f"SN{secrets.randbelow(100_000_000):08d}"
        if session.exec(select(DeviceCredential.id).where(
            DeviceCredential.device_code == code,
        )).first() is not None:
            continue
        try:
            with session.begin_nested():
                session.add(TerminalInstallation(installation_hash=digest, device_code=code))
                session.flush()
            return code
        except IntegrityError:
            # Locking reads see a concurrent winner under MySQL REPEATABLE READ.
            existing = session.exec(select(TerminalInstallation).where(
                TerminalInstallation.installation_hash == digest,
            ).with_for_update()).first()
            if existing is not None:
                return existing.device_code
    raise HTTPException(status_code=503, detail="Device number allocation is unavailable")
