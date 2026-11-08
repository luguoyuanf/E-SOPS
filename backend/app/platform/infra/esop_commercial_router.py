"""Platform-superuser operations for ESOP storage grants."""

import uuid
from datetime import UTC, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_superuser
from app.core.quotas import get_file_usage
from app.platform.core.esop_commercial import (
    certify_esop_tenant,
    esop_storage_limit,
)
from app.platform.core.esop_commercial_models import (
    EsopStorageDefault,
    EsopStorageGrant,
    EsopStorageGrantCreate,
    EsopStorageGrantPublic,
    EsopStorageGrantsPublic,
    EsopStorageUsagePublic,
)
from app.platform.core.tenancy_models import Tenant
from app.platform.storage_provisioning import (
    ensure_esop_storage_account,
    read_storage_default,
    save_storage_default,
)

router = APIRouter(
    prefix="/esop",
    tags=["esop-commercial"],
    dependencies=[Depends(get_current_active_superuser)],
)


def require_tenant(session: SessionDep, tenant_id: uuid.UUID) -> None:
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")


@router.get("/storage-default", response_model=EsopStorageDefault)
def get_storage_default(session: SessionDep) -> EsopStorageDefault:
    return read_storage_default(session=session)


@router.put("/storage-default", response_model=EsopStorageDefault)
def update_storage_default(session: SessionDep, body: EsopStorageDefault) -> EsopStorageDefault:
    save_storage_default(session=session, body=body)
    session.commit()
    return body


@router.get("/storage-grants", response_model=EsopStorageGrantsPublic)
def list_storage_grants(session: SessionDep, tenant_id: uuid.UUID) -> EsopStorageGrantsPublic:
    require_tenant(session, tenant_id)
    grants = session.exec(
        select(EsopStorageGrant)
        .where(EsopStorageGrant.tenant_id == tenant_id)
        .order_by(EsopStorageGrant.created_at.desc())
    ).all()
    return EsopStorageGrantsPublic(
        items=[EsopStorageGrantPublic.model_validate(grant, from_attributes=True) for grant in grants],
        total=len(grants),
    )


@router.post("/storage-grants", response_model=EsopStorageGrantPublic, status_code=201)
def create_storage_grant(session: SessionDep, body: EsopStorageGrantCreate) -> EsopStorageGrantPublic:
    ensure_esop_storage_account(session=session, tenant_id=body.tenant_id)
    if body.starts_at.tzinfo is None or body.expires_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Storage grant dates require timezone")
    starts_at = body.starts_at.astimezone(UTC)
    expires_at = body.expires_at.astimezone(UTC)
    term = expires_at - starts_at
    if term < timedelta(days=365) or term > timedelta(days=366):
        raise HTTPException(status_code=422, detail="Storage grants must cover one year")
    grant = EsopStorageGrant(
        tenant_id=body.tenant_id,
        capacity_bytes=body.capacity_bytes,
        starts_at=starts_at,
        expires_at=expires_at,
        note=body.note,
    )
    session.add(grant)
    session.commit()
    session.refresh(grant)
    return EsopStorageGrantPublic.model_validate(grant, from_attributes=True)


@router.get("/storage-usage", response_model=EsopStorageUsagePublic)
def read_storage_usage(session: SessionDep, tenant_id: uuid.UUID) -> EsopStorageUsagePublic:
    require_tenant(session, tenant_id)
    base_bytes, grant_bytes = esop_storage_limit(session=session, tenant_id=tenant_id)
    _, used_bytes = get_file_usage(session=session, tenant_id=tenant_id)
    return EsopStorageUsagePublic(
        tenant_id=tenant_id,
        base_bytes=base_bytes,
        active_grant_bytes=grant_bytes,
        limit_bytes=base_bytes + grant_bytes,
        used_bytes=used_bytes,
    )


@router.post("/tenants/{tenant_id}/certify", response_model=EsopStorageUsagePublic)
def certify_tenant(session: SessionDep, tenant_id: uuid.UUID) -> EsopStorageUsagePublic:
    ensure_esop_storage_account(session=session, tenant_id=tenant_id)
    certify_esop_tenant(session=session, tenant_id=tenant_id)
    session.commit()
    return read_storage_usage(session=session, tenant_id=tenant_id)
