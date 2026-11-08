from unittest.mock import MagicMock

from sqlmodel import Session, select

from app.core.cache import CacheNamespace, redis_cache
from app.core.database import engine
from app.platform.bootstrap import init_db
from app.platform.bootstrap_navigation import seed_menus
from app.platform.bootstrap_rbac import (
    bind_role_menus,
    ensure_default_tenant_plan_menus,
)
from app.platform.core.authorization_models import Menu, Role, RoleMenu
from app.platform.core.tenancy_models import (
    TenantInitializationTemplate,
    TenantPlan,
    TenantPlanMenu,
)
from app.platform.tenant_uow import PlatformGlobalUnitOfWork


def test_bootstrap_menu_bindings_deduplicate_repeated_menu_objects() -> None:
    session = MagicMock()
    session.exec.return_value.all.return_value = []
    menu = Menu(title="Shared permission", permission_code="example:read")
    plan = TenantPlan(code="default", name="Default", is_default=True)
    role = Role(code="admin", name="Admin")

    ensure_default_tenant_plan_menus(
        session=session,
        plan=plan,
        menus=[menu, menu],
    )

    plan_bindings = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], TenantPlanMenu)
    ]
    assert len(plan_bindings) == 1

    session.reset_mock()
    session.exec.return_value.all.return_value = []
    bind_role_menus(session=session, role=role, menus=[menu, menu])

    role_bindings = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], RoleMenu)
    ]
    assert len(role_bindings) == 1


def test_init_db_invalidates_access_caches(db, monkeypatch) -> None:
    invalidated: list[CacheNamespace] = []
    monkeypatch.setattr(redis_cache, "bump_namespace", invalidated.append)

    init_db(db)

    assert CacheNamespace.RBAC in invalidated
    assert CacheNamespace.MODULE_ACCESS in invalidated


def test_services_menu_is_nested_under_resources_without_reordering() -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                with PlatformGlobalUnitOfWork(session):
                    menus = {menu.route_path: menu for menu in seed_menus(session=session)}
                    resources = menus["/esop/resources"]
                    services = menus["/esop/services"]
                    original_id, original_sort = services.id, services.sort
                    services.parent_id = menus["/esop"].id
                    session.flush()

                    menus = {menu.route_path: menu for menu in seed_menus(session=session)}
                    services = menus["/esop/services"]
                    assert services.parent_id == resources.id
                    assert (services.id, services.sort) == (original_id, original_sort)
                    assert menus["/esop/services/activation-keys"].parent_id == services.id
                    assert menus["/esop/services/storage-grants"].parent_id == services.id
        finally:
            transaction.rollback()


def test_esop_menu_hierarchy_is_seeded_for_package_and_template() -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                with PlatformGlobalUnitOfWork(session):
                    menus = {menu.route_path: menu for menu in seed_menus(session=session)}
                    assert menus["/esop/publish-center"].title == "工单&发布"
                    expected_parents = {
                        "/erp/product": "/esop",
                        "/esop/order-center": "/esop/publish-center",
                        "/esop/records": "/esop/publish-center",
                        "/esop/order-center/orders": "/esop/publish-center",
                        "/esop/records/reports": "/esop/publish-center",
                        "/esop/records/alarms": "/esop/publish-center",
                    }
                    original = {
                        path: (menus[path].id, menus[path].sort)
                        for path in expected_parents
                    }
                    for path, parent_path in expected_parents.items():
                        assert menus[path].parent_id == menus[parent_path].id
                    assert not menus["/esop/order-center"].is_visible
                    assert not menus["/esop/records"].is_visible
                    assert menus["/esop/publish-center/broadcasts"].sort < menus["/esop/records/reports"].sort < menus["/esop/records/alarms"].sort

                    menus = {menu.route_path: menu for menu in seed_menus(session=session)}
                    for path, parent_path in expected_parents.items():
                        assert menus[path].parent_id == menus[parent_path].id
                        assert (menus[path].id, menus[path].sort) == original[path]

                    plan = session.exec(
                        select(TenantPlan).where(TenantPlan.code == "standard")
                    ).one()
                    template = session.exec(
                        select(TenantInitializationTemplate).where(
                            TenantInitializationTemplate.code == "standard"
                        )
                    ).one()
                    assert template.is_default and plan.is_default
                    selected = set(session.exec(
                        select(TenantPlanMenu.menu_id).where(TenantPlanMenu.plan_id == plan.id)
                    ).all())
                    for path, parent_path in expected_parents.items():
                        assert menus[path].id in selected
                        assert menus[parent_path].id in selected
        finally:
            transaction.rollback()
