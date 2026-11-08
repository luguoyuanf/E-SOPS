"""Tenant-bound recovery challenges and single-use password reset proofs."""

import hashlib
import hmac
import secrets
import uuid

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.cache import redis_cache
from app.core.clock import get_datetime_utc
from app.core.security import get_password_hash
from app.core.tenancy import get_active_tenant_membership
from app.platform.core.identity_models import User, UserSession
from app.platform.core.tenancy_models import Tenant, TenantMembership
from app.platform.infra.registration_email import (
    CODE_TTL,
    INVALID_CODE,
    UNAVAILABLE,
    hash_code,
    send_registration_code,
    validate_registration_code,
)
from app.platform.tenant_uow import PlatformTenantUnitOfWork

INVALID_PROOF = "Password recovery verification is invalid or expired"


def find_recovery_user(
    session: Session, tenant_code: str, email: str
) -> tuple[Tenant, User] | None:
    tenant = session.exec(
        select(Tenant).where(
            Tenant.code == tenant_code.strip().lower(), Tenant.is_active
        )
    ).first()
    user = session.exec(
        select(User).where(User.email == email.strip().lower(), User.is_active)
    ).first()
    if (
        not tenant
        or not user
        or not get_active_tenant_membership(
            session=session, user_id=user.id, tenant_id=tenant.id
        )
    ):
        return None
    return tenant, user


def send_recovery_code(
    *, session: Session, tenant_code: str, email: str, client_ip: str
) -> None:
    target = find_recovery_user(session, tenant_code, email)
    tenant = session.exec(
        select(Tenant).where(Tenant.code == tenant_code.strip().lower())
    ).first()
    scope = (
        str(tenant.id)
        if tenant
        else hashlib.sha256(tenant_code.strip().lower().encode()).hexdigest()
    )
    send_registration_code(
        email=email.strip().lower(),
        client_ip=client_ip,
        purpose=f"password-reset:{scope}",
        deliver=target is not None,
    )
    # Unknown accounts share the response and rate limits without receiving mail.


def proof_key(token: str) -> str:
    return redis_cache.build_key(
        "password-reset-proof", hashlib.sha256(token.encode()).hexdigest()
    )


def verify_recovery_code(
    *, session: Session, tenant_code: str, email: str, code: str
) -> str:
    target = find_recovery_user(session, tenant_code, email)
    if not target:
        raise HTTPException(status_code=400, detail=INVALID_CODE)
    tenant, user = target
    email = email.strip().lower()
    purpose = f"password-reset:{tenant.id}"
    key, attempts = validate_registration_code(email=email, code=code, purpose=purpose)
    value = redis_cache.consume(key, expected_value=hash_code(email, code, purpose))
    if not value or not hmac.compare_digest(value, hash_code(email, code, purpose)):
        raise HTTPException(status_code=400, detail=INVALID_CODE)
    token = secrets.token_urlsafe(48)
    if not redis_cache.set_json(
        proof_key(token),
        {
            "user_id": str(user.id),
            "tenant_id": str(tenant.id),
            "password_version": hashlib.sha256(
                user.hashed_password.encode()
            ).hexdigest(),
        },
        ttl_seconds=CODE_TTL,
    ):
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    redis_cache.delete(attempts)
    return token


def complete_recovery(*, session: Session, reset_token: str, new_password: str) -> None:
    proof = redis_cache.consume_json_if(proof_key(reset_token), expected={})
    if not isinstance(proof, dict):
        raise HTTPException(status_code=400, detail=INVALID_PROOF)
    user = session.exec(
        select(User).where(User.id == uuid.UUID(proof["user_id"])).with_for_update()
    ).first()
    tenant_id = uuid.UUID(proof["tenant_id"])
    if (
        not user
        or not user.is_active
        or not get_active_tenant_membership(
            session=session, user_id=user.id, tenant_id=tenant_id
        )
        or not hmac.compare_digest(
            proof["password_version"],
            hashlib.sha256(user.hashed_password.encode()).hexdigest(),
        )
    ):
        raise HTTPException(status_code=400, detail=INVALID_PROOF)
    now = get_datetime_utc()
    user.hashed_password = get_password_hash(new_password)
    user.updated_at = now
    session.add(user)
    # The password belongs to the global account: revoke all tenant sessions atomically.
    tenant_ids = session.exec(
        select(TenantMembership.tenant_id).where(TenantMembership.user_id == user.id)
    ).all()
    for item in tenant_ids:
        with PlatformTenantUnitOfWork(session, item, privileged=True):
            sessions = session.exec(
                select(UserSession).where(
                    UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
                )
            ).all()
            for current in sessions:
                current.revoked_at = now
                session.add(current)
            session.flush()
    session.commit()
