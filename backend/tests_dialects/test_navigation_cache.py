"""Cache hits must observe live authorization, including missed Redis bumps."""

import copy

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, delete

from app.api.routes import menus
from app.core.tenancy import TenantContext
from app.platform.core.authorization_models import Menu, Role, RoleMenu, UserRole
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import Tenant, TenantPlan, TenantPlanMenu
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.hits = 0
        self.offline = False

    def build_versioned_key(self, *parts):
        return ":".join(map(str, parts))

    def get_json(self, key):
        if self.offline:
            return None
        value = self.values.get(key)
        if value is not None:
            self.hits += 1
        return copy.deepcopy(value)

    def set_json(self, key, value):
        if not self.offline:
            self.values[key] = copy.deepcopy(value)


@pytest.fixture
def navigation(monkeypatch):
    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    cache = MemoryRedis()
    denied = set()
    monkeypatch.setattr(menus, "redis_cache", cache)
    monkeypatch.setattr(
        menus,
        "filter_module_scoped_permissions",
        lambda **kw: [c for c in kw["permission_codes"] if c not in denied],
    )
    monkeypatch.setattr(
        menus,
        "filter_user_menu_permissions",
        lambda **kw: kw["permission_codes"] - denied,
    )
    with Session(engine, expire_on_commit=False) as s:
        plan = TenantPlan(code="nav", name="Nav")
        tenant = Tenant(code="nav", name="Nav", plan_id=plan.id)
        other = Tenant(code="other", name="Other", plan_id=plan.id)
        user = User(email="nav@example.com", hashed_password="unused")
        stranger = User(email="stranger@example.com", hashed_password="unused")
        role = Role(tenant_id=tenant.id, code="admin", name="Admin")
        root = Menu(title="System", type="directory", route_path="/system")
        leaf = Menu(
            title="Users",
            parent_id=root.id,
            permission_code="system:user:list",
            route_path="/system/users",
        )
        button = Menu(
            title="Create",
            parent_id=leaf.id,
            permission_code="system:user:create",
            type="button",
            is_visible=False,
        )
        s.add_all([plan, tenant, other, user, stranger, role, root, leaf, button])
        s.flush()
        for menu in (root, leaf, button):
            s.add_all(
                [
                    RoleMenu(role_id=role.id, menu_id=menu.id),
                    TenantPlanMenu(plan_id=plan.id, menu_id=menu.id),
                ]
            )
        s.add(UserRole(tenant_id=tenant.id, role_id=role.id, user_id=user.id))
        s.commit()
        context = TenantContext(
            tenant_id=tenant.id, tenant_code=tenant.code, user_id=user.id
        )
        yield (
            s,
            user,
            context,
            cache,
            denied,
            role,
            plan,
            root,
            leaf,
            button,
            other,
            stranger,
        )


def query(data, permissions=False):
    return (menus.read_my_permissions if permissions else menus.read_my_menus)(
        session=data[0], current_user=data[1], tenant_context=data[2]
    )


def test_warm_tenant_cache_uses_one_sql_snapshot(navigation):
    query(navigation)
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(navigation[0].bind, "before_cursor_execute", record)
    try:
        result = query(navigation)
        assert len(statements) == 1
        assert navigation[3].hits == 1
        assert {row.route_path for row in result} == {"/system", "/system/users"}
    finally:
        event.remove(navigation[0].bind, "before_cursor_execute", record)


@pytest.mark.parametrize(
    "change",
    [
        "role_binding",
        "role_menus",
        "role_disabled",
        "plan_binding",
        "plan_disabled",
        "menu_disabled",
        "parent_cycle",
    ],
)
@pytest.mark.parametrize("permissions", [False, True])
def test_revocation_is_immediate_without_namespace_bump(
    navigation, change, permissions
):
    s, user, _, _, _, role, plan, root, leaf, *_ = navigation
    assert query(navigation, permissions)
    if change == "role_binding":
        s.exec(delete(UserRole).where(UserRole.user_id == user.id))
    elif change == "role_menus":
        s.exec(delete(RoleMenu).where(RoleMenu.role_id == role.id))
    elif change == "role_disabled":
        role.is_active = False
    elif change == "plan_binding":
        s.exec(delete(TenantPlanMenu).where(TenantPlanMenu.menu_id == root.id))
    elif change == "plan_disabled":
        plan.is_active = False
    elif change == "menu_disabled":
        leaf.is_active = False
    else:
        root.parent_id = leaf.id
    s.commit()
    assert query(navigation, permissions) == []


def test_menu_content_and_dynamic_visibility_are_fresh(navigation):
    query(navigation)
    leaf = navigation[8]
    leaf.title = "Renamed"
    navigation[0].commit()
    assert any(row.title == "Renamed" for row in query(navigation))
    navigation[4].add("system:user:list")
    assert query(navigation) == []
    navigation[4].clear()
    assert query(navigation)


def test_cache_is_isolated_by_tenant_and_user_and_fails_to_db(navigation):
    query(navigation)
    s, user, context, cache, *_ = navigation
    other, stranger = navigation[-2:]
    assert (
        menus.read_my_menus(session=s, current_user=stranger, tenant_context=context)
        == []
    )
    foreign = TenantContext(tenant_id=other.id, tenant_code=other.code, user_id=user.id)
    assert (
        menus.read_my_menus(session=s, current_user=user, tenant_context=foreign) == []
    )
    cache.offline = True
    assert query(navigation)
    navigation[5].is_active = False
    s.commit()
    assert query(navigation) == []
