"""Purpose-bound read-only links, independent of interactive login sessions."""

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta

import jwt
from fastapi import HTTPException
from jwt.exceptions import InvalidTokenError
from sqlmodel import Session

from app.api.deps import MODULE_ACCESS_ERRORS, user_has_permission
from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.core.security import ALGORITHM
from app.core.tenancy import get_active_tenant_membership
from app.modules.access import evaluate_module_access
from app.platform.core.identity_models import User
from app.platform.tenant_uow import PlatformTenantUnitOfWork


def _credential_version(user: User) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"view-key:{user.id}:{user.hashed_password}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _authorize(
    session: Session,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    module: str,
    permission: str,
) -> User:
    user = session.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or get_active_tenant_membership(
            session=session,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        is None
    ):
        raise HTTPException(status_code=403, detail="大屏所属账号或租户已不可用")
    decision = evaluate_module_access(
        session=session, tenant_id=tenant_id, module_code=module
    )
    if not decision.allowed:
        code, detail = MODULE_ACCESS_ERRORS[decision.error_code or "MODULE_UNAVAILABLE"]
        raise HTTPException(status_code=code, detail=detail)
    if not user_has_permission(
        session=session,
        current_user=user,
        tenant_id=tenant_id,
        permission_code=permission,
    ):
        raise HTTPException(status_code=403, detail="大屏所属用户已无查看权限")
    return user


def issue_view_key(
    *,
    session: Session,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    audience: str,
    module: str,
    permission: str,
) -> tuple[str, datetime]:
    with PlatformTenantUnitOfWork(session, tenant_id):
        user = _authorize(session, user_id, tenant_id, module, permission)
        expires_at = get_datetime_utc() + timedelta(days=30)
        # No sub/jti: a view key cannot be used as an interactive account token.
        payload = {
            "aud": audience,
            "owner": str(user.id),
            "tenant": str(tenant_id),
            "credential_version": _credential_version(user),
            "exp": expires_at,
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM), expires_at


def resolve_view_key(
    *, session: Session, key: str, audience: str, module: str, permission: str
) -> uuid.UUID:
    try:
        payload = jwt.decode(
            key,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
            audience=audience,
            options={
                "require": ["aud", "owner", "tenant", "credential_version", "exp"]
            },
        )
        user_id, tenant_id = uuid.UUID(payload["owner"]), uuid.UUID(payload["tenant"])
    except InvalidTokenError, ValueError, TypeError, AttributeError:
        raise HTTPException(
            status_code=403, detail="大屏链接无效或已过期，请从后台重新打开"
        ) from None
    with PlatformTenantUnitOfWork(session, tenant_id):
        user = _authorize(session, user_id, tenant_id, module, permission)
        if not hmac.compare_digest(
            str(payload["credential_version"]), _credential_version(user)
        ):
            raise HTTPException(
                status_code=403, detail="大屏密钥已失效，请从后台重新打开"
            )
    return tenant_id
