import uuid

from fastapi import HTTPException
from sqlmodel import Session, func, select

from app.platform.core.esop_commercial import esop_storage_limit
from app.platform.core.esop_commercial_models import EsopTenantStorage
from app.platform.core.tenancy_models import Tenant, TenantMembership, TenantPlan
from app.platform.infra.file_models import FileAsset


def get_tenant_plan(*, session: Session, tenant_id: uuid.UUID) -> TenantPlan:
    plan = session.exec(
        select(TenantPlan)
        .join(Tenant, Tenant.plan_id == TenantPlan.id)
        .where(Tenant.id == tenant_id)
    ).first()
    if plan is None:
        raise HTTPException(status_code=409, detail="Tenant plan is not configured")
    return plan


def get_member_count(*, session: Session, tenant_id: uuid.UUID) -> int:
    return session.exec(
        select(func.count())
        .select_from(TenantMembership)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.is_active,
        )
    ).one()


def get_file_usage(*, session: Session, tenant_id: uuid.UUID, current_read: bool = False) -> tuple[int, int]:
    statement = (
        select(func.count(), func.coalesce(func.sum(FileAsset.size), 0)).where(
            FileAsset.tenant_id == tenant_id
        )
    )
    if current_read and session.get_bind().dialect.name == "mysql":
        # A locking read bypasses a previously established MySQL RR snapshot.
        statement = statement.with_for_update()
    count, storage_bytes = session.exec(statement).one()
    return count, storage_bytes


def ensure_member_quota(*, session: Session, tenant_id: uuid.UUID) -> None:
    plan = get_tenant_plan(session=session, tenant_id=tenant_id)
    if plan.max_members is None:
        return
    if get_member_count(session=session, tenant_id=tenant_id) >= plan.max_members:
        raise HTTPException(status_code=409, detail="Tenant member quota exceeded")


def ensure_file_quota(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    incoming_size: int,
    current_read: bool = False,
) -> None:
    plan = get_tenant_plan(session=session, tenant_id=tenant_id)
    file_assets, storage_bytes = get_file_usage(
        session=session,
        tenant_id=tenant_id, current_read=current_read,
    )
    if plan.max_file_assets is not None and file_assets >= plan.max_file_assets:
        raise HTTPException(status_code=409, detail="Tenant file quota exceeded")
    storage_limit = get_storage_limit(session=session, tenant_id=tenant_id, plan=plan)
    if storage_limit is not None and storage_bytes + incoming_size > storage_limit:
        raise HTTPException(status_code=409, detail="Tenant storage quota exceeded")


def get_storage_limit(*, session: Session, tenant_id: uuid.UUID, plan: TenantPlan | None = None) -> int | None:
    esop_account = session.get(EsopTenantStorage, tenant_id)
    if esop_account is not None:
        base_bytes, grant_bytes = esop_storage_limit(session=session, tenant_id=tenant_id)
        storage_limit = base_bytes + grant_bytes
    else:
        storage_limit = (plan or get_tenant_plan(session=session, tenant_id=tenant_id)).max_storage_bytes
    return storage_limit
