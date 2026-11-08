"""Role authorization only exposes effective tenant package menus."""

import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.deps import grantable_tenant_menus
from app.api.routes.menus import read_available_role_menus
from app.api.routes.roles import read_role_menus, update_role_menus
from app.core.config import settings
from app.core.database import engine
from app.core.tenancy import TenantContext
from app.platform.core.authorization_models import (
    Menu,
    Role,
    RoleMenu,
    RoleMenuUpdate,
    UserRole,
)
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import Tenant
from app.platform.tenant_uow import PlatformTenantUnitOfWork


def test_role_menu_tree_and_save_follow_effective_package() -> None:
    assert settings.DATABASE_TYPE == "mysql" and settings.MYSQL_DB == "esop_fva_test_20261024"
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                tenant = session.exec(select(Tenant).where(Tenant.code == "test")).one()
                platform_admin = session.exec(select(User).where(User.is_superuser)).first()
                assert platform_admin is not None
                context = TenantContext(tenant_id=tenant.id, tenant_code=tenant.code, user_id=platform_admin.id)
                with PlatformTenantUnitOfWork(session, tenant.id):
                    menus = grantable_tenant_menus(session, tenant.id)
                    available = read_available_role_menus(session, platform_admin, context)
                    assert {menu.id for menu in available} == {menu.id for menu in menus}
                    assert not any((menu.permission_code or "").startswith("platform:") for menu in available)
                    assert not any(menu.type == "directory" and menu.id not in {item.parent_id for item in available} for menu in available)

                    tenant_admin = session.exec(
                        select(User)
                        .join(UserRole, UserRole.user_id == User.id)
                        .join(Role, Role.id == UserRole.role_id)
                        .where(UserRole.tenant_id == tenant.id, Role.code == "super_admin", User.is_superuser.is_(False))
                    ).first()
                    assert tenant_admin is not None
                    tenant_context = TenantContext(tenant_id=tenant.id, tenant_code=tenant.code, user_id=tenant_admin.id)
                    tenant_available = read_available_role_menus(session, tenant_admin, tenant_context)
                    assert {menu.id for menu in tenant_available} <= {menu.id for menu in available}
                    assert any(menu.permission_code == "system:role:list" for menu in tenant_available)
                    assert not any((menu.permission_code or "").startswith("platform:") for menu in tenant_available)

                    disabled = session.exec(select(Menu).where(Menu.permission_code == "business:item:list")).one()
                    assert disabled.id not in {menu.id for menu in available}
                    role = Role(tenant_id=tenant.id, code=f"menu_test_{uuid.uuid4().hex[:10]}", name="Menu test")
                    session.add(role)
                    session.flush()
                    session.add(RoleMenu(role_id=role.id, menu_id=disabled.id))
                    session.flush()
                    assert read_role_menus(session=session, tenant_context=context, role_id=role.id) == []
                    with pytest.raises(HTTPException) as rejected:
                        update_role_menus(
                            session=session,
                            tenant_context=context,
                            current_user=platform_admin,
                            role_id=role.id,
                            body=RoleMenuUpdate(menu_ids=[disabled.id]),
                        )
                    assert rejected.value.status_code == 403
        finally:
            outer.rollback()
