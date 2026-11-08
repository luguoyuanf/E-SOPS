"""Tenant plan ceiling, independent of role bindings and frontend visibility."""

import uuid

from sqlmodel import Session, select

from app.platform.core.authorization_models import Menu
from app.platform.core.tenancy_models import Tenant, TenantPlan, TenantPlanMenu


def tenant_permission_allowed(code: str | None) -> bool:
    if code is None:
        return True
    if code.startswith("platform:"):
        return False
    if code.startswith("system:"):
        return code.startswith(
            (
                "system:user:",
                "system:role:",
                "system:department:",
                "system:post:",
                "system:login-log:",
                "system:operation-log:",
            )
        )
    if code == "personal:message:list":
        return False
    return True


def tenant_plan_menu_ids(session: Session, tenant_id: uuid.UUID) -> set[uuid.UUID]:
    tenant = session.get(Tenant, tenant_id)
    plan = (
        session.get(TenantPlan, tenant.plan_id) if tenant and tenant.plan_id else None
    )
    if not plan or not plan.is_active:
        return set()
    selected = set(
        session.exec(
            select(TenantPlanMenu.menu_id).where(TenantPlanMenu.plan_id == plan.id)
        ).all()
    )
    menus = {
        menu.id: menu
        for menu in session.exec(select(Menu).where(Menu.id.in_(selected))).all()
    }

    def allowed(menu_id: uuid.UUID) -> bool:
        seen = set()
        while menu_id:
            menu = menus.get(menu_id)
            if (
                not menu
                or menu_id in seen
                or menu_id not in selected
                or not menu.is_active
                or not tenant_permission_allowed(menu.permission_code)
            ):
                return False
            seen.add(menu_id)
            menu_id = menu.parent_id
        return True

    return {menu_id for menu_id in selected if allowed(menu_id)}
