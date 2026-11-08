"""Create a customer tenant for an already authorized channel administrator."""

import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass

from fastapi import HTTPException
from sqlmodel import Session, select

from app.platform.bootstrap_rbac import provision_tenant_roles
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import (
    Tenant,
    TenantInitializationTemplate,
    TenantPlan,
)


@dataclass(frozen=True)
class TenantSummary:
    id: uuid.UUID
    code: str
    name: str


def get_channel_customer_tenants(
    *, session: Session, tenant_ids: Collection[uuid.UUID],
) -> list[TenantSummary]:
    if not tenant_ids:
        return []
    tenants = session.exec(select(Tenant).where(Tenant.id.in_(tenant_ids))).all()
    return [TenantSummary(id=tenant.id, code=tenant.code, name=tenant.name) for tenant in tenants]


def create_channel_customer_tenant(
    *, session: Session, channel_admin_user_id: uuid.UUID,
    customer_name: str, customer_code: str,
) -> TenantSummary:
    code = customer_code.strip().lower()
    name = customer_name.strip()
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,31}", code) or not 2 <= len(name) <= 100:
        raise HTTPException(status_code=422, detail="Invalid customer tenant")
    owner = session.get(User, channel_admin_user_id)
    if owner is None or not owner.is_active:
        raise HTTPException(status_code=403, detail="Channel administrator is inactive")
    if session.exec(select(Tenant.id).where(Tenant.code == code)).first():
        raise HTTPException(status_code=409, detail="Tenant code already exists")
    plan = session.exec(select(TenantPlan).where(TenantPlan.is_default, TenantPlan.is_active)).first()
    template = session.exec(select(TenantInitializationTemplate).where(
        TenantInitializationTemplate.is_default,
        TenantInitializationTemplate.is_active,
    )).first()
    if plan is None or template is None:
        raise HTTPException(status_code=503, detail="Tenant provisioning is not configured")

    from app.modules.tenant_initialization import (
        initialize_tenant_modules,
        prepare_tenant_creation,
    )

    prepare_tenant_creation(session=session)
    tenant = Tenant(
        code=code, name=name, plan_id=plan.id,
        initialization_template_id=template.id, is_active=True,
    )
    session.add(tenant)
    session.flush()
    provision_tenant_roles(
        session=session, tenant=tenant, template=template, owner=owner,
    )
    initialize_tenant_modules(session=session, tenant_id=tenant.id)
    from app.platform.storage_provisioning import ensure_esop_storage_account

    ensure_esop_storage_account(session=session, tenant_id=tenant.id)
    session.flush()
    return TenantSummary(id=tenant.id, code=tenant.code, name=tenant.name)


def resolve_channel_customer_code(*, session: Session, code: str) -> TenantSummary:
    tenant = session.exec(select(Tenant).where(Tenant.code == code.strip().lower(), Tenant.is_active).with_for_update()).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Active customer tenant not found")
    return TenantSummary(id=tenant.id, code=tenant.code, name=tenant.name)
