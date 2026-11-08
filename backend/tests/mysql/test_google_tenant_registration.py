"""Real fixed-test MySQL coverage; all writes roll back via the shared fixture."""
import re
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, select
from starlette.requests import Request

from app.api.routes import login
from app.core.clock import get_datetime_utc
from app.core.security import get_password_hash
from app.core.tenancy import TenantContext, get_active_tenant_membership
from app.platform.core.authorization_models import Role, UserRole
from app.platform.core.identity_models import (
    EnterpriseOidcIdentity,
    EnterpriseOidcLoginTicket,
    UserSession,
)
from app.platform.core.tenancy_models import Tenant
from app.platform.infra import google_oauth_config
from app.platform.tenant_uow import PlatformGlobalUnitOfWork
from app.platform.user_directory import SqlUserDirectory
from tests.mysql.test_official_channel import session as database_session

session = database_session


def test_first_google_login_creates_one_bound_admin_tenant(session, monkeypatch):
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    monkeypatch.setattr(login, "is_public_registration_enabled", lambda **_: True)
    subject = f"esops-google-test-{uuid.uuid4().hex}"
    email = f"esops-google-test-{uuid.uuid4().hex}@gmail.com"
    claims = {"sub": subject, "email": email, "email_verified": True, "name": "Google Test"}
    with PlatformGlobalUnitOfWork(session):
        user = login.resolve_enterprise_oidc_user(session=session, claims=claims)
        binding = session.exec(select(EnterpriseOidcIdentity).where(EnterpriseOidcIdentity.subject == subject)).one()
        assert binding.user_id == user.id
        assert binding.tenant_id is not None
        assert get_active_tenant_membership(session=session, user_id=user.id, tenant_id=binding.tenant_id)
        login.activate_platform_tenant_scope(session, binding.tenant_id, privileged=True)
        assert SqlUserDirectory(session).is_tenant_administrator(user.id, binding.tenant_id)
        again = login.resolve_enterprise_oidc_user(session=session, claims=claims)
        assert again.id == user.id
        assert len(session.exec(select(EnterpriseOidcIdentity).where(EnterpriseOidcIdentity.subject == subject)).all()) == 1
        tenant = session.get(Tenant, binding.tenant_id)
        assert re.fullmatch(r"g-[0-9a-f]{20}", tenant.code)
        preset_codes = session.exec(select(Role.code).where(Role.tenant_id == tenant.id)).all()
        assert {"super_admin", "esop_manager", "esop_team_leader", "esop_member"}.issubset(preset_codes)
        tenant.is_active = False
        session.add(tenant)
        session.flush()
        with pytest.raises(HTTPException) as disabled_tenant:
            login.resolve_enterprise_oidc_user(session=session, claims=claims)
        assert disabled_tenant.value.status_code == 403
        tenant.is_active = True
        session.add(tenant)
        session.flush()
        user.is_active = False
        session.add(user)
        session.flush()
        with pytest.raises(HTTPException) as disabled_user:
            login.resolve_enterprise_oidc_user(session=session, claims=claims)
        assert disabled_user.value.status_code == 403
        user.is_active = True
        session.add(user)
        session.flush()
        session.exec(delete(UserRole).where(UserRole.user_id == user.id, UserRole.tenant_id == binding.tenant_id))
        session.flush()
        with pytest.raises(HTTPException) as removed_admin:
            login.resolve_enterprise_oidc_user(session=session, claims=claims)
        assert removed_admin.value.status_code == 403


def test_existing_email_does_not_create_or_auto_bind(session, monkeypatch):
    from app.platform.core.identity_models import User

    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    monkeypatch.setattr(login, "is_public_registration_enabled", lambda **_: True)
    subject = f"esops-google-test-{uuid.uuid4().hex}"
    with PlatformGlobalUnitOfWork(session):
        user = session.exec(select(User).where(User.email.is_not(None))).first()
        assert user and user.email
        with pytest.raises(HTTPException) as error:
            login.create_google_tenant(session=session, subject=subject, email=user.email, full_name="Test")
        assert error.value.status_code == 409
        assert not session.exec(select(EnterpriseOidcIdentity).where(EnterpriseOidcIdentity.subject == subject)).first()


def test_admin_binding_state_and_ticket_are_tenant_bound(session, monkeypatch):
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    google_config = google_oauth_config.GoogleOAuthConfig(True, "test-client", "test-secret", "http://localhost:18095/api/v1/login/enterprise-oidc/callback")
    monkeypatch.setattr(google_oauth_config, "load_google_oauth_config", lambda: google_config)
    monkeypatch.setattr(google_oauth_config, "lock_and_load_google_oauth_config", lambda _session: google_config)
    monkeypatch.setattr(login, "is_public_registration_enabled", lambda **_: True)
    monkeypatch.setattr(login, "get_oidc_provider_metadata", lambda **_: {"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth"})
    monkeypatch.setattr(login, "exchange_authorization_code", lambda **_: "synthetic-id-token")
    google_subject = f"esops-bind-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(login, "validate_identity_token", lambda **_: {"sub": google_subject, "email": "test@gmail.com", "email_verified": True})
    monkeypatch.setattr(login.redis_cache, "incr", lambda *_args, **_kwargs: 1)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "server": ("localhost", 80), "scheme": "http"})
    with PlatformGlobalUnitOfWork(session):
        subject = f"esops-create-test-{uuid.uuid4().hex}"
        email = f"esops-create-test-{uuid.uuid4().hex}@gmail.com"
        owner = login.create_google_tenant(session=session, subject=subject, email=email, full_name="Test Admin")
        identity = session.exec(select(EnterpriseOidcIdentity).where(EnterpriseOidcIdentity.subject == subject)).one()
        tenant_id = identity.tenant_id
        login.activate_platform_tenant_scope(session, tenant_id, privileged=True)
        session.delete(identity)
        owner.hashed_password = get_password_hash("temporary-test-password")
        session.add(owner)
        jti = uuid.uuid4().hex
        session.add(UserSession(user_id=owner.id, tenant_id=tenant_id, token_jti=jti, expires_at=get_datetime_utc() + timedelta(minutes=10)))
        session.flush()
        session.info["verified_request_session"] = (owner.id, jti, tenant_id)
        context = TenantContext(tenant_id=tenant_id, tenant_code="test", user_id=owner.id)
        result = login.google_binding_start(session=session, current_user=owner, tenant=context, body=login.GoogleBindingStart(current_password="temporary-test-password"))
        state = parse_qs(urlparse(result["authorization_url"]).query)["state"][0]
        response = login.complete_enterprise_oidc_login(request=request, session=session, code="synthetic-code", state=state)
        assert response.headers["location"] == "/profile?google_binding=success"
        binding = session.exec(select(EnterpriseOidcIdentity).where(EnterpriseOidcIdentity.subject == google_subject)).one()
        assert binding.user_id == owner.id and binding.tenant_id == tenant_id
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(EnterpriseOidcIdentity(provider="google", subject=google_subject, user_id=owner.id, tenant_id=tenant_id))
            session.flush()
        ticket_value = "x" * 48 + uuid.uuid4().hex
        session.add(EnterpriseOidcLoginTicket(ticket_hash=login.hash_oidc_value(f"{ticket_value}.{google_oauth_config.google_oauth_fingerprint(google_config)}"), user_id=owner.id, tenant_id=tenant_id, expires_at=get_datetime_utc() + timedelta(minutes=5)))
        session.flush()
        rotated = google_oauth_config.GoogleOAuthConfig(True, "rotated-client", "rotated-secret", google_config.redirect_uri)
        monkeypatch.setattr(google_oauth_config, "lock_and_load_google_oauth_config", lambda _session: rotated)
        with pytest.raises(HTTPException) as rotated_ticket:
            login.exchange_enterprise_oidc_ticket(request=request, session=session, body=login.EnterpriseOidcTicketExchange(ticket=ticket_value))
        assert rotated_ticket.value.status_code == 400
        disabled = google_oauth_config.GoogleOAuthConfig(False, "test-client", "test-secret", google_config.redirect_uri)
        monkeypatch.setattr(google_oauth_config, "lock_and_load_google_oauth_config", lambda _session: disabled)
        with pytest.raises(HTTPException) as disabled_ticket:
            login.exchange_enterprise_oidc_ticket(request=request, session=session, body=login.EnterpriseOidcTicketExchange(ticket=ticket_value))
        assert disabled_ticket.value.status_code == 400
        monkeypatch.setattr(google_oauth_config, "lock_and_load_google_oauth_config", lambda _session: google_config)
        aba = google_oauth_config.GoogleOAuthConfig(True, google_config.client_id, google_config.client_secret, google_config.redirect_uri, "different-revision")
        monkeypatch.setattr(google_oauth_config, "lock_and_load_google_oauth_config", lambda _session: aba)
        with pytest.raises(HTTPException) as aba_ticket:
            login.exchange_enterprise_oidc_ticket(request=request, session=session, body=login.EnterpriseOidcTicketExchange(ticket=ticket_value))
        assert aba_ticket.value.status_code == 400
        monkeypatch.setattr(google_oauth_config, "lock_and_load_google_oauth_config", lambda _session: google_config)
        token = login.exchange_enterprise_oidc_ticket(request=request, session=session, body=login.EnterpriseOidcTicketExchange(ticket=ticket_value))
        assert token.tenant_id == tenant_id
        with pytest.raises(HTTPException) as reused_ticket:
            login.exchange_enterprise_oidc_ticket(request=request, session=session, body=login.EnterpriseOidcTicketExchange(ticket=ticket_value))
        assert reused_ticket.value.status_code == 400
        reused_state = login.complete_enterprise_oidc_login(request=request, session=session, code="synthetic-code", state=state)
        assert reused_state.status_code == 302
        assert reused_state.headers["location"] == "/auth/login?google_error=login_failed"
