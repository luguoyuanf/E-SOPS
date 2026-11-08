"""Navigation refresh must not override user-managed menu ordering."""
from unittest.mock import Mock

from app.platform.bootstrap_navigation import ensure_menu
from app.platform.core.authorization_models import Menu


def test_existing_menu_sort_is_preserved_while_updating_title():
    session = Mock()
    menu = Menu(title="原名称", type="menu", permission_code="esop:sop:list", sort=987)
    session.exec.return_value.first.return_value = menu
    updated = ensure_menu(session=session,title="SOP列表",type="menu",sort=10,permission_code="esop:sop:list")
    assert updated.title == "SOP列表"
    assert updated.sort == 987
    ensure_menu(session=session,title="SOP列表",type="menu",sort=20,permission_code="esop:sop:list")
    assert updated.sort == 987


def test_new_menu_uses_initial_default_order():
    session = Mock()
    session.exec.return_value.first.return_value = None
    menu = ensure_menu(session=session,title="新入口",type="menu",sort=30,permission_code="esop:new:list")
    assert menu.sort == 30
