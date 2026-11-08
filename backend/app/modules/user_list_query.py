"""Compose platform user protection with bundled module bindings."""

from sqlalchemy import and_, exists, or_
from sqlmodel import select

from app.modules.access import get_runtime_manifest
from app.platform.core.authorization_models import Role, UserRole
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import TenantProfile


def deletion_protected_expression():
    conditions = [
        User.is_superuser,
        exists(select(TenantProfile.contact_user_id).where(TenantProfile.contact_user_id == User.id)),
        exists(select(UserRole.user_id).join(Role, and_(
            Role.id == UserRole.role_id, Role.tenant_id == UserRole.tenant_id,
        )).where(UserRole.user_id == User.id, Role.is_system,
                 Role.code.in_(["super_admin", "admin"]))),
    ]
    if any(module.code == "esop" for module in get_runtime_manifest().modules):
        from app.modules.esop.infrastructure.models import ChannelAdmin

        conditions.append(exists(select(ChannelAdmin.id).where(ChannelAdmin.user_id == User.id)))
    return or_(*conditions)
