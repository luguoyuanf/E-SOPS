import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes import login
from app.core.cache import redis_cache
from app.core.clock import get_datetime_utc
from app.core.security import get_password_hash, verify_password
from app.core.tenancy_constants import DEFAULT_TENANT_CODE, DEFAULT_TENANT_ID
from app.platform.core.identity_models import (
    PasswordRecoveryReset,
    PasswordRecoverySend,
    User,
    UserSession,
)
from app.platform.core.tenancy_models import Tenant, TenantMembership
from app.platform.infra import password_recovery as recovery
from app.platform.infra.registration_email import hash_code, verification_keys
from app.platform.tenant_uow import PlatformGlobalUnitOfWork, PlatformTenantUnitOfWork
from tests.mysql.test_official_channel import session as database_session

session = database_session


@pytest.fixture
def target(session):
    with PlatformGlobalUnitOfWork(session):
        user = User(
            email=uuid.uuid4().hex + "@example.com",
            hashed_password=get_password_hash("Original-only-42!"),
            is_active=True,
        )
        session.add(user)
        session.flush()
        membership = TenantMembership(
            user_id=user.id, tenant_id=DEFAULT_TENANT_ID, is_active=True
        )
        session.add(membership)
        session.flush()
        with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
            current = UserSession(
                user_id=user.id,
                tenant_id=DEFAULT_TENANT_ID,
                token_jti=uuid.uuid4().hex,
                expires_at=get_datetime_utc() + timedelta(hours=1),
            )
            session.add(current)
            session.flush()
        yield user, membership, current


def issue_proof(session, user):
    purpose = f"password-reset:{DEFAULT_TENANT_ID}"
    keys = verification_keys(user.email, purpose)
    assert redis_cache.set(
        keys[0], hash_code(user.email, "123456", purpose), ttl_seconds=60
    )
    token = recovery.verify_recovery_code(
        session=session,
        tenant_code=DEFAULT_TENANT_CODE,
        email=user.email,
        code="123456",
    )
    assert redis_cache.get(keys[0]) is None
    redis_cache.delete(*keys)
    return token


def test_reset_is_single_use_and_revokes_sessions(session, target):
    user, _, current = target
    token = issue_proof(session, user)
    try:
        recovery.complete_recovery(
            session=session, reset_token=token, new_password="Updated-only-42!"
        )
        assert verify_password("Updated-only-42!", user.hashed_password)[0]
        assert not verify_password("Original-only-42!", user.hashed_password)[0]
        with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
            assert session.get(UserSession, current.id).revoked_at is not None
        with pytest.raises(HTTPException) as exc:
            recovery.complete_recovery(
                session=session, reset_token=token, new_password="Another-only-42!"
            )
        assert exc.value.status_code == 400
    finally:
        redis_cache.delete(recovery.proof_key(token))


def test_code_is_bound_to_tenant_and_purpose(session, target):
    user, _, _ = target
    baseline = session.get(Tenant, DEFAULT_TENANT_ID)
    other = Tenant(
        code="recovery-other-" + uuid.uuid4().hex[:12],
        name="Other test tenant",
        plan_id=baseline.plan_id,
        initialization_template_id=baseline.initialization_template_id,
    )
    session.add(other)
    session.flush()
    for purpose, tenant in [
        ("register", DEFAULT_TENANT_CODE),
        (f"password-reset:{DEFAULT_TENANT_ID}", other.code),
    ]:
        keys = verification_keys(user.email, purpose)
        assert redis_cache.set(
            keys[0], hash_code(user.email, "123456", purpose), ttl_seconds=60
        )
        try:
            with pytest.raises(HTTPException):
                recovery.verify_recovery_code(
                    session=session, tenant_code=tenant, email=user.email, code="123456"
                )
        finally:
            redis_cache.delete(*keys)


def test_password_change_invalidates_outstanding_proof(session, target):
    user, _, _ = target
    token = issue_proof(session, user)
    user.hashed_password = get_password_hash("Different-only-42!")
    session.add(user)
    session.flush()
    with pytest.raises(HTTPException):
        recovery.complete_recovery(
            session=session, reset_token=token, new_password="Updated-only-42!"
        )
    assert verify_password("Different-only-42!", user.hashed_password)[0]


def test_disabled_membership_rejects_proof(session, target):
    user, membership, _ = target
    token = issue_proof(session, user)
    membership.is_active = False
    session.add(membership)
    session.flush()
    with pytest.raises(HTTPException):
        recovery.complete_recovery(
            session=session, reset_token=token, new_password="Updated-only-42!"
        )
    assert verify_password("Original-only-42!", user.hashed_password)[0]


def test_mismatched_passwords_do_not_consume_proof(session, target):
    user, _, _ = target
    token = issue_proof(session, user)
    try:
        with pytest.raises(HTTPException) as exc:
            login.reset_password_by_email_code(
                session=session,
                body=PasswordRecoveryReset(
                    reset_token=token,
                    new_password="Updated-only-42!",
                    confirm_password="Different-only-42!",
                ),
            )
        assert exc.value.detail == "Passwords do not match"
        assert redis_cache.get_json(recovery.proof_key(token))
    finally:
        redis_cache.delete(recovery.proof_key(token))


def test_send_requires_captcha_and_unknown_account_is_generic(session, monkeypatch):
    sent = []
    monkeypatch.setattr(
        recovery, "send_registration_code", lambda **kwargs: sent.append(kwargs)
    )
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    body = PasswordRecoverySend(
        tenant_code=DEFAULT_TENANT_CODE,
        email="nonexistent-" + uuid.uuid4().hex + "@example.com",
        captcha_verification="invalid-proof",
    )
    monkeypatch.setattr(
        login, "validate_slider_captcha_verification", lambda value: False
    )
    with pytest.raises(HTTPException):
        login.send_password_recovery_code(request=request, session=session, body=body)
    monkeypatch.setattr(
        login, "validate_slider_captcha_verification", lambda value: True
    )
    assert (
        login.send_password_recovery_code(
            request=request, session=session, body=body
        ).retry_after_seconds
        == 60
    )
    assert len(sent) == 1 and sent[0]["deliver"] is False


def test_code_consumption_does_not_delete_a_newer_challenge():
    key = redis_cache.build_key("password-recovery-test", uuid.uuid4().hex)
    try:
        assert redis_cache.set(key, "new-challenge", ttl_seconds=60)
        assert redis_cache.consume(key, expected_value="old-challenge") is None
        assert redis_cache.get(key) == "new-challenge"
        assert redis_cache.consume(key, expected_value="new-challenge") == "new-challenge"
        assert redis_cache.get(key) is None
    finally:
        redis_cache.delete(key)
