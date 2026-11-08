"""Exercise tenant role presets on the fixed test database, rolling back all writes."""
import uuid

from sqlmodel import select

from app.api.deps import has_backoffice_menu
from app.platform.bootstrap_rbac import provision_esop_operational_roles
from app.platform.core.authorization_models import Menu, Role, RoleMenu, UserRole
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import Tenant, TenantMembership, TenantPlanMenu
from app.platform.tenant_uow import PlatformGlobalUnitOfWork, PlatformTenantUnitOfWork
from tests.mysql.test_official_channel import session as database_session

session = database_session


def test_presets_allow_manager_and_deny_terminal_only_roles(session):
    with PlatformGlobalUnitOfWork(session):
        tenant = session.exec(select(Tenant).where(Tenant.code == 'g-ed0409089137472f909a')).one()
        menus = session.exec(select(Menu).join(TenantPlanMenu, TenantPlanMenu.menu_id == Menu.id).where(TenantPlanMenu.plan_id == tenant.plan_id)).all()
        with PlatformTenantUnitOfWork(session, tenant.id, privileged=True):
            provision_esop_operational_roles(session=session, tenant=tenant, plan_menus=menus)
            session.flush()
            roles = {role.code: role for role in session.exec(select(Role).where(Role.tenant_id == tenant.id, Role.code.in_(['esop_manager', 'esop_team_leader', 'esop_member']))).all()}
            assert set(roles) == {'esop_manager', 'esop_team_leader', 'esop_member'}
            manager_codes = set(session.exec(select(Menu.permission_code).join(RoleMenu, RoleMenu.menu_id == Menu.id).where(RoleMenu.role_id == roles['esop_manager'].id)).all())
            assert 'esop:plan:list' in manager_codes
            assert 'system:user:update' not in manager_codes
            assert 'esop:channel:admin' not in manager_codes
            assert not session.exec(select(RoleMenu).where(RoleMenu.role_id.in_([roles['esop_team_leader'].id, roles['esop_member'].id]))).all()
            manager = User(username='test-mgr-' + uuid.uuid4().hex[:10], hashed_password='unused')
            worker = User(username='test-worker-' + uuid.uuid4().hex[:10], hashed_password='unused')
            session.add_all([manager, worker])
            session.flush()
            session.add_all([TenantMembership(user_id=manager.id, tenant_id=tenant.id, username=manager.username), TenantMembership(user_id=worker.id, tenant_id=tenant.id, username=worker.username)])
            session.flush()
            session.add_all([UserRole(user_id=manager.id, role_id=roles['esop_manager'].id, tenant_id=tenant.id), UserRole(user_id=worker.id, role_id=roles['esop_member'].id, tenant_id=tenant.id), UserRole(user_id=worker.id, role_id=roles['esop_manager'].id, tenant_id=tenant.id)])
            session.flush()
            assert has_backoffice_menu(session, manager, tenant.id)
            assert not has_backoffice_menu(session, worker, tenant.id)
            provision_esop_operational_roles(session=session, tenant=tenant, plan_menus=menus)
            session.flush()
            assert len(session.exec(select(Role).where(Role.tenant_id == tenant.id, Role.code.in_(list(roles)))).all()) == 3
