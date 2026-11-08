"""Terminal login errors remain specific without requiring a station binding."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import crud
from app.api.routes import login
from app.core import tenancy
from app.platform.web_api import authenticate_terminal_staff


@pytest.mark.parametrize(('case', 'expected'), [
    ('missing', '当前租户下不存在该账号'),
    ('other_tenant', '当前租户下不存在该账号'),
    ('password', '账号或密码错误'),
    ('inactive', '账号已停用'),
    ('mfa', '多重验证'),
    ('success', None),
])
def test_terminal_login_feedback(monkeypatch, case, expected):
    user = SimpleNamespace(id=uuid4(), username='operator', email=None,
                           full_name='Operator', is_active=case != 'inactive',
                           mfa_enabled=case == 'mfa')
    monkeypatch.setattr(crud, 'get_user_by_username', lambda **_: None if case == 'missing' else user)
    monkeypatch.setattr(crud, 'authenticate', lambda **_: None if case in {'missing', 'password'} else user)
    monkeypatch.setattr(tenancy, 'get_active_tenant_membership',
                        lambda **_: None if case == 'other_tenant' else (object(), object()))
    monkeypatch.setattr(login, 'is_login_rate_limited', lambda *_: False)
    monkeypatch.setattr(login, 'record_failed_login_attempt', lambda *_: False)
    monkeypatch.setattr(login, 'clear_failed_login_attempts', lambda *_: None)
    if case == 'success':
        user.mobile = None
        user.avatar_url = None
        from datetime import date
        monkeypatch.setattr(tenancy, 'get_active_tenant_membership',
                            lambda **_: (SimpleNamespace(hire_date=date(2026, 10, 1)), object()))
        from contextlib import nullcontext

        from app.platform import tenant_uow
        monkeypatch.setattr(tenant_uow, 'PlatformTenantUnitOfWork', lambda *_: nullcontext())
    issue = Mock(return_value=SimpleNamespace(access_token='test-token'))
    monkeypatch.setattr(login, 'create_login_token', issue)
    request = Request({'type': 'http', 'headers': []})
    session = Mock()
    session.exec.return_value.all.return_value = []
    kwargs = {'session': session, 'request': request, 'tenant_id': uuid4(),
              'username': 'operator', 'password': 'test-only'}
    if expected:
        with pytest.raises(HTTPException) as caught:
            authenticate_terminal_staff(**kwargs)
        assert caught.value.status_code == 401
        assert expected in caught.value.detail
        issue.assert_not_called()
    else:
        assert authenticate_terminal_staff(**kwargs)['accessToken'] == 'test-token'
        assert issue.call_args.kwargs['client_kind'] == 'terminal'
        assert issue.call_args.kwargs['tenant_id'] == kwargs['tenant_id']
