import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, delete

from app.api.deps import get_platform_read_tenant, user_has_permission
from app.core.tenancy import TenantContext
from app.platform.core.authorization_models import Menu, Role, RoleMenu, UserRole
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import Tenant, TenantPlan, TenantPlanMenu
from app.platform.core.tenant_menu_access import tenant_plan_menu_ids
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)


@pytest.mark.parametrize(
    "permission",
    [
        "system:user:list",
        "system:role:list",
        "system:department:list",
        "system:department:create",
        "system:post:list",
        "system:post:update",
        "system:login-log:list",
        "system:operation-log:list",
    ],
)
def test_plan_ceiling_applies_immediately_and_blocks_platform_metadata(permission):
    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine) as session:
        plan = TenantPlan(code="test", name="Test")
        session.add(plan)
        session.flush()
        tenant = Tenant(code="test", name="Test", plan_id=plan.id)
        user = User(email="tenant@example.com", hashed_password="unused")
        role = Role(code="tenant", name="Tenant", tenant_id=tenant.id)
        allowed = Menu(title="Tenant administration", permission_code=permission)
        platform = Menu(title="Menus", permission_code="system:menu:list")
        session.add_all([tenant, user, role, allowed, platform])
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id, tenant_id=tenant.id))
        for menu in (allowed, platform):
            session.add(TenantPlanMenu(plan_id=plan.id, menu_id=menu.id))
            session.add(RoleMenu(role_id=role.id, menu_id=menu.id))
        session.commit()
        assert allowed.id in tenant_plan_menu_ids(session, tenant.id)
        assert platform.id not in tenant_plan_menu_ids(session, tenant.id)
        assert user_has_permission(
            session=session,
            current_user=user,
            tenant_id=tenant.id,
            permission_code=permission,
        )
        assert not user_has_permission(
            session=session,
            current_user=user,
            tenant_id=tenant.id,
            permission_code="system:menu:list",
        )
        session.exec(delete(TenantPlanMenu).where(TenantPlanMenu.menu_id == allowed.id))
        session.commit()
        assert not user_has_permission(
            session=session,
            current_user=user,
            tenant_id=tenant.id,
            permission_code=permission,
        )
        root = User(
            email="root@example.com", hashed_password="unused", is_superuser=True
        )
        assert user_has_permission(
            session=session,
            current_user=root,
            tenant_id=tenant.id,
            permission_code="system:menu:list",
        )


def test_global_read_scope_requires_root_and_restores_parent():
    engine = create_engine("sqlite://")
    tenant_id = uuid.uuid4()
    context = TenantContext(
        tenant_id=tenant_id, tenant_code="test", user_id=uuid.uuid4()
    )
    with Session(engine) as session:
        session.info["platform_tenant_id"] = tenant_id
        root = User(
            email="root@example.com", hashed_password="unused", is_superuser=True
        )
        scope = get_platform_read_tenant(session, root, context, None)
        assert next(scope) is None
        assert session.info["platform_global_scope"]
        with pytest.raises(StopIteration):
            next(scope)
        assert session.info["platform_tenant_id"] == tenant_id
        assert not session.info.get("platform_global_scope")
        tenant_user = User(email="tenant@example.com", hashed_password="unused")
        denied = get_platform_read_tenant(session, tenant_user, context, uuid.uuid4())
        with pytest.raises(HTTPException) as error:
            next(denied)
        assert error.value.status_code == 403


def test_jwt_subject_is_validated_uuid_before_database_lookup():
    from app.api.deps import get_user_from_token_payload
    from app.models import TokenPayload

    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    with Session(engine) as session:
        for subject, status in [("invalid-subject", 403), (str(uuid.uuid4()), 404)]:
            payload = TokenPayload(sub=subject, jti="fixture", tenant_id=uuid.uuid4())
            with pytest.raises(HTTPException) as error:
                get_user_from_token_payload(session=session, token_data=payload)
            assert error.value.status_code == status


def test_unbundled_module_directories_disappear_after_leaf_filtering():
    from app.api.routes.menus import prune_empty_directories
    from app.platform.core.authorization_models import MenuPublic

    root_id, child_id, page_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    root = MenuPublic(id=root_id, title="ERP", type="directory")
    child = MenuPublic(
        id=child_id, title="ERP child", type="directory", parent_id=root_id
    )
    dashboard = MenuPublic(id=page_id, title="Dashboard", type="menu")
    assert prune_empty_directories([root, child, dashboard]) == [dashboard]


@pytest.mark.parametrize(
    "permission",
    [
        "personal:message:list",
        "system:notice:list",
        "system:site-message-template:send",
        "system:site-message:list",
        "system:sms-channel:list",
        "system:mail-account:list",
        "system:menu:list",
        "platform:tenant:list",
    ],
)
def test_platform_only_permissions_cannot_be_granted_to_tenants(permission):
    from app.platform.core.tenant_menu_access import tenant_permission_allowed

    assert not tenant_permission_allowed(permission)
