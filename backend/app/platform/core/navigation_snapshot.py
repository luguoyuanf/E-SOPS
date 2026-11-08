"""One live authorization snapshot keeps menu cache hits revocation-safe."""

import hashlib
import json
import uuid

from sqlalchemy import String, cast, func
from sqlmodel import Session, select

from app.platform.core.authorization_models import Menu, Role, RoleMenu, UserRole
from app.platform.core.tenancy_models import Tenant, TenantPlan, TenantPlanMenu
from app.platform.core.tenant_menu_access import tenant_permission_allowed


def tenant_navigation_snapshot(
    session: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    load_menus: bool = False,
) -> tuple[str, list[Menu] | None]:
    grants = (
        select(RoleMenu.menu_id)
        .join(Role, Role.id == RoleMenu.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            Role.tenant_id == tenant_id,
            Role.is_active,
            UserRole.user_id == user_id,
            UserRole.tenant_id == tenant_id,
        )
        .distinct()
        .subquery()
    )
    plan = (
        select(TenantPlanMenu.menu_id)
        .join(TenantPlan, TenantPlan.id == TenantPlanMenu.plan_id)
        .join(Tenant, Tenant.plan_id == TenantPlan.id)
        .where(Tenant.id == tenant_id, Tenant.is_active, TenantPlan.is_active)
        .subquery()
    )
    mysql = session.get_bind().dialect.name == "mysql"
    # MySQL hashes each policy row server-side. Hot reads transfer only IDs and
    # fixed-size digests, not the full menu labels/components/route metadata.
    stamp = (
        func.sha2(
            cast(
                func.json_array(
                    *Menu.__table__.columns,
                    grants.c.menu_id.is_not(None),
                    plan.c.menu_id.is_not(None),
                ),
                String,
            ),
            256,
        )
        if mysql
        else None
    )
    query = (
        select(Menu, grants.c.menu_id, plan.c.menu_id)
        .outerjoin(grants, grants.c.menu_id == Menu.id)
        .outerjoin(plan, plan.c.menu_id == Menu.id)
        .order_by(Menu.sort, Menu.created_at, Menu.id)
    )
    if mysql and not load_menus:
        rows = session.exec(query.with_only_columns(Menu.id, stamp)).all()
        digest = hashlib.sha256(
            json.dumps([row[1] for row in rows], separators=(",", ":")).encode()
        ).hexdigest()
        return digest, None
    rows = session.exec(query.add_columns(stamp) if mysql else query).all()
    stamps = [row[3] for row in rows] if mysql else None
    rows = [row[:3] for row in rows]
    menus = {menu.id: menu for menu, _, _ in rows}
    selected = {menu.id for menu, _, planned in rows if planned is not None}

    def allowed(menu: Menu) -> bool:
        seen = set()
        while menu:
            if (
                menu.id in seen
                or menu.id not in selected
                or not menu.is_active
                or not tenant_permission_allowed(menu.permission_code)
            ):
                return False
            seen.add(menu.id)
            if menu.parent_id is None:
                return True
            menu = menus.get(menu.parent_id)
        return False

    # Includes actual grants/plan bindings and menu content, not just timestamps:
    # direct ORM changes and missed Redis invalidation cannot reuse stale grants.
    fingerprint = hashlib.sha256(
        json.dumps(
            stamps
            if mysql
            else [
                [menu.model_dump(mode="json"), granted is not None, planned is not None]
                for menu, granted, planned in rows
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return fingerprint, [
        menu for menu, granted, _ in rows if granted is not None and allowed(menu)
    ]
