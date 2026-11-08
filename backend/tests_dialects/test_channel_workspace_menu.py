"""A tenant role grant alone must not reveal the channel workspace."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.routes import menus
from app.core.tenancy import TenantContext
from app.modules.esop.menu_access import menu_permission_visible
from app.platform.core.authorization_models import Menu


@pytest.mark.parametrize('superuser,channel,visible', [(True, False, True), (False, True, True), (False, False, False)])
def test_channel_workspace_visibility(monkeypatch, superuser, channel, visible):
    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=superuser)
    tenant_id = uuid.uuid4()
    directory = Menu(title='Services', type='directory')
    workspace = Menu(title='Channel', parent_id=directory.id, permission_code='esop:channel:portal')
    session = MagicMock()
    session.exec.return_value.all.return_value = [directory, workspace]
    session.exec.return_value.first.return_value = uuid.uuid4() if channel else None
    monkeypatch.setattr(menus.redis_cache, 'get_json', lambda *a: None)
    monkeypatch.setattr(menus.redis_cache, 'set_json', lambda *a: None)
    monkeypatch.setattr(menus.redis_cache, 'build_versioned_key', lambda *a: 'test')
    monkeypatch.setattr(menus, 'tenant_plan_menu_ids', lambda *a: {directory.id, workspace.id})
    monkeypatch.setattr(menus, 'filter_module_scoped_permissions', lambda **kw: kw['permission_codes'])
    result = menus.read_my_menus(session=session, current_user=user, tenant_context=TenantContext(tenant_id=tenant_id, tenant_code='test', user_id=user.id))
    assert (workspace.id in {item.id for item in result}) is visible
    assert (directory.id in {item.id for item in result}) is visible
    assert menu_permission_visible(session, user.id, 'esop:ota:list')
