"""Batch role assignment must preserve tenant and plan authority."""

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.api.routes.menus import read_available_role_menus
from app.core.tenancy import TenantContext
from app.platform.core.authorization_models import Menu, Role, RoleMenu, UserRole
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import Tenant, TenantPlan, TenantPlanMenu
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)
from app.platform.tenant_uow import activate_platform_tenant_scope


def test_available_menus_batch_and_authority():
    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine, expire_on_commit=False) as session:
        plan = TenantPlan(code="test", name="Test")
        tenant = Tenant(code="test", name="Test", plan_id=plan.id)
        other = Tenant(code="other", name="Other", plan_id=plan.id)
        user = User(email="test@example.com", hashed_password="unused")
        role = Role(code="admin", name="Admin", tenant_id=tenant.id)
        foreign = Role(code="admin", name="Other", tenant_id=other.id)
        root = Menu(title="System", type="directory")
        codes = ["system:role:list", *(f"system:role:action{i}" for i in range(100))]
        menus = [
            Menu(title=code, parent_id=root.id, permission_code=code) for code in codes
        ]
        denied = Menu(
            title="Not owned", parent_id=root.id, permission_code="system:role:delete"
        )
        platform = Menu(title="Platform", permission_code="system:menu:list")
        session.add_all(
            [plan, tenant, other, user, role, foreign, root, *menus, denied, platform]
        )
        session.flush()
        for menu in [root, *menus, denied, platform]:
            session.add(TenantPlanMenu(plan_id=plan.id, menu_id=menu.id))
        for menu in menus:
            session.add(RoleMenu(role_id=role.id, menu_id=menu.id))
        session.add(RoleMenu(role_id=foreign.id, menu_id=denied.id))
        session.add(UserRole(user_id=user.id, role_id=role.id, tenant_id=tenant.id))
        session.add(UserRole(user_id=user.id, role_id=foreign.id, tenant_id=other.id))
        session.commit()
        activate_platform_tenant_scope(session, tenant.id)
        queries = []
        event.listen(
            engine, "before_cursor_execute", lambda *args: queries.append(args[2])
        )
        result = read_available_role_menus(
            session=session,
            current_user=user,
            tenant_context=TenantContext(
                tenant_id=tenant.id, tenant_code=tenant.code, user_id=user.id
            ),
        )
        assert {menu.id for menu in result} == {root.id, *(menu.id for menu in menus)}
        assert len(queries) < 15, len(queries)
