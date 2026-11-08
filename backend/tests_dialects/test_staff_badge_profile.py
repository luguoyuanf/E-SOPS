"""The legacy terminal badge receives the current tenant's employee details."""
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from app import crud
from app.api.routes import login
from app.core import tenancy
from app.platform.core.identity_models import User, UserCreate, UserUpdate
from app.platform.core.tenancy_models import TenantMembership
from app.platform.web_api import authenticate_terminal_staff


@pytest.mark.parametrize('filled', [False, True])
def test_terminal_login_projects_badge_fields(monkeypatch, filled):
    tenant = uuid.uuid4()
    user = User(username='badge', hashed_password='unused', full_name='测试员工',
                mobile='13800138000' if filled else None,
                avatar_url='/api/v1/files/avatar/download' if filled else None)
    membership = TenantMembership(user_id=user.id, tenant_id=tenant,
                                  hire_date=date(2026, 10, 1) if filled else None)
    session = MagicMock()
    session.info = {}
    session.identity_map = {}
    session.new = session.dirty = session.deleted = set()
    session.exec.return_value.all.return_value = ['经理', '质检员'] if filled else []
    monkeypatch.setattr(crud, 'get_user_by_username', lambda **_: user)
    monkeypatch.setattr(crud, 'authenticate', lambda **_: user)
    monkeypatch.setattr(tenancy, 'get_active_tenant_membership', lambda **_: (membership, SimpleNamespace(id=tenant)))
    monkeypatch.setattr(login, 'is_login_rate_limited', lambda *_: False)
    monkeypatch.setattr(login, 'clear_failed_login_attempts', lambda *_: None)
    monkeypatch.setattr(login, 'create_login_token', lambda **_: SimpleNamespace(access_token='test-token'))
    result = authenticate_terminal_staff(session=session, request=Request({'type':'http', 'headers':[]}),
                                         tenant_id=tenant, username='badge', password='unused')
    assert result['post'] == ('经理、质检员' if filled else '')
    assert result['phoneNumber'] == (user.mobile or '')
    assert result['hiredate'] == ('2026-10-01' if filled else '')
    assert result['avatar'] == (user.avatar_url or '')
    assert result['accessToken'] == 'test-token'


def test_hire_date_is_tenant_membership_data():
    assert 'hire_date' not in User.__table__.columns
    assert 'hire_date' in TenantMembership.__table__.columns
    assert UserCreate(username='badge', password='12345678', hire_date='2026-10-01').hire_date == date(2026, 10, 1)
    assert UserUpdate(hire_date=None).model_dump(exclude_unset=True) == {'hire_date': None}
