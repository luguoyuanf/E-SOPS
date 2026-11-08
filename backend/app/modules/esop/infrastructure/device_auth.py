"""Opaque device credentials and one-use activation keys."""

import hashlib
import hmac
import secrets
import string
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.modules.esop.infrastructure.device_installation import allocate_terminal_serial
from app.modules.esop.infrastructure.key_cipher import encrypt_key
from app.modules.esop.infrastructure.models import (
    ActivationKey,
    ChannelCustomerTenant,
    DeviceCredential,
    Terminal,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.platform.web_api import (
    ensure_paid_activation_storage,
    require_resolved_tenant_module_access,
)

ALPHABET = string.ascii_uppercase + string.digits
ISSUED_KEY_ALPHABET = "".join(char for char in ALPHABET if char not in "O0I1")


def _digest(value: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def issue_key(
    session: Session, tenant_id: uuid.UUID | None, *, grant_type: str = "paid",
    channel_id: uuid.UUID | None = None,
    hardware_model_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
) -> tuple[ActivationKey, str]:
    if grant_type not in {"free", "paid"}:
        raise ValueError("Invalid activation grant type")
    for _ in range(10):
        plaintext = "".join(secrets.choice(ISSUED_KEY_ALPHABET) for _ in range(8))
        digest = _digest(f"key:{plaintext}")
        if session.exec(select(ActivationKey.id).where(ActivationKey.key_hash == digest)).first() is None:
            row = ActivationKey(
                tenant_id=tenant_id, key_hash=digest,
                key_ciphertext=encrypt_key(plaintext), grant_type=grant_type,
                channel_id=channel_id, hardware_model_id=hardware_model_id,
                batch_id=batch_id,
            )
            session.add(row)
            session.flush()
            return row, plaintext
    raise RuntimeError("Unable to allocate an activation key")



@dataclass(frozen=True)
class DeviceIdentity:
    tenant_id: uuid.UUID
    terminal_id: uuid.UUID


def resolve_device(session: Session, token: str) -> DeviceIdentity:
    if not token or len(token) != 64:
        raise HTTPException(status_code=401, detail="Invalid device credential")
    token_hash = _digest(f"token:{token}")
    credential = session.exec(
        select(DeviceCredential).where(DeviceCredential.token_hash == token_hash)
    ).first()
    if credential is None:
        raise HTTPException(status_code=401, detail="Invalid device credential")
    with EsopTenantUnitOfWork(session, credential.tenant_id):
        terminal = session.get(Terminal, credential.terminal_id)
        if terminal is None or not terminal.is_active or terminal.tenant_id != credential.tenant_id:
            raise HTTPException(status_code=401, detail="Invalid device credential")
    if credential.device_code.startswith("web:"):
        require_resolved_tenant_module_access(
            session=session, tenant_id=credential.tenant_id, module_code="esop",
        )
    return DeviceIdentity(credential.tenant_id, credential.terminal_id)


def activate_device(
    session: Session, *, key: str, device_code: str, old_token: str | None,
    tenant_code: str | None = None
) -> tuple[DeviceIdentity, str]:
    if device_code == "WEB" or device_code.startswith("web:"):
        raise HTTPException(status_code=400, detail="Reserved web terminal identity")
    normalized = key.strip().upper()
    if len(normalized) != 8 or any(char not in ALPHABET for char in normalized):
        raise HTTPException(
            status_code=400, detail="Activation key must contain exactly 8 letters or digits"
        )
    from app.platform.web_api import resolve_channel_customer_code

    if not tenant_code:
        raise HTTPException(status_code=422, detail="Tenant code is required for activation")
    tenant = resolve_channel_customer_code(session=session, code=tenant_code)
    mapping = session.exec(select(ChannelCustomerTenant).where(
        ChannelCustomerTenant.tenant_id == tenant.id,
    ).with_for_update()).first()
    key_record = session.exec(
        select(ActivationKey).where(ActivationKey.key_hash == _digest(f"key:{normalized}")).with_for_update()
    ).first()
    if key_record is None:
        raise HTTPException(
            status_code=400, detail="Activation key not found; check letter O and digit 0"
        )
    if key_record.tenant_id is None:
        if key_record.channel_id is None or mapping is None or mapping.channel_id != key_record.channel_id:
            raise HTTPException(status_code=403, detail="Activation key does not belong to the tenant channel")
    elif tenant.id != key_record.tenant_id:
        raise HTTPException(status_code=403, detail="Activation key does not match tenant code")
    elif key_record.channel_id is not None and (mapping is None or mapping.channel_id != key_record.channel_id):
        raise HTTPException(status_code=403, detail="Activation key does not belong to the tenant channel")
    target_tenant_id = tenant.id
    token = secrets.token_hex(32)
    token_hash = _digest(f"token:{token}")
    existing = session.exec(
        select(DeviceCredential).where(
            DeviceCredential.device_code == device_code
        ).with_for_update()
    ).first()
    if key_record.used_at is not None:
        if (
            existing is not None and key_record.used_terminal_id == existing.terminal_id
            and old_token is not None
            and hmac.compare_digest(existing.token_hash, _digest(f"token:{old_token}"))
        ):
            resolve_device(session, old_token)
            return DeviceIdentity(existing.tenant_id, existing.terminal_id), old_token
        raise HTTPException(status_code=409, detail="Activation key is already used")
    if existing is not None:
        with EsopTenantUnitOfWork(session, existing.tenant_id):
            current = session.get(Terminal, existing.terminal_id, with_for_update=True)
            if existing.tenant_id != target_tenant_id and (
                current is None or current.is_active
            ):
                raise HTTPException(status_code=409, detail="Device belongs to another tenant")
            if current is not None and current.is_active:
                raise HTTPException(status_code=409, detail="Device already has an active authorization")
    with EsopTenantUnitOfWork(session, target_tenant_id):
        terminal = session.exec(select(Terminal).where(Terminal.device_code == device_code)).first()
        if terminal is None:
            serial = device_code if len(device_code) == 10 and device_code.startswith("SN") and device_code[2:].isdigit() else allocate_terminal_serial(session)
            terminal = Terminal(tenant_id=target_tenant_id, device_code=device_code, serial_number=serial)
        terminal.is_active = True
        terminal.channel_id = key_record.channel_id
        terminal.hardware_model_id = key_record.hardware_model_id
        session.add(terminal)
        session.flush()
    if existing is None:
        session.add(DeviceCredential(
            device_code=device_code, token_hash=token_hash,
            tenant_id=target_tenant_id, terminal_id=terminal.id,
        ))
    else:
        existing.token_hash = token_hash
        existing.tenant_id = target_tenant_id
        existing.terminal_id = terminal.id
        session.add(existing)
    key_record.tenant_id = target_tenant_id
    key_record.used_at = get_datetime_utc()
    key_record.used_terminal_id = terminal.id
    session.add(key_record)
    if key_record.grant_type == "paid":
        ensure_paid_activation_storage(session=session, tenant_id=target_tenant_id)
    session.commit()
    return DeviceIdentity(target_tenant_id, terminal.id), token
