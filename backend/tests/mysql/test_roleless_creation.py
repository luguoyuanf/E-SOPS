"""A user without selected roles has no tenant menu or API permissions."""

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from jwt import decode
from sqlmodel import Session, select
from starlette.requests import Request

from app import crud
from app.api.deps import (
    get_user_from_token_payload,
    has_backoffice_menu,
    user_has_permission,
)
from app.api.routes.login import create_login_token
from app.core.config import settings
from app.core.database import engine
from app.core.security import ALGORITHM
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.models import TokenPayload
from app.platform.core.authorization_models import (
    Menu,
    Post,
    Role,
    RoleMenu,
    UserPost,
    UserRole,
)
from app.platform.core.identity_models import UserCreate
from app.platform.core.navigation_snapshot import tenant_navigation_snapshot
from app.platform.core.tenancy_models import TenantMembership
from app.platform.tenant_uow import PlatformTenantUnitOfWork
from app.platform.web_api import authenticate_terminal_staff, get_terminal_staff_profile


def test_terminal_staff_profile_reads_latest_tenant_post_and_hire_date(session: Session) -> None:
    username = f"badge_{uuid.uuid4().hex[:12]}"
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID):
        user = crud.create_user(
            session=session, tenant_id=DEFAULT_TENANT_ID,
            user_create=UserCreate(username=username, password="TestPass123!"),
        )
        post = Post(tenant_id=DEFAULT_TENANT_ID, code=f"post_{uuid.uuid4().hex[:10]}", name="装配员")
        session.add(post)
        session.flush()
        session.add(UserPost(user_id=user.id, tenant_id=DEFAULT_TENANT_ID, post_id=post.id))
        membership = session.get(TenantMembership, (user.id, DEFAULT_TENANT_ID))
        assert membership is not None
        membership.hire_date = date(2026, 10, 1)
        session.add(membership)
        session.flush()
        first = get_terminal_staff_profile(session=session, tenant_id=DEFAULT_TENANT_ID, user_id=user.id)
        assert first["post"] == "装配员"
        assert first["hiredate"] == "2026-10-01"
        post.name = "质检员"
        session.add(post)
        session.flush()
        latest = get_terminal_staff_profile(session=session, tenant_id=DEFAULT_TENANT_ID, user_id=user.id)
        assert latest["post"] == "质检员"


@pytest.fixture
def session():
    assert settings.DATABASE_TYPE == "mysql" and settings.MYSQL_DB == "esop_fva_test_20261024"
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode="create_savepoint") as scoped:
                yield scoped
        finally:
            outer.rollback()


def test_new_user_without_roles_has_no_menu_or_permission(session: Session) -> None:
    username = f"roleless_{uuid.uuid4().hex[:12]}"
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID):
        user = crud.create_user(
            session=session,
            tenant_id=DEFAULT_TENANT_ID,
            user_create=UserCreate(username=username, password="TestPass123!"),
        )
        roles = session.exec(select(UserRole).where(UserRole.user_id == user.id)).all()
        assert roles == []
        assert tenant_navigation_snapshot(session, DEFAULT_TENANT_ID, user.id, load_menus=True)[1] == []
        assert not user_has_permission(
            session=session,
            current_user=user,
            tenant_id=DEFAULT_TENANT_ID,
            permission_code="dashboard:view",
        )
        assert not has_backoffice_menu(session, user, DEFAULT_TENANT_ID)

        request = Request({"type": "http", "method": "POST", "path": "/api/v1/login/access-token",
                           "headers": [], "client": ("127.0.0.1", 1234)})
        with pytest.raises(HTTPException) as rejected:
            create_login_token(session=session, request=request, user=user, tenant_id=DEFAULT_TENANT_ID)
        assert rejected.value.status_code == 403
        terminal = authenticate_terminal_staff(
            session=session, request=request, tenant_id=DEFAULT_TENANT_ID,
            username=username, password="TestPass123!",
        )
        terminal_payload = TokenPayload(**decode(terminal["accessToken"], settings.SECRET_KEY, algorithms=[ALGORITHM]))
        assert terminal_payload.client_kind == "terminal"
        with pytest.raises(HTTPException) as forbidden:
            get_user_from_token_payload(session=session, token_data=terminal_payload)
        assert forbidden.value.status_code == 403
        assert get_user_from_token_payload(session=session, token_data=terminal_payload, allow_terminal=True).id == user.id

        empty_role = Role(tenant_id=DEFAULT_TENANT_ID, code=f"empty_{uuid.uuid4().hex[:10]}", name="No backend menu")
        session.add(empty_role)
        session.flush()
        session.add(UserRole(user_id=user.id, tenant_id=DEFAULT_TENANT_ID, role_id=empty_role.id))
        button = session.exec(select(Menu).where(Menu.type == "button")).first()
        assert button is not None
        session.add(RoleMenu(role_id=empty_role.id, menu_id=button.id))
        session.flush()
        assert not has_backoffice_menu(session, user, DEFAULT_TENANT_ID)
        with pytest.raises(HTTPException) as no_menu:
            create_login_token(session=session, request=request, user=user, tenant_id=DEFAULT_TENANT_ID)
        assert no_menu.value.status_code == 403

        role = session.exec(select(Role).where(Role.tenant_id == DEFAULT_TENANT_ID, Role.code == "user")).one()
        session.add(UserRole(user_id=user.id, tenant_id=DEFAULT_TENANT_ID, role_id=role.id))
        session.flush()
        assert user_has_permission(
            session=session,
            current_user=user,
            tenant_id=DEFAULT_TENANT_ID,
            permission_code="dashboard:view",
        )
        assert has_backoffice_menu(session, user, DEFAULT_TENANT_ID)
        backoffice = create_login_token(session=session, request=request, user=user, tenant_id=DEFAULT_TENANT_ID)
        backoffice_payload = TokenPayload(**decode(backoffice.access_token, settings.SECRET_KEY, algorithms=[ALGORITHM]))
        assert backoffice_payload.client_kind == "backoffice"
        assert get_user_from_token_payload(session=session, token_data=backoffice_payload).id == user.id
        for user_role in session.exec(select(UserRole).where(UserRole.user_id == user.id)).all():
            session.delete(user_role)
        session.flush()
        with pytest.raises(HTTPException) as revoked:
            get_user_from_token_payload(session=session, token_data=backoffice_payload)
        assert revoked.value.status_code == 403
