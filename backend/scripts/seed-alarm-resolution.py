"""Add only the alarm resolution action to existing default plans and system tenant admins.

Run explicitly after backup; never changes existing menu ordering or ordinary roles.
"""
from sqlmodel import Session, select

from app.core.database import engine
from app.platform.bootstrap_navigation import ensure_menu
from app.platform.core.authorization_models import Menu, Role, RoleMenu
from app.platform.core.tenancy_models import TenantPlan, TenantPlanMenu
from app.platform.tenant_uow import PlatformGlobalUnitOfWork


def seed(session):
    before = {row.id: row.sort for row in session.exec(select(Menu)).all()}
    parent = session.exec(select(Menu).where(Menu.permission_code == "esop:alarm:list")).one()
    action = ensure_menu(session=session, title="解除报警", type="button", sort=2,
                         parent_id=parent.id, permission_code="esop:alarm:resolve", is_visible=False)
    for plan in session.exec(select(TenantPlan).where(TenantPlan.is_default == True)).all():  # noqa: E712
        if session.get(TenantPlanMenu, (plan.id, action.id)) is None:
            session.add(TenantPlanMenu(plan_id=plan.id, menu_id=action.id))
    for role in session.exec(select(Role).where(Role.code == "super_admin", Role.is_system == True)).all():  # noqa: E712
        if session.get(RoleMenu, (role.id, action.id)) is None:
            session.add(RoleMenu(role_id=role.id, menu_id=action.id))
    session.flush()
    assert all(row.sort == before[row.id] for row in session.exec(select(Menu)).all() if row.id in before)
    return action.id


if __name__ == "__main__":
    with Session(engine) as session, PlatformGlobalUnitOfWork(session):
        first = seed(session)
        session.flush()
        assert seed(session) == first
        session.commit()
    print("ALARM_RESOLUTION_PERMISSION_SEED_IDEMPOTENT_OK; existing menu sort preserved")  # noqa: T201
