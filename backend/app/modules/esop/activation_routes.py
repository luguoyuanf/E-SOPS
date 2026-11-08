"""Role-scoped activation inventory and platform-only device revocation."""

import csv
import io
import uuid
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import select

from app.core.export_datetime import (
    ExportTimezoneHeader,
    export_datetime,
    export_timezone,
)
from app.modules.esop.infrastructure.device_auth import issue_key
from app.modules.esop.infrastructure.key_cipher import decrypt_key
from app.modules.esop.infrastructure.models import (
    ActivationKey,
    ActivationUnbindLog,
    Channel,
    ChannelAdmin,
    ChannelCustomerTenant,
    DeviceCredential,
    HardwareModel,
    Terminal,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.terminal_dto import (
    ActivationIssueInput,
    ActivationKeyPublic,
    ActivationUnbindInput,
    IssuedActivationKey,
    ListActivationKeys,
)
from app.platform.web_api import (
    CurrentPrincipal,
    CurrentTenant,
    SessionDep,
    get_channel_customer_tenants,
    require_module_access,
)

router = APIRouter(prefix="/esop", tags=["esop-activation"])
key_access = [Depends(require_module_access("esop", "esop:device:key-list"))]


def visible_keys(session, principal, tenant):
    query = select(ActivationKey)
    if principal.is_superuser:
        return query
    channel = session.exec(select(ChannelAdmin).where(ChannelAdmin.user_id == principal.id)).first()
    if channel is not None:
        customers = select(ChannelCustomerTenant.tenant_id).where(ChannelCustomerTenant.channel_id == channel.channel_id)
        return query.where(or_(ActivationKey.channel_id == channel.channel_id, ActivationKey.tenant_id.in_(customers)))
    return query.where(ActivationKey.tenant_id == tenant.tenant_id)


def public_key(session, row):
    device_code = None
    if row.tenant_id is not None and row.used_terminal_id is not None:
        with EsopTenantUnitOfWork(session, row.tenant_id):
            terminal = session.get(Terminal, row.used_terminal_id)
            device_code = terminal.serial_number if terminal else None
    return ActivationKeyPublic(
        id=row.id, tenant_id=row.tenant_id, channel_id=row.channel_id,
        hardware_model_id=row.hardware_model_id, key=decrypt_key(row.key_ciphertext),
        created_at=row.created_at, used_at=row.used_at, is_used=row.used_at is not None,
        used_terminal_id=row.used_terminal_id, device_code=device_code,
    )


@router.get("/activation-keys", dependencies=key_access, response_model=ListActivationKeys)
def list_activation_keys(
    session: SessionDep, current_principal: CurrentPrincipal, tenant: CurrentTenant,
    is_used: bool | None = None, tenant_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
) -> ListActivationKeys:
    query = visible_keys(session, current_principal, tenant)
    if is_used is not None:
        query = query.where(ActivationKey.used_at.is_not(None) if is_used else ActivationKey.used_at.is_(None))
    if tenant_id is not None:
        query = query.where(ActivationKey.tenant_id == tenant_id)
    if channel_id is not None:
        query = query.where(ActivationKey.channel_id == channel_id)
    rows = session.exec(query.order_by(ActivationKey.created_at.desc())).all()
    return ListActivationKeys(items=[public_key(session, row) for row in rows], total=len(rows))


@router.post("/activation-keys", dependencies=[Depends(require_module_access("esop", "esop:device:issue"))], response_model=IssuedActivationKey)
def issue_activation_key(
    session: SessionDep, current_principal: CurrentPrincipal,
    body: ActivationIssueInput,
) -> IssuedActivationKey:
    if not current_principal.is_superuser:
        raise HTTPException(status_code=403, detail="Platform administrator required")
    target = body.tenant_id
    channel_id = body.channel_id
    if target is None and body.channel_id is None:
        raise HTTPException(status_code=422, detail="Tenant or channel required")
    if target is not None and not get_channel_customer_tenants(session=session, tenant_ids=[target]):
        raise HTTPException(status_code=404, detail="Tenant not found")
    if body.channel_id is not None and session.get(Channel, body.channel_id) is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    if body.hardware_model_id is not None:
        hardware = session.get(HardwareModel, body.hardware_model_id)
        if hardware is None or hardware.channel_id != body.channel_id:
            raise HTTPException(status_code=422, detail="Hardware model does not match channel")
    if target is not None:
        customer = session.exec(select(ChannelCustomerTenant).where(ChannelCustomerTenant.tenant_id == target)).first()
        if channel_id is not None and (customer is None or customer.channel_id != channel_id):
            raise HTTPException(status_code=422, detail="Tenant does not belong to channel")
        if channel_id is None and customer is not None:
            channel_id = customer.channel_id
    row, plaintext = issue_key(session, target, channel_id=channel_id, hardware_model_id=body.hardware_model_id, batch_id=uuid.uuid4() if target is None else None)
    session.commit()
    return IssuedActivationKey(**public_key(session, row).model_dump(exclude={"key"}), key=plaintext)


@router.post("/activation-keys/export", dependencies=key_access, response_model=None)
def export_activation_keys(
    session: SessionDep, current_principal: CurrentPrincipal, tenant: CurrentTenant,
    is_used: bool | None = None, tenant_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    x_export_timezone: ExportTimezoneHeader = None,
):
    timezone = export_timezone(x_export_timezone)
    result = list_activation_keys(session, current_principal, tenant, is_used, tenant_id, channel_id)
    if result.total > 1000:
        raise HTTPException(status_code=422, detail="Export is limited to 1000 keys; narrow filters")
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["密钥", "租户ID", "渠道ID", "状态", "设备编号", "激活时间"])
    for row in result.items:
        writer.writerow([row.key or "不可回读", row.tenant_id or "", row.channel_id or "", "已使用" if row.is_used else "未使用", "'" + row.device_code if row.device_code else "", export_datetime(row.used_at, timezone)])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('激活密钥.csv')}"})


@router.post("/activation-keys/{key_id}/unbind", dependencies=[Depends(require_module_access("esop", "esop:device:issue"))], response_model=ActivationKeyPublic)
def unbind_activation_key(
    session: SessionDep, current_principal: CurrentPrincipal,
    key_id: uuid.UUID, body: ActivationUnbindInput,
) -> ActivationKeyPublic:
    if not current_principal.is_superuser:
        raise HTTPException(status_code=403, detail="Platform administrator required")
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="Unbind reason required")
    row = session.exec(select(ActivationKey).where(ActivationKey.id == key_id).with_for_update()).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Activation key not found")
    if row.tenant_id is None or row.used_at is None or row.used_terminal_id is None:
        raise HTTPException(status_code=409, detail="Activation key is not used")
    with EsopTenantUnitOfWork(session, row.tenant_id):
        terminal = session.get(Terminal, row.used_terminal_id)
        if terminal is None:
            raise HTTPException(status_code=409, detail="Activated terminal not found")
        session.add(ActivationUnbindLog(
            key_id=row.id, tenant_id=row.tenant_id, terminal_id=terminal.id,
            device_code=terminal.device_code, activated_at=row.used_at,
            actor_id=current_principal.id, reason=body.reason.strip(),
        ))
        terminal.is_active = False
        terminal.station_id = None
        session.add(terminal)
        credential = session.exec(select(DeviceCredential).where(DeviceCredential.terminal_id == terminal.id)).first()
        if credential is not None:
            # Keep the device/tenant reservation; rotate the revoked credential.
            credential.token_hash = uuid.uuid4().hex + uuid.uuid4().hex
            session.add(credential)
        row.used_at = None
        row.used_terminal_id = None
        session.add(row)
        session.commit()
    return public_key(session, row)


class UnbindHistoryPublic(BaseModel):
    terminal_id: uuid.UUID
    device_code: str
    activated_at: datetime
    unbound_at: datetime
    actor_id: uuid.UUID
    reason: str


@router.get("/activation-keys/{key_id}/unbind-history", dependencies=key_access, response_model=list[UnbindHistoryPublic])
def activation_unbind_history(
    session: SessionDep, current_principal: CurrentPrincipal, tenant: CurrentTenant,
    key_id: uuid.UUID,
) -> list[UnbindHistoryPublic]:
    key = session.exec(visible_keys(session, current_principal, tenant).where(ActivationKey.id == key_id)).first()
    if key is None:
        raise HTTPException(status_code=404, detail="Activation key not found")
    rows = session.exec(select(ActivationUnbindLog).where(ActivationUnbindLog.key_id == key_id).order_by(ActivationUnbindLog.unbound_at.desc())).all()
    return [UnbindHistoryPublic(**row.model_dump()) for row in rows]
