import secrets

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.routes.tenants import create_tenant
from app.platform.core.authorization_models import Role
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import (
    Tenant,
    TenantCreate,
    TenantInitializationTemplate,
    TenantPlan,
    TenantProfile,
)
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)
from app.platform.tenant_uow import PlatformTenantUnitOfWork


@pytest.fixture
def platform_only_edition(monkeypatch):
    # These fixtures intentionally create only Platform tables; model the Base
    # Edition rather than invoking ERP provisioning against an incomplete schema.
    from app.core.config import settings
    from app.modules.manifest import build_manifest

    monkeypatch.setattr(settings, "APP_EDITION", "base")
    manifest = build_manifest(edition="base")
    monkeypatch.setattr("app.modules.access.get_runtime_manifest", lambda: manifest)


@pytest.mark.usefixtures("platform_only_edition")
@pytest.mark.parametrize("with_admin", [False, True])
def test_create_tenant_flushes_control_plane_before_switch_and_preserves_parent(
    with_admin,
):
    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine) as session:
        plan = TenantPlan(code="fixture", name="Fixture")
        template = TenantInitializationTemplate(code="fixture", name="Fixture")
        parent = Tenant(code="parent", name="Parent")
        root = User(
            email="root@example.com", hashed_password="unused", is_superuser=True
        )
        session.add_all([plan, template, parent, root])
        session.commit()
        session.info["platform_tenant_id"] = parent.id
        body = TenantCreate(
            code="child",
            name="Child",
            plan_id=plan.id,
            initialization_template_id=template.id,
            username="admin@example.com" if with_admin else None,
            password=secrets.token_urlsafe(16) if with_admin else None,
        )
        result = create_tenant(session=session, current_user=root, tenant_in=body)
        assert (
            result.id != parent.id and session.info["platform_tenant_id"] == parent.id
        )
        profile = session.get(TenantProfile, result.id)
        assert result.admin_username == ("admin@example.com" if with_admin else None)
        assert bool(profile.contact_user_id) == with_admin
        assert not session.exec(select(Role).where(Role.tenant_id == result.id)).all()
        with PlatformTenantUnitOfWork(session, result.id, privileged=True):
            assert (
                len(session.exec(select(Role).where(Role.tenant_id == result.id)).all())
                == 3
            )
        assert not session.new and not session.dirty


@pytest.mark.parametrize(
    "action", ["inactive", "expired", "freeze", "lifecycle_archive", "delete_archive"]
)
def test_lifecycle_revokes_target_tenant_sessions_and_restores_parent(action):
    from datetime import timedelta

    from app.api.routes.tenants import (
        archive_tenant,
        operate_tenant_lifecycle,
        update_tenant,
    )
    from app.core.clock import get_datetime_utc
    from app.platform.core.identity_models import UserSession
    from app.platform.core.tenancy_models import (
        TenantLifecycleActionRequest,
        TenantUpdate,
    )

    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine) as session:
        plan = TenantPlan(code="fixture", name="Fixture")
        parent, target = (
            Tenant(code="parent", name="Parent"),
            Tenant(code="target", name="Target", plan_id=plan.id),
        )
        root = User(
            email="root@example.com", hashed_password="unused", is_superuser=True
        )
        session.add_all(
            [
                plan,
                parent,
                target,
                root,
                TenantProfile(
                    tenant_id=target.id,
                    effective_at=get_datetime_utc() - timedelta(days=2),
                ),
            ]
        )
        session.commit()
        with PlatformTenantUnitOfWork(session, target.id, privileged=True):
            session.add(
                UserSession(
                    user_id=root.id,
                    tenant_id=target.id,
                    token_jti="target",
                    expires_at=get_datetime_utc() + timedelta(hours=1),
                )
            )
            session.flush()
        with PlatformTenantUnitOfWork(session, parent.id, privileged=True):
            session.add(
                UserSession(
                    user_id=root.id,
                    tenant_id=parent.id,
                    token_jti="parent",
                    expires_at=get_datetime_utc() + timedelta(hours=1),
                )
            )
            session.flush()
        session.commit()
        session.info["platform_tenant_id"] = parent.id
        if action == "inactive":
            update_tenant(
                session=session,
                tenant_id=target.id,
                tenant_in=TenantUpdate(is_active=False),
            )
        elif action == "expired":
            update_tenant(
                session=session,
                tenant_id=target.id,
                tenant_in=TenantUpdate(
                    service_expires_at=get_datetime_utc() - timedelta(hours=1)
                ),
            )
        elif action == "delete_archive":
            archive_tenant(session=session, tenant_id=target.id)
        else:
            operate_tenant_lifecycle(
                session=session,
                tenant_id=target.id,
                body=TenantLifecycleActionRequest(
                    action="freeze" if action == "freeze" else "archive",
                    frozen_reason="Fixture",
                ),
            )
        assert session.info["platform_tenant_id"] == parent.id
        assert (
            session.exec(select(UserSession).where(UserSession.token_jti == "parent"))
            .one()
            .revoked_at
            is None
        )
        with PlatformTenantUnitOfWork(session, target.id, privileged=True):
            assert (
                session.exec(
                    select(UserSession).where(UserSession.token_jti == "target")
                )
                .one()
                .revoked_at
                is not None
            )


def test_password_recovery_without_tenant_scope_revokes_resolved_user_sessions():
    from datetime import timedelta

    from app import crud
    from app.core.clock import get_datetime_utc
    from app.platform.core.identity_models import UserSession, UserUpdate
    from app.platform.core.tenancy_models import TenantMembership

    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine) as session:
        tenants = [Tenant(code="a", name="A"), Tenant(code="b", name="B")]
        user = User(email="recover@example.com", hashed_password="unused")
        session.add_all([*tenants, user])
        session.commit()
        for index, tenant in enumerate(tenants):
            session.add(TenantMembership(user_id=user.id, tenant_id=tenant.id))
            session.flush()
            with PlatformTenantUnitOfWork(session, tenant.id, privileged=True):
                session.add(
                    UserSession(
                        user_id=user.id,
                        tenant_id=tenant.id,
                        token_jti=f"token-{index}",
                        expires_at=get_datetime_utc() + timedelta(hours=1),
                    )
                )
                session.flush()
        session.commit()
        crud.update_user(
            session=session,
            db_user=user,
            user_in=UserUpdate(password=secrets.token_urlsafe(16)),
        )
        assert not session.info.get("platform_tenant_id")
        for tenant in tenants:
            with PlatformTenantUnitOfWork(session, tenant.id, privileged=True):
                assert session.exec(select(UserSession)).one().revoked_at is not None


@pytest.mark.usefixtures("platform_only_edition")
def test_browser_payload_null_fields_and_full_menu_plan_create_without_duplicate_role_mappings():
    from app.platform.bootstrap_navigation import seed_menus
    from app.platform.core.authorization_models import RoleMenu
    from app.platform.core.tenancy_models import TenantPlanMenu

    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine) as session:
        plan = TenantPlan(code="browser", name="Browser full plan")
        template = TenantInitializationTemplate(code="browser", name="Browser template")
        parent = Tenant(code="parent", name="Parent")
        root = User(
            email="root@example.com", hashed_password="unused", is_superuser=True
        )
        session.add_all([plan, template, parent, root])
        session.flush()
        menus = seed_menus(session=session)
        by_path = {menu.route_path: menu for menu in menus}
        assert by_path["/esop/basic/operations"].parent_id == by_path["/esop"].id
        assert by_path["/esop/sop-center/review"].parent_id == by_path["/esop"].id
        assert by_path["/esop/sop-center"].is_visible is False
        audit_page = next(menu for menu in menus if menu.route_path == "/erp/finance/action-logs")
        assert audit_page.type == "menu"
        assert audit_page.parent_id != audit_page.id
        assert len([menu for menu in menus if menu.permission_code == "erp:audit:list"]) == 1
        for menu_id in {menu.id for menu in menus}:
            session.add(TenantPlanMenu(plan_id=plan.id, menu_id=menu_id))
        audit_page.title = "Custom audit menu title"
        session.add(audit_page)
        session.commit()
        session.info["platform_tenant_id"] = parent.id
        payload = dict.fromkeys(
            [
                "account_count",
                "address_code",
                "address_detail",
                "contact_mobile",
                "contact_name",
                "customer_source",
                "effective_at",
                "follow_up_notes",
                "industry",
                "owner_name",
                "qualifications",
                "service_expires_at",
                "trial_ends_at",
                "type",
                "website",
            ]
        )
        payload.update(
            code="browser-child",
            name="Browser child",
            plan_id=plan.id,
            initialization_template_id=template.id,
            lifecycle_status="formal",
            username="browser-admin@example.com",
            admin_username="browser_admin",
            password=secrets.token_urlsafe(18),
        )
        selects = []

        def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(engine, "before_cursor_execute", count_selects)
        try:
            created = create_tenant(
                session=session,
                current_user=root,
                tenant_in=TenantCreate.model_validate(payload),
            )
        finally:
            event.remove(engine, "before_cursor_execute", count_selects)
        # Provisioning must not perform a lookup for each global menu.
        assert len(selects) < 120
        session.refresh(audit_page)
        assert audit_page.title == "Custom audit menu title"
        assert created.admin_username == "browser_admin"
        assert session.get(TenantProfile, created.id).contact_user_id
        with PlatformTenantUnitOfWork(session, created.id, privileged=True):
            roles = session.exec(select(Role).where(Role.tenant_id == created.id)).all()
            assert len(roles) == 3
            mappings = session.exec(
                select(RoleMenu).where(
                    RoleMenu.role_id.in_([role.id for role in roles])
                )
            ).all()
            keys = {(mapping.role_id, mapping.menu_id) for mapping in mappings}
            assert mappings and len(keys) == len(mappings)
