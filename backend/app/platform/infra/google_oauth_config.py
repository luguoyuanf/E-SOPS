"""Read the platform-owned Google OAuth configuration without exposing secrets."""
import hashlib
import hmac
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.core.mfa import decrypt_secret
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.platform.core.identity_models import SocialClient
from app.platform.core.tenancy_models import Tenant
from app.platform.tenant_uow import PlatformTenantUnitOfWork


@dataclass(frozen=True)
class GoogleOAuthConfig:
    enabled: bool
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    revision: str = ""


def google_oauth_fingerprint(config: GoogleOAuthConfig) -> str:
    payload = "\0".join(("https://accounts.google.com", config.client_id, config.client_secret, config.redirect_uri, config.revision))
    return hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def validate_google_redirect(uri: str) -> None:
    parsed = urlsplit(uri)
    expected = urlsplit(settings.FRONTEND_HOST)
    local = settings.ENVIRONMENT == "local" and parsed.hostname in {"localhost", "127.0.0.1"}
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != f"{settings.API_V1_STR}/login/enterprise-oidc/callback" or (not local and (parsed.scheme != "https" or parsed.netloc != expected.netloc)) or (local and parsed.scheme not in {"http", "https"}):
        raise HTTPException(status_code=503, detail="Enterprise OIDC is not configured")


def lock_google_config_anchor(session: Session) -> None:
    # This existing row also serializes the first creation of a configuration record.
    session.exec(select(Tenant.id).where(Tenant.id == DEFAULT_TENANT_ID).with_for_update()).one()


def _load_google_oauth_config(session: Session, *, lock: bool) -> GoogleOAuthConfig:
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        if lock:
            lock_google_config_anchor(session)
        row = session.exec(select(SocialClient).where(
            SocialClient.tenant_id == DEFAULT_TENANT_ID,
            SocialClient.social_type == "google",
            SocialClient.user_type == "platform",
        )).first()
        if row is not None:
            revision = row.remark or f"legacy:{row.id}:{row.updated_at}"
            if not row.is_active:
                return GoogleOAuthConfig(False, row.client_id, "", "", revision)
            if not row.client_id or not row.client_secret or not row.agent_id:
                raise HTTPException(status_code=503, detail="Enterprise OIDC is not configured")
            validate_google_redirect(row.agent_id)
            try:
                secret = decrypt_secret(row.client_secret)
            except ValueError:
                raise HTTPException(status_code=503, detail="Enterprise OIDC is not configured") from None
            return GoogleOAuthConfig(True, row.client_id, secret, row.agent_id, revision)
    # Existing installations remain operational until their platform record is created.
    config = GoogleOAuthConfig(
        bool(settings.ENTERPRISE_OIDC_ENABLED),
        settings.ENTERPRISE_OIDC_CLIENT_ID or "",
        settings.ENTERPRISE_OIDC_CLIENT_SECRET or "",
        settings.ENTERPRISE_OIDC_REDIRECT_URI or "",
        "environment",
    )
    if config.enabled and config.redirect_uri:
        validate_google_redirect(config.redirect_uri)
    return config


def load_google_oauth_config() -> GoogleOAuthConfig:
    # A separate read-only session cannot change an authenticated request's tenant scope.
    with Session(engine) as session:
        return _load_google_oauth_config(session, lock=False)


def lock_and_load_google_oauth_config(session: Session) -> GoogleOAuthConfig:
    """Lock after external OAuth I/O and retain that lock until the caller commits."""
    return _load_google_oauth_config(session, lock=True)
