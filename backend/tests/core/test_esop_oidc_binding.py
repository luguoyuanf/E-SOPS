import uuid
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes import login
from app.platform.infra import google_oauth_config


def valid_google_state(monkeypatch):
    config = google_oauth_config.GoogleOAuthConfig(True, "test-client", "test-secret", "http://localhost:18095/api/v1/login/enterprise-oidc/callback")
    monkeypatch.setattr(google_oauth_config, "load_google_oauth_config", lambda: config)
    monkeypatch.setattr(google_oauth_config, "lock_and_load_google_oauth_config", lambda _session: config)
    return "state." + google_oauth_config.google_oauth_fingerprint(config)


def test_esop_unbound_google_identity_is_not_linked_by_email(monkeypatch):
    session = MagicMock()
    session.exec.return_value.first.return_value = None
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    monkeypatch.setattr(login.settings, "ENTERPRISE_OIDC_REQUIRE_VERIFIED_EMAIL", True)
    monkeypatch.setattr(login, "is_public_registration_enabled", lambda **_: True)
    lookup = MagicMock(return_value=object())
    monkeypatch.setattr(login.crud, "get_user_by_email", lookup)

    with pytest.raises(HTTPException) as error:
        login.resolve_enterprise_oidc_user(
            session=session,
            claims={"sub": "google-subject", "email": "user@gmail.com", "email_verified": True},
        )

    assert error.value.status_code == 409
    lookup.assert_called_once()
    session.add.assert_not_called()


def test_unbound_third_party_email_cannot_auto_register(monkeypatch):
    session = MagicMock()
    session.exec.return_value.first.return_value = None
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    create = MagicMock()
    monkeypatch.setattr(login, "create_google_tenant", create)
    with pytest.raises(HTTPException) as error:
        login.resolve_enterprise_oidc_user(
            session=session,
            claims={"sub": "google-subject", "email": "user@example.com", "email_verified": True},
        )
    assert error.value.status_code == 403
    create.assert_not_called()


@pytest.mark.parametrize("email,hd", [("user@gmail.com", None), ("user@company.example", "company.example")])
def test_google_authoritative_email_starts_registration(monkeypatch, email, hd):
    session = MagicMock()
    session.exec.return_value.first.return_value = None
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    create = MagicMock(return_value=object())
    monkeypatch.setattr(login, "create_google_tenant", create)
    claims = {"sub": "google-subject", "email": email, "email_verified": True, "name": "Test Admin"}
    if hd:
        claims["hd"] = hd
    assert login.resolve_enterprise_oidc_user(session=session, claims=claims) is create.return_value
    create.assert_called_once_with(session=session, subject="google-subject", email=email, full_name="Test Admin")


def test_unverified_google_email_cannot_auto_register(monkeypatch):
    session = MagicMock()
    session.exec.return_value.first.return_value = None
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    monkeypatch.setattr(login.settings, "ENTERPRISE_OIDC_REQUIRE_VERIFIED_EMAIL", False)
    create = MagicMock()
    monkeypatch.setattr(login, "create_google_tenant", create)
    with pytest.raises(HTTPException) as error:
        login.resolve_enterprise_oidc_user(session=session, claims={"sub": "google-subject", "email": "user@gmail.com", "email_verified": False})
    assert error.value.status_code == 403
    create.assert_not_called()


def test_legacy_identity_without_tenant_fails_closed(monkeypatch):
    session = MagicMock()
    session.exec.return_value.first.return_value = MagicMock(tenant_id=None)
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    with pytest.raises(HTTPException) as error:
        login.resolve_enterprise_oidc_user(
            session=session,
            claims={"sub": "google-subject", "email": "user@gmail.com", "email_verified": True},
        )
    assert error.value.status_code == 403


def test_binding_requires_tenant_administrator(monkeypatch):
    from app.platform.user_directory import SqlUserDirectory

    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    monkeypatch.setattr(SqlUserDirectory, "is_tenant_administrator", lambda *_: False)
    session = MagicMock()
    with pytest.raises(HTTPException) as error:
        login.google_binding_start(
            session=session,
            current_user=MagicMock(),
            tenant=MagicMock(),
            body=login.GoogleBindingStart(current_password="test-password"),
        )
    assert error.value.status_code == 403
    session.add.assert_not_called()


def test_google_login_rejects_non_admin_for_bound_tenant(monkeypatch):
    from app.platform.user_directory import SqlUserDirectory

    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    monkeypatch.setattr(SqlUserDirectory, "is_tenant_administrator", lambda *_: False)
    monkeypatch.setattr(login, "get_active_tenant_membership", lambda **_: (object(), MagicMock(id=uuid.uuid4())))
    monkeypatch.setattr(login, "activate_platform_tenant_scope", lambda *_args, **_kwargs: None)
    session = MagicMock()
    session.exec.return_value.first.return_value = MagicMock(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    with pytest.raises(HTTPException) as error:
        login.resolve_enterprise_oidc_user(session=session, claims={"sub": "bound-google", "email": "user@gmail.com", "email_verified": True})
    assert error.value.status_code == 403
    session.add.assert_not_called()


def test_binding_rejects_wrong_password(monkeypatch):
    from app.platform.user_directory import SqlUserDirectory

    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    monkeypatch.setattr(SqlUserDirectory, "is_tenant_administrator", lambda *_: True)
    monkeypatch.setattr(login.redis_cache, "incr", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(login.security, "verify_password", lambda *_: (False, None))
    session = MagicMock()
    with pytest.raises(HTTPException) as error:
        login.google_binding_start(
            session=session,
            current_user=MagicMock(),
            tenant=MagicMock(),
            body=login.GoogleBindingStart(current_password="wrong-password"),
        )
    assert error.value.status_code == 403
    session.add.assert_not_called()


def test_binding_password_attempt_limit_fails_closed(monkeypatch):
    from app.platform.user_directory import SqlUserDirectory

    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    monkeypatch.setattr(SqlUserDirectory, "is_tenant_administrator", lambda *_: True)
    monkeypatch.setattr(login.redis_cache, "incr", lambda *_args, **_kwargs: 6)
    verify = MagicMock()
    monkeypatch.setattr(login.security, "verify_password", verify)
    with pytest.raises(HTTPException) as error:
        login.google_binding_start(session=MagicMock(), current_user=MagicMock(), tenant=MagicMock(), body=login.GoogleBindingStart(current_password="password"))
    assert error.value.status_code == 429
    verify.assert_not_called()


@pytest.mark.parametrize("code,valid", [(None, False), ("123456", False), ("654321", True)])
def test_binding_requires_valid_mfa_before_authorization(monkeypatch, code, valid):
    from app.platform.user_directory import SqlUserDirectory

    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    monkeypatch.setattr(SqlUserDirectory, "is_tenant_administrator", lambda *_: True)
    monkeypatch.setattr(login.redis_cache, "incr", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(login.security, "verify_password", lambda *_: (True, None))
    monkeypatch.setattr(login, "decrypt_totp_secret", lambda *_: "secret")
    monkeypatch.setattr(login, "verify_totp_code", lambda **_: valid)
    session = MagicMock()
    session.exec.return_value.first.return_value = None
    user = MagicMock(mfa_enabled=True, mfa_secret_encrypted="encrypted")
    start = MagicMock(side_effect=RuntimeError("authorization reached"))
    monkeypatch.setattr(login, "start_enterprise_oidc_login", start)
    session.info = {"verified_request_session": (user.id, "jti", "tenant")}
    if valid:
        with pytest.raises(RuntimeError, match="authorization reached"):
            login.google_binding_start(session=session, current_user=user, tenant=MagicMock(tenant_id="tenant"), body=login.GoogleBindingStart(current_password="password", mfa_code=code))
        start.assert_called_once()
    else:
        with pytest.raises(HTTPException) as error:
            login.google_binding_start(session=session, current_user=user, tenant=MagicMock(tenant_id="tenant"), body=login.GoogleBindingStart(current_password="password", mfa_code=code))
        assert error.value.status_code == 403
        start.assert_not_called()


def test_binding_callback_rejects_revoked_session(monkeypatch):
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    state_value = valid_google_state(monkeypatch)
    state = MagicMock(purpose="bind", binding_user_id=uuid.uuid4(), binding_tenant_id=uuid.uuid4(), binding_session_jti="session-id", nonce="nonce")
    monkeypatch.setattr(login, "consume_enterprise_oidc_state", lambda **_: state)
    monkeypatch.setattr(login, "get_oidc_provider_metadata", lambda **_: {})
    monkeypatch.setattr(login, "exchange_authorization_code", lambda **_: "id-token")
    monkeypatch.setattr(login, "validate_identity_token", lambda **_: {"sub": "google-sub", "email_verified": True})
    monkeypatch.setattr(login, "activate_platform_tenant_scope", lambda *_args, **_kwargs: None)
    session = MagicMock()
    session.exec.return_value.first.return_value = None
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "server": ("localhost", 80), "scheme": "http"})
    response = login.complete_enterprise_oidc_login(request=request, session=session, code="code", state=state_value)
    assert response.status_code == 302
    assert response.headers["location"] == "/profile?google_binding=error"
    session.add.assert_not_called()


def test_google_ticket_rejects_mfa_enabled_user(monkeypatch):
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    valid_google_state(monkeypatch)
    session = MagicMock()
    session.exec.return_value.first.return_value = MagicMock(consumed_at=None, expires_at=login.get_datetime_utc() + timedelta(minutes=5))
    session.get.return_value = MagicMock(is_active=True, mfa_enabled=True)
    create_token = MagicMock()
    monkeypatch.setattr(login, "create_login_token", create_token)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b"", "server": ("localhost", 80), "scheme": "http"})
    with pytest.raises(HTTPException) as error:
        login.exchange_enterprise_oidc_ticket(request=request, session=session, body=login.EnterpriseOidcTicketExchange(ticket="x" * 48))
    assert error.value.status_code == 403
    assert "MFA" in error.value.detail
    create_token.assert_not_called()


@pytest.mark.parametrize("status", [403, 409, 503])
def test_google_callback_uses_same_safe_error_for_account_and_configuration_failures(monkeypatch, status):
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    state_value = valid_google_state(monkeypatch)
    state = MagicMock(purpose="login", nonce="nonce")
    monkeypatch.setattr(login, "consume_enterprise_oidc_state", lambda **_: state)
    monkeypatch.setattr(login, "get_oidc_provider_metadata", lambda **_: {})
    monkeypatch.setattr(login, "exchange_authorization_code", lambda **_: "secret-token")
    monkeypatch.setattr(login, "validate_identity_token", lambda **_: {"sub": "subject", "email": "private@example.com", "email_verified": True})
    def fail(**_):
        raise HTTPException(status_code=status, detail="private account information")
    monkeypatch.setattr(login, "resolve_enterprise_oidc_user", fail)
    monkeypatch.setattr(login, "create_login_log", lambda **_: None)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "server": ("localhost", 80), "scheme": "http"})
    response = login.complete_enterprise_oidc_login(request=request, session=MagicMock(), code="secret-code", state=state_value)
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?google_error=login_failed"
    assert response.headers["cache-control"] == "no-store"
