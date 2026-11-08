"""ESOP tenant storage entitlements, kept separate from edition plan ceilings."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import case
from sqlmodel import Session, func, or_, select

from app.core.clock import get_datetime_utc
from app.platform.core.esop_commercial_models import EsopStorageGrant, EsopTenantStorage
from app.platform.core.tenancy_models import Tenant

MIB = 1024 * 1024
REGISTERED_BYTES = 100 * MIB
CERTIFIED_BYTES = 1024 * MIB


def ensure_esop_storage_account(*, session: Session, tenant_id: uuid.UUID, initial_bytes: int = REGISTERED_BYTES) -> EsopTenantStorage:
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    account = session.get(EsopTenantStorage, tenant_id)
    if account is None:
        account = EsopTenantStorage(tenant_id=tenant_id, base_bytes=initial_bytes)
        session.add(account)
        session.add(EsopStorageGrant(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"esop-storage-opening:{tenant_id}"),
            tenant_id=tenant_id,
            capacity_bytes=initial_bytes,
            source="opening_gift",
            starts_at=get_datetime_utc(),
            expires_at=None,
            note="开户赠送",
        ))
        session.flush()
    return account


def certify_esop_tenant(*, session: Session, tenant_id: uuid.UUID) -> EsopTenantStorage:
    account = ensure_esop_storage_account(session=session, tenant_id=tenant_id)
    if account.certified_at is None:
        account.certified_at = get_datetime_utc()
        session.add(account)
    return account


def ensure_paid_activation_storage(
    *, session: Session, tenant_id: uuid.UUID
) -> EsopTenantStorage:
    return ensure_esop_storage_account(session=session, tenant_id=tenant_id)


def esop_storage_limit(*, session: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> tuple[int, int]:
    account = session.get(EsopTenantStorage, tenant_id)
    if account is None:
        return 0, 0
    current = now or get_datetime_utc()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    base, active = session.exec(
        select(
            func.coalesce(func.sum(case((EsopStorageGrant.source == "opening_gift", EsopStorageGrant.capacity_bytes), else_=0)), 0),
            func.coalesce(func.sum(case((EsopStorageGrant.source == "expansion", EsopStorageGrant.capacity_bytes), else_=0)), 0),
        ).where(
            EsopStorageGrant.tenant_id == tenant_id,
            EsopStorageGrant.starts_at <= current,
            or_(EsopStorageGrant.expires_at.is_(None), EsopStorageGrant.expires_at > current),
        )
    ).one()
    return int(base), int(active)
