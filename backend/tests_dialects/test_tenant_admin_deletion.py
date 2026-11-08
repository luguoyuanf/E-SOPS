import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.api.routes.users import delete_user
from app.core.config import settings
from app.core.tenancy import TenantContext
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.platform.core.authorization_models import Role, UserRole
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import Tenant, TenantMembership, TenantProfile
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)


def test_tenant_admin_protected_and_other_members_removable():
    from app.modules.esop.infrastructure.models import ChannelAdmin
    import_platform_model_groups()
    engine = create_engine('sqlite://')
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(engine, tables=[SQLModel.metadata.tables[name] for name in names] + [ChannelAdmin.__table__])
    with Session(engine) as session:
        tenant = Tenant(code='business', name='Business')
        platform = Tenant(id=DEFAULT_TENANT_ID, code='default', name='Platform')
        other_tenant = Tenant(code='other', name='Other')
        root = User(email=str(settings.FIRST_SUPERUSER), hashed_password='unused', is_superuser=True)
        admin = User(email='admin@example.org', hashed_password='unused')
        colleague = User(email='colleague@example.org', hashed_password='unused')
        outsider = User(email='outside@example.org', hashed_password='unused')
        role = Role(tenant_id=tenant.id, code='super_admin', name='Admin', data_scope='all')
        session.add_all([platform, tenant, other_tenant, root, admin, colleague, outsider, role])
        session.flush()
        session.add_all([
            TenantProfile(tenant_id=tenant.id, contact_user_id=admin.id),
            TenantMembership(user_id=root.id, tenant_id=platform.id, is_default=True),
            TenantMembership(user_id=root.id, tenant_id=tenant.id),
            TenantMembership(user_id=admin.id, tenant_id=tenant.id),
            TenantMembership(user_id=colleague.id, tenant_id=tenant.id),
            TenantMembership(user_id=outsider.id, tenant_id=other_tenant.id),
            UserRole(user_id=admin.id, role_id=role.id, tenant_id=tenant.id),
        ])
        session.commit()
        session.info['platform_tenant_id'] = tenant.id
        ctx = TenantContext(tenant_id=tenant.id, tenant_code=tenant.code, user_id=admin.id)
        with pytest.raises(HTTPException) as protected:
            delete_user(session=session, current_user=admin, tenant_context=ctx, user_id=admin.id)
        assert protected.value.status_code == 403
        with pytest.raises(HTTPException) as cross_tenant:
            delete_user(session=session, current_user=admin, tenant_context=ctx, user_id=outsider.id)
        assert cross_tenant.value.status_code == 404
        with pytest.raises(HTTPException) as protected_root:
            delete_user(session=session, current_user=admin, tenant_context=ctx, user_id=root.id)
        assert protected_root.value.status_code == 403
        root_ctx = TenantContext(tenant_id=tenant.id, tenant_code=tenant.code, user_id=root.id)
        with pytest.raises(HTTPException) as protected_admin:
            delete_user(session=session, current_user=root, tenant_context=root_ctx, user_id=admin.id)
        assert protected_admin.value.status_code == 403
        assert session.get(User, root.id).is_active
        assert session.get(User, admin.id).is_active
        delete_user(session=session, current_user=admin, tenant_context=ctx, user_id=colleague.id)
        assert not session.get(User, colleague.id).is_active
