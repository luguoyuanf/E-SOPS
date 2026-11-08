from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.api.routes import login, social
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.platform.infra import google_oauth_config as config


def test_google_config_reauthentication_accepts_existing_short_password():
    assert social.GoogleConfigUpdate(enabled=True, client_id="client", current_password="short").current_password == "short"
    with pytest.raises(ValidationError):
        social.GoogleConfigUpdate(enabled=True, client_id="client", current_password="")
    assert login.GoogleBindingStart(current_password="short").current_password == "short"


@pytest.mark.parametrize("name", ["google", "Google", " GOOGLE ", "GoOgLe", "Ｇｏｏｇｌｅ"])
def test_generic_social_management_cannot_write_google(name):
    with pytest.raises(HTTPException) as error:
        social.reject_google_type(name)
    assert error.value.status_code == 403


@pytest.mark.parametrize("name", ["google", " GOOGLE ", "Ｇｏｏｇｌｅ"])
def test_legacy_google_user_detail_is_hidden(name):
    session = MagicMock()
    session.exec.return_value.first.return_value = SimpleNamespace(type=name)
    with pytest.raises(HTTPException) as error:
        social.get_social_user_or_404(session=session, tenant_id=None, social_user_id=DEFAULT_TENANT_ID)
    assert error.value.status_code == 404


def test_legacy_google_user_list_filters_unicode_variants(monkeypatch):
    session = MagicMock()
    session.exec.side_effect = [SimpleNamespace(one=lambda: 1), SimpleNamespace(all=lambda: [SimpleNamespace(type="Ｇｏｏｇｌｅ")])]
    convert = MagicMock()
    monkeypatch.setattr(social, "to_social_user_public", convert)
    result = social.read_social_users(session=session, read_tenant=None)
    assert result.items == []
    convert.assert_not_called()


def test_google_config_is_platform_superuser_only(monkeypatch):
    monkeypatch.setattr(social.settings, "APP_EDITION", "esop")
    tenant = SimpleNamespace(tenant_id=DEFAULT_TENANT_ID)
    with pytest.raises(HTTPException) as error:
        social.require_google_platform_admin(SimpleNamespace(is_superuser=False), tenant)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        social.require_google_platform_admin(SimpleNamespace(is_superuser=True), SimpleNamespace(tenant_id=None))
    assert error.value.status_code == 403


def test_non_esop_google_config_unavailable(monkeypatch):
    monkeypatch.setattr(social.settings, "APP_EDITION", "base")
    with pytest.raises(HTTPException) as error:
        social.require_google_platform_admin(SimpleNamespace(is_superuser=True), SimpleNamespace(tenant_id=DEFAULT_TENANT_ID))
    assert error.value.status_code == 404


def test_disabled_database_config_does_not_fallback(monkeypatch):
    session = MagicMock()
    session.exec.return_value.first.return_value = SimpleNamespace(is_active=False, client_id="stored-client", remark="revision-1")
    monkeypatch.setattr(config, "Session", lambda *_: nullcontext(session))
    monkeypatch.setattr(config, "PlatformTenantUnitOfWork", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(config.settings, "ENTERPRISE_OIDC_ENABLED", True)
    result = config.load_google_oauth_config()
    assert result.enabled is False
    assert result.client_id == "stored-client"
    assert result.client_secret == ""


def test_corrupt_database_secret_does_not_fallback(monkeypatch):
    session = MagicMock()
    session.exec.return_value.first.return_value = SimpleNamespace(is_active=True, client_id="stored-client", client_secret="corrupt", agent_id="http://localhost:18095/api/v1/login/enterprise-oidc/callback", remark="revision-1")
    monkeypatch.setattr(config, "Session", lambda *_: nullcontext(session))
    monkeypatch.setattr(config, "PlatformTenantUnitOfWork", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(config.settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(config.settings, "ENTERPRISE_OIDC_ENABLED", True)
    monkeypatch.setattr(config, "decrypt_secret", MagicMock(side_effect=ValueError("secret")))
    with pytest.raises(HTTPException) as error:
        config.load_google_oauth_config()
    assert error.value.status_code == 503
    assert "corrupt" not in error.value.detail


def test_changed_google_config_rejects_pending_state(monkeypatch):
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    old = config.GoogleOAuthConfig(True, "old-client", "old-secret", "http://localhost:18095/api/v1/login/enterprise-oidc/callback")
    new = config.GoogleOAuthConfig(True, "new-client", "new-secret", old.redirect_uri)
    state = "state." + config.google_oauth_fingerprint(old)
    monkeypatch.setattr(config, "load_google_oauth_config", lambda: new)
    monkeypatch.setattr(login, "consume_enterprise_oidc_state", lambda **_: SimpleNamespace(purpose="login", nonce="nonce"))
    exchange = MagicMock()
    monkeypatch.setattr(login, "exchange_authorization_code", exchange)
    monkeypatch.setattr(login, "create_login_log", lambda **_: None)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "server": ("localhost", 80), "scheme": "http"})
    response = login.complete_enterprise_oidc_login(request=request, session=MagicMock(), code="code", state=state)
    assert response.headers["location"] == "/auth/login?google_error=login_failed"
    exchange.assert_not_called()


def test_google_config_rotated_during_provider_exchange_is_rejected(monkeypatch):
    monkeypatch.setattr(login.settings, "APP_EDITION", "esop")
    original = config.GoogleOAuthConfig(True, "old-client", "old-secret", "http://localhost:18095/api/v1/login/enterprise-oidc/callback")
    changed = config.GoogleOAuthConfig(True, "new-client", "new-secret", original.redirect_uri)
    state = "state." + config.google_oauth_fingerprint(original)
    monkeypatch.setattr(config, "load_google_oauth_config", lambda: original)
    monkeypatch.setattr(config, "lock_and_load_google_oauth_config", lambda _session: changed)
    monkeypatch.setattr(login, "consume_enterprise_oidc_state", lambda **_: SimpleNamespace(purpose="login", nonce="nonce", code_verifier="verifier"))
    monkeypatch.setattr(login, "get_oidc_provider_metadata", lambda **_: {})
    monkeypatch.setattr(login, "exchange_authorization_code", lambda **_: "id-token")
    monkeypatch.setattr(login, "validate_identity_token", lambda **_: {"sub": "subject", "email": "user@gmail.com", "email_verified": True})
    resolve = MagicMock()
    monkeypatch.setattr(login, "resolve_enterprise_oidc_user", resolve)
    monkeypatch.setattr(login, "create_login_log", lambda **_: None)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "server": ("localhost", 80), "scheme": "http"})
    response = login.complete_enterprise_oidc_login(request=request, session=MagicMock(), code="code", state=state)
    assert response.headers["location"] == "/auth/login?google_error=login_failed"
    resolve.assert_not_called()


def test_google_config_revision_prevents_aba_ticket_reuse():
    a = config.GoogleOAuthConfig(True, "client", "secret", "https://esops.cc/api/v1/login/enterprise-oidc/callback", "revision-a")
    b = config.GoogleOAuthConfig(True, "client", "secret", a.redirect_uri, "revision-b")
    assert config.google_oauth_fingerprint(a) != config.google_oauth_fingerprint(b)
