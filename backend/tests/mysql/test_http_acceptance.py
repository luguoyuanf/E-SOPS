"""Real upstream HTTP acceptance on loopback; no PostgreSQL pytest fixtures.

Run: uv run python tests/mysql/test_http_acceptance.py
The local API must already use the dedicated MySQL test schema. Synthetic
fixtures are disabled afterwards; framework seeds and shared services are kept.
Authentication uses short-lived scoped test sessions, not the password/captcha
login flow; browser login acceptance is a separate validation.
"""
import json
import os
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlmodel import Session, delete, select  # noqa: E402

from app.core.clock import get_datetime_utc  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.core.tenancy import get_active_tenant_membership  # noqa: E402
from app.platform.core.identity_models import User, UserSession  # noqa: E402
from app.platform.core.tenancy_models import Tenant  # noqa: E402
from app.platform.tenant_uow import PlatformTenantUnitOfWork  # noqa: E402

BASE = os.environ.get('FVA_HTTP_TEST_URL', 'http://127.0.0.1:18094/api/v1')
if not BASE.startswith(('http://127.0.0.1:', 'http://localhost:')):
    raise RuntimeError('HTTP acceptance only permits loopback APIs')
# Explicit standalone execution only; broad pytest runs must not create HTTP fixtures.
__test__ = False


def request(path, body=None, token=None, *, method=None, expected=200, form=False, headers=None):
    headers = dict(headers or {})
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers,
                                 method=method or ('POST' if data is not None else 'GET'))
    try:
        response = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    expected = (expected,) if isinstance(expected, int) else expected
    raw = response.read()
    response.close()
    try:
        result = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        result = None
    error_code = result.get('code') if isinstance(result, dict) else None
    assert response.status in expected, f'{req.method} {path}: status {response.status}, code {error_code}, expected {expected}'
    return result


FIXTURE_SESSIONS = []


def authenticated_fixture(username, code='default'):
    """Issue only scoped, ten-minute test sessions in the dedicated test schema."""
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == username)).one()
        tenant = session.exec(select(Tenant).where(Tenant.code == code)).one()
        membership = get_active_tenant_membership(session=session, user_id=user.id, tenant_id=tenant.id)
        assert membership is not None and user.is_active and tenant.is_active
        token_id = str(uuid.uuid4())
        duration = timedelta(minutes=10)
        with PlatformTenantUnitOfWork(session, tenant.id):
            session.add(UserSession(user_id=user.id, tenant_id=tenant.id, token_jti=token_id,
                                   user_agent='upstream-http-acceptance',
                                   expires_at=get_datetime_utc() + duration))
            session.commit()
        FIXTURE_SESSIONS.append((tenant.id, token_id))
        return create_access_token(user.id, expires_delta=duration, token_id=token_id, tenant_id=tenant.id)


def cleanup_fixture_sessions():
    for tenant_id, token_id in FIXTURE_SESSIONS:
        with Session(engine) as session, PlatformTenantUnitOfWork(session, tenant_id):
            session.exec(delete(UserSession).where(UserSession.token_jti == token_id))
            session.commit()
    FIXTURE_SESSIONS.clear()


class UpstreamHttpAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if settings.DATABASE_TYPE != 'mysql' or not settings.MYSQL_DB.startswith('esop_fva_test_'):
            raise RuntimeError('HTTP acceptance requires the dedicated MySQL test configuration')
        cls.root = authenticated_fixture(settings.FIRST_SUPERUSER)
        cls.prefix = 'http-' + uuid.uuid4().hex[:12]
        cls.password = uuid.uuid4().hex + 'A9!'
        cls.tenants = []
        cls.tokens = []
        cls.plan = None
        cls.default_plan_id = next(plan['id'] for plan in request('/tenants/plans', token=cls.root)['items']
                                   if plan['is_default'])
        try:
            cls.menus = request('/menus?page_size=500', token=cls.root)['items']
            cls.tenant_menu_ids = [menu['id'] for menu in cls.menus
                                   if (menu.get('permission_code') or '').startswith(
                                       ('system:user:', 'system:role:'))
                                   or menu.get('permission_code') == 'dashboard:view']
            assert cls.tenant_menu_ids, 'Upstream user/role menus must be seeded'
            cls.plan = request('/tenants/plans', {'code': cls.prefix, 'name': 'HTTP验收套餐'}, cls.root)
            request('/tenants/plans/' + cls.plan['id'] + '/menus',
                    {'menu_ids': cls.tenant_menu_ids}, cls.root, method='PUT')
            for suffix in ('a', 'b'):
                code = cls.prefix + '-' + suffix
                email = code + '@example.com'
                tenant = request('/tenants', {'code': code, 'name': 'HTTP验收租户' + suffix,
                                 'plan_id': cls.plan['id'], 'username': email,
                                 'password': cls.password}, cls.root)
                cls.tenants.append(tenant)
                cls.tokens.append(authenticated_fixture(email, code))
            cls.a, cls.b = cls.tokens
        except Exception:
            cls.cleanup()
            raise

    @classmethod
    def cleanup(cls):
        errors = []
        try:
            for tenant in cls.tenants:
                try:
                    request('/tenants/' + tenant['id'], {'is_active': False, 'plan_id': cls.default_plan_id},
                            cls.root, method='PATCH')
                except AssertionError as error:
                    errors.append(error)
            if cls.plan:
                request('/tenants/plans/' + cls.plan['id'], {'is_active': False}, cls.root, method='PATCH')
        finally:
            cleanup_fixture_sessions()
        if errors:
            raise errors[0]

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    def test_01_authentication_and_root_global_visibility(self):
        request('/users/me', expected=401)
        request('/users/me', token='invalid-token', expected=(401, 403))
        malformed = create_access_token('invalid-subject', expires_delta=timedelta(minutes=1),
                                        token_id=str(uuid.uuid4()), tenant_id=uuid.UUID('00000000-0000-4000-8000-000000000001'))
        request('/users/me', token=malformed, expected=(401, 403))
        me = request('/users/me', token=self.root)
        self.assertTrue(me['is_superuser'])
        for resource in ('users', 'roles', 'dictionary-types', 'dictionary-items',
                         'departments', 'posts', 'settings', 'notices',
                         'site-messages/templates', 'site-messages/messages'):
            all_rows = request('/' + resource + '?page_size=200', token=self.root)['items']
            for tenant in self.tenants:
                selected = request('/' + resource + '?tenant_id=' + tenant['id'] + '&page_size=200',
                                   token=self.root)['items']
                if resource in ('users', 'roles'):
                    self.assertTrue(selected)
                    self.assertTrue(any(row.get('tenant_id') == tenant['id'] for row in all_rows))
                self.assertTrue(all(row.get('tenant_id') == tenant['id'] for row in selected))
        own = request('/users', token=self.a)['items']
        self.assertTrue(any(user['email'] == self.tenants[0]['code'] + '@example.com' for user in own))
        self.assertTrue(all(user['tenant_id'] == self.tenants[0]['id'] for user in own))

    def test_02_tenant_isolation_and_forged_scope_rejected(self):
        other = self.tenants[1]['id']
        for resource in ('users', 'roles'):
            request('/' + resource + '?tenant_id=' + other, token=self.a, expected=403)
            request('/' + resource + '?tenant_id=invalid-uuid', token=self.a, expected=422)
            rows = request('/' + resource, token=self.a,
                           headers={'X-Tenant-Id': other, 'X-Role': 'super_admin'})['items']
            self.assertTrue(all(row['tenant_id'] == self.tenants[0]['id'] for row in rows))
        role_b = request('/roles', token=self.b)['items'][0]
        request('/roles/' + role_b['id'], token=self.a, expected=404)
        request('/roles/' + role_b['id'], {'name': '不得跨租户修改'}, self.a, method='PATCH', expected=404)
        user_b = request('/users/me', token=self.b)
        request('/users/' + user_b['id'], token=self.a, expected=(403, 404))
        request('/tenants/switch', {'tenant_id': other}, self.a, expected=403)

    def test_03_tenant_has_no_platform_management(self):
        for path in ('/tenants', '/tenants/plans', '/tenants/templates', '/menus',
                     '/dictionary-types', '/dictionary-items', '/departments', '/posts',
                     '/settings', '/notices', '/site-messages/templates', '/site-messages/messages'):
            request(path, token=self.a, expected=403)
            request(path, token=self.root)
        codes = request('/menus/permissions/me', token=self.a)
        self.assertIn('system:user:list', codes)
        self.assertIn('system:role:list', codes)
        self.assertFalse(any(code.startswith(('platform:', 'system:menu:', 'system:dict:')) for code in codes))
        mine = request('/menus/me', token=self.a)
        self.assertFalse(any((menu.get('permission_code') or '').startswith(
            ('platform:', 'system:menu:', 'system:dict:')) for menu in mine))
        root_menus = request('/menus/me', token=self.root)
        self.assertTrue(any(menu.get('permission_code') == 'platform:tenant:list' for menu in root_menus))
        self.assertTrue(any(menu.get('permission_code') == 'system:menu:list' for menu in root_menus))

    def test_04_role_cannot_delegate_platform_or_other_tenant_menus(self):
        role = request('/roles', {'code': self.prefix, 'name': 'HTTP验收角色',
                                 'tenant_id': self.tenants[1]['id']}, self.a)
        self.assertEqual(role['tenant_id'], self.tenants[0]['id'])
        try:
            available = request('/menus/available', token=self.a)
            self.assertTrue(available)
            forbidden = next(menu for menu in self.menus if menu.get('permission_code') == 'system:menu:list')
            request('/roles/' + role['id'] + '/menus', {'menu_ids': [forbidden['id']]},
                    self.a, method='PUT', expected=403)
            allowed = next(menu for menu in available if menu.get('permission_code') == 'system:user:list')
            request('/roles/' + role['id'] + '/menus', {'menu_ids': [allowed['id']]}, self.a, method='PUT')
            self.assertEqual(request('/roles/' + role['id'] + '/menus', token=self.a), [allowed['id']])
            request('/roles/' + role['id'] + '/menus', {'menu_ids': [allowed['id']]},
                    self.b, method='PUT', expected=404)
        finally:
            request('/roles/' + role['id'], token=self.a, method='DELETE', expected=204)

    def test_05_package_downgrade_immediately_bounds_existing_token(self):
        plan_url = '/tenants/plans/' + self.plan['id'] + '/menus'
        limited = [menu['id'] for menu in self.menus
                   if menu.get('permission_code') in ('system:user:list', 'dashboard:view')]
        try:
            request(plan_url, {'menu_ids': limited}, self.root, method='PUT')
            request('/users', token=self.a)
            request('/roles', token=self.a, expected=403)
            codes = request('/menus/permissions/me', token=self.a)
            self.assertIn('system:user:list', codes)
            self.assertNotIn('system:role:list', codes)
            self.assertFalse(any(code.startswith('system:user:') and code != 'system:user:list' for code in codes))
            tenant_menus = request('/menus/me', token=self.a)
            self.assertFalse(any((menu.get('permission_code') or '').startswith('system:role:') for menu in tenant_menus))
            self.assertTrue(any(menu.get('permission_code') == 'system:role:list'
                                for menu in request('/menus/me', token=self.root)))
            request('/roles?tenant_id=' + self.tenants[0]['id'], token=self.root)
            forbidden = next(menu for menu in self.menus if menu.get('permission_code') == 'platform:tenant:list')
            request(plan_url, {'menu_ids': limited + [forbidden['id']]}, self.root, method='PUT', expected=400)
        finally:
            request(plan_url, {'menu_ids': self.tenant_menu_ids}, self.root, method='PUT')
        request('/roles', token=self.a)


    def test_06_tenant_disable_revokes_access_and_remains_visible_to_root(self):
        tenant_url = '/tenants/' + self.tenants[1]['id']
        request(tenant_url, {'is_active': False}, self.root, method='PATCH')
        self.assertFalse(request(tenant_url, token=self.root)['is_active'])
        request('/users', token=self.b, expected=403)
        request('/users?tenant_id=' + self.tenants[1]['id'], token=self.root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
