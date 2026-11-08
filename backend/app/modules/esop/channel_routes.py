"""Manual channel grant and tenant-local key assignment."""

import csv
import io
import uuid
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func
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
    Channel,
    ChannelAdmin,
    ChannelCustomerTenant,
    HardwareModel,
)
from app.modules.esop.public_api.channel_dto import (
    BatchIssueInput,
    BatchSummary,
    ChannelAdminInput,
    ChannelAdminPublic,
    ChannelInventoryItem,
    ChannelWorkspace,
    CustomerInput,
    CustomerPublic,
    IssuedBatch,
    IssuedKey,
    KeyAssignInput,
    KeyAssignResult,
    KeyExportInput,
    ListBatchSummaries,
    ListChannelCustomers,
    ListChannelInventory,
)
from app.platform.public_api.codes import generate_entity_code
from app.platform.web_api import (
    CurrentPrincipal,
    SessionDep,
    UserDirectoryDep,
    create_channel_customer_tenant,
    get_channel_customer_tenants,
    normalize_pagination,
    require_module_access,
)

router = APIRouter(prefix="/esop", tags=["esop-channel"])


def _superuser(principal: CurrentPrincipal) -> None:
    if not principal.is_superuser:
        raise HTTPException(status_code=403, detail="Platform administrator required")


def _channel_admin(session: SessionDep, principal: CurrentPrincipal) -> ChannelAdmin:
    binding = session.exec(select(ChannelAdmin).where(ChannelAdmin.user_id == principal.id)).first()
    if binding is None:
        raise HTTPException(status_code=403, detail="Channel administrator role required")
    return binding


def _channel(session: SessionDep, channel_id: uuid.UUID) -> Channel:
    channel = session.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.post(
    "/channels/{channel_id}/admins",
    dependencies=[Depends(require_module_access("esop", "esop:channel:admin"))],
    response_model=ChannelAdminPublic,
)
def bind_channel_admin(
    session: SessionDep, principal: CurrentPrincipal, users: UserDirectoryDep,
    channel_id: uuid.UUID, body: ChannelAdminInput,
) -> ChannelAdminPublic:
    _superuser(principal)
    _channel(session, channel_id)
    user = users.get_users([body.user_id])
    if not user or not user[0].is_active:
        raise HTTPException(status_code=404, detail="Active user not found")
    existing = session.exec(select(ChannelAdmin).where(ChannelAdmin.user_id == body.user_id)).first()
    if existing is not None:
        if existing.channel_id != channel_id:
            raise HTTPException(status_code=409, detail="User already administers another channel")
        return ChannelAdminPublic(channel_id=channel_id, user_id=body.user_id)
    session.add(ChannelAdmin(channel_id=channel_id, user_id=body.user_id))
    session.commit()
    return ChannelAdminPublic(channel_id=channel_id, user_id=body.user_id)


@router.post(
    "/channels/{channel_id}/keys/batches",
    dependencies=[Depends(require_module_access("esop", "esop:channel:issue"))],
    response_model=IssuedBatch,
)
def issue_channel_batch(
    session: SessionDep, principal: CurrentPrincipal,
    channel_id: uuid.UUID, body: BatchIssueInput,
) -> IssuedBatch:
    _superuser(principal)
    _channel(session, channel_id)
    if body.hardware_model_id is not None:
        hardware = session.get(HardwareModel, body.hardware_model_id)
        if hardware is None or hardware.channel_id != channel_id:
            raise HTTPException(status_code=422, detail="Hardware model does not match channel")
    batch_id = uuid.uuid4()
    keys = []
    for _ in range(body.quantity):
        row, plaintext = issue_key(
            session, None, channel_id=channel_id,
            hardware_model_id=body.hardware_model_id, batch_id=batch_id,
        )
        keys.append(IssuedKey(id=row.id, key=plaintext))
    session.commit()
    return IssuedBatch(batch_id=batch_id, keys=keys)


@router.get("/channel-workspace/me", response_model=ChannelWorkspace)
def channel_workspace(session: SessionDep, principal: CurrentPrincipal) -> ChannelWorkspace:
    binding = _channel_admin(session, principal)
    channel = _channel(session, binding.channel_id)
    return ChannelWorkspace(channel_id=channel.id, channel_code=channel.code, channel_name=channel.name)


def _key_status(row: ActivationKey) -> str:
    if row.used_at is not None:
        return "activated"
    return "assigned" if row.tenant_id is not None else "unassigned"


def _inventory(
    session: SessionDep, channel_id: uuid.UUID, batch_id: uuid.UUID | None,
    page: int, page_size: int, created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> ListChannelInventory:
    page, page_size = normalize_pagination(page=page, page_size=page_size, max_page_size=200)
    criterion = [ActivationKey.channel_id == channel_id]
    if batch_id is not None:
        criterion.append(ActivationKey.batch_id == batch_id)
    if created_from is not None:
        criterion.append(ActivationKey.created_at >= created_from)
    if created_to is not None:
        criterion.append(ActivationKey.created_at <= created_to)
    total = session.exec(select(func.count()).select_from(ActivationKey).where(*criterion)).one()
    rows = session.exec(select(ActivationKey).where(*criterion).order_by(
        ActivationKey.created_at.desc(), ActivationKey.id,
    ).offset((page - 1) * page_size).limit(page_size)).all()
    return ListChannelInventory(items=[ChannelInventoryItem(
        id=row.id, batch_id=row.batch_id, key=decrypt_key(row.key_ciphertext),
        recoverable=row.key_ciphertext is not None,
        tenant_id=row.tenant_id, hardware_model_id=row.hardware_model_id,
        created_at=row.created_at, used_at=row.used_at,
        used_terminal_id=row.used_terminal_id,
        is_assigned=row.tenant_id is not None,
        is_used=row.used_at is not None, status=_key_status(row),
    ) for row in rows], total=total)


@router.get("/channel-workspace/keys", response_model=ListChannelInventory)
def channel_inventory(
    session: SessionDep, principal: CurrentPrincipal,
    batch_id: uuid.UUID | None = None, page: int = 1, page_size: int = 100,
    created_from: datetime | None = None, created_to: datetime | None = None,
) -> ListChannelInventory:
    binding = _channel_admin(session, principal)
    return _inventory(session, binding.channel_id, batch_id, page, page_size, created_from, created_to)


@router.get(
    "/channels/{channel_id}/keys",
    dependencies=[Depends(require_module_access("esop", "esop:channel:admin"))],
    response_model=ListChannelInventory,
)
def admin_channel_inventory(
    session: SessionDep, principal: CurrentPrincipal, channel_id: uuid.UUID,
    batch_id: uuid.UUID | None = None, page: int = 1, page_size: int = 100,
    created_from: datetime | None = None, created_to: datetime | None = None,
) -> ListChannelInventory:
    _superuser(principal)
    _channel(session, channel_id)
    return _inventory(session, channel_id, batch_id, page, page_size, created_from, created_to)


def _batches(session: SessionDep, channel_id: uuid.UUID) -> ListBatchSummaries:
    rows = session.exec(select(
        ActivationKey.batch_id,
        func.count(ActivationKey.id),
        func.sum(case((ActivationKey.tenant_id.is_not(None), 1), else_=0)),
        func.sum(case((ActivationKey.used_at.is_not(None), 1), else_=0)),
        func.min(ActivationKey.created_at),
    ).where(
        ActivationKey.channel_id == channel_id,
        ActivationKey.batch_id.is_not(None),
    ).group_by(ActivationKey.batch_id).order_by(
        func.min(ActivationKey.created_at).desc(),
    )).all()
    items = [BatchSummary(
        batch_id=batch_id, quantity=quantity,
        assigned_count=assigned_count, activated_count=activated_count,
        created_at=created_at,
    ) for batch_id, quantity, assigned_count, activated_count, created_at in rows]
    return ListBatchSummaries(items=items, total=len(items))


@router.get("/channel-workspace/keys/batches", response_model=ListBatchSummaries)
def channel_batches(session: SessionDep, principal: CurrentPrincipal) -> ListBatchSummaries:
    return _batches(session, _channel_admin(session, principal).channel_id)


@router.get(
    "/channels/{channel_id}/keys/batches",
    dependencies=[Depends(require_module_access("esop", "esop:channel:admin"))],
    response_model=ListBatchSummaries,
)
def admin_channel_batches(
    session: SessionDep, principal: CurrentPrincipal, channel_id: uuid.UUID,
) -> ListBatchSummaries:
    _superuser(principal)
    _channel(session, channel_id)
    return _batches(session, channel_id)


def _export_keys(
    session: SessionDep, channel_id: uuid.UUID, body: KeyExportInput, timezone: ZoneInfo,
) -> StreamingResponse:
    if body.batch_id is None and not body.key_ids:
        raise HTTPException(status_code=422, detail="Batch or key IDs required")
    if body.key_ids and len(set(body.key_ids)) != len(body.key_ids):
        raise HTTPException(status_code=422, detail="Duplicate key IDs")
    statement = select(ActivationKey).where(ActivationKey.channel_id == channel_id)
    if body.batch_id is not None:
        statement = statement.where(ActivationKey.batch_id == body.batch_id)
    if body.key_ids:
        statement = statement.where(ActivationKey.id.in_(body.key_ids))
    rows = session.exec(statement.order_by(ActivationKey.created_at, ActivationKey.id).limit(1001)).all()
    if len(rows) > 1000:
        raise HTTPException(status_code=422, detail="Export is limited to 1000 keys")
    if body.key_ids and len(rows) != len(body.key_ids):
        raise HTTPException(status_code=404, detail="Selected keys not found in this channel")
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "密钥编号", "批次编号", "密钥", "是否可回读", "租户编号", "硬件型号编号",
        "状态", "创建时间", "激活时间", "使用终端编号",
    ])
    for row in rows:
        writer.writerow([
            row.id, row.batch_id or "", decrypt_key(row.key_ciphertext) or "",
            row.key_ciphertext is not None, row.tenant_id or "",
            row.hardware_model_id or "", _key_status(row), export_datetime(row.created_at, timezone),
            export_datetime(row.used_at, timezone), row.used_terminal_id or "",
        ])
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('渠道密钥.csv')}"},
    )


@router.post("/channel-workspace/keys/export", response_model=None)
def export_channel_inventory(
    session: SessionDep, principal: CurrentPrincipal, body: KeyExportInput,
    x_export_timezone: ExportTimezoneHeader = None,
) -> StreamingResponse:
    return _export_keys(session, _channel_admin(session, principal).channel_id, body, export_timezone(x_export_timezone))


@router.post(
    "/channels/{channel_id}/keys/export",
    dependencies=[Depends(require_module_access("esop", "esop:channel:admin"))],
    response_model=None,
)
def admin_export_channel_inventory(
    session: SessionDep, principal: CurrentPrincipal,
    channel_id: uuid.UUID, body: KeyExportInput,
    x_export_timezone: ExportTimezoneHeader = None,
) -> StreamingResponse:
    _superuser(principal)
    _channel(session, channel_id)
    return _export_keys(session, channel_id, body, export_timezone(x_export_timezone))


@router.get("/channel-workspace/customers", response_model=ListChannelCustomers)
def channel_customers(session: SessionDep, principal: CurrentPrincipal) -> ListChannelCustomers:
    binding = _channel_admin(session, principal)
    mappings = session.exec(select(ChannelCustomerTenant).where(
        ChannelCustomerTenant.channel_id == binding.channel_id,
    )).all()
    summaries = get_channel_customer_tenants(
        session=session, tenant_ids=[row.tenant_id for row in mappings],
    )
    created_at_by_tenant = {row.tenant_id: row.created_at for row in mappings}
    items = [CustomerPublic(tenant_id=item.id, tenant_code=item.code, tenant_name=item.name,
                            created_at=created_at_by_tenant[item.id]) for item in summaries]
    return ListChannelCustomers(items=items, total=len(items))


@router.post("/channel-workspace/customers", response_model=CustomerPublic)
def create_channel_customer(
    session: SessionDep, principal: CurrentPrincipal, body: CustomerInput,
) -> CustomerPublic:
    binding = _channel_admin(session, principal)
    customer = create_channel_customer_tenant(
        session=session, channel_admin_user_id=principal.id,
        customer_name=body.name, customer_code=body.code or generate_entity_code("TEN"),
    )
    mapping = ChannelCustomerTenant(
        channel_id=binding.channel_id, tenant_id=customer.id,
        created_by=principal.id,
    )
    session.add(mapping)
    session.commit()
    return CustomerPublic(tenant_id=customer.id, tenant_code=customer.code, tenant_name=customer.name,
                          created_at=mapping.created_at)


@router.post("/channel-workspace/keys/assign", response_model=KeyAssignResult)
def assign_channel_keys(
    session: SessionDep, principal: CurrentPrincipal, body: KeyAssignInput,
) -> KeyAssignResult:
    binding = _channel_admin(session, principal)
    if len(set(body.key_ids)) != len(body.key_ids):
        raise HTTPException(status_code=422, detail="Duplicate key IDs")
    customer = session.exec(select(ChannelCustomerTenant.id).where(
        ChannelCustomerTenant.channel_id == binding.channel_id,
        ChannelCustomerTenant.tenant_id == body.tenant_id,
    )).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Channel customer tenant not found")
    keys = session.exec(select(ActivationKey).where(
        ActivationKey.id.in_(body.key_ids),
    ).order_by(ActivationKey.id).with_for_update()).all()
    if len(keys) != len(body.key_ids) or any(
        row.channel_id != binding.channel_id or row.batch_id is None
        or row.used_at is not None or row.tenant_id not in (None, body.tenant_id)
        for row in keys
    ):
        raise HTTPException(status_code=409, detail="Key is unavailable for this channel customer")
    for row in keys:
        row.tenant_id = body.tenant_id
        session.add(row)
    session.commit()
    return KeyAssignResult(assigned_count=len(keys))
