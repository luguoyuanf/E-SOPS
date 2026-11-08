from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import get_current_tenant_context, get_user_from_token_payload
from app.core.clock import get_datetime_utc
from app.models import TokenPayload
from app.platform.core.identity_models import User, UserSession
from app.platform.core.tenancy_models import Tenant, TenantMembership, TenantProfile
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)


@pytest.fixture
def identity():
    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine, expire_on_commit=False) as s:
        tenant = Tenant(code="auth", name="Auth")
        user = User(email="auth@example.com", hashed_password="unused")
        session = UserSession(
            user_id=user.id,
            tenant_id=tenant.id,
            token_jti="auth-test",
            expires_at=get_datetime_utc() + timedelta(hours=1),
        )
        membership = TenantMembership(user_id=user.id, tenant_id=tenant.id)
        s.add_all([tenant, user, session, membership])
        s.commit()
        yield engine, user.id, tenant.id, session.id, (user.id, tenant.id)


def request(engine, user_id, tenant_id):
    token = TokenPayload(sub=str(user_id), jti="auth-test", tenant_id=tenant_id)
    with Session(engine) as s:
        user = get_user_from_token_payload(session=s, token_data=token)
        return get_current_tenant_context(
            session=s, current_user=user, token_data=token
        )


def test_one_session_read_and_no_heartbeat_write_for_recent_activity(identity):
    engine, user_id, tenant_id, *_ = identity
    sql = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        sql.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert request(engine, user_id, tenant_id).tenant_id == tenant_id
        assert sum("FROM usersession" in statement for statement in sql) == 1
        assert not any(statement.startswith("UPDATE") for statement in sql)
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_stale_heartbeat_is_updated_once_then_throttled(identity):
    engine, user_id, tenant_id, session_id, _ = identity
    with Session(engine) as s:
        row = s.get(UserSession, session_id)
        row.last_active_at = get_datetime_utc() - timedelta(minutes=2)
        s.commit()
    request(engine, user_id, tenant_id)
    with Session(engine) as s:
        first = s.get(UserSession, session_id).last_active_at
    request(engine, user_id, tenant_id)
    with Session(engine) as s:
        assert s.get(UserSession, session_id).last_active_at == first


@pytest.mark.parametrize(
    "state",
    [
        "revoked",
        "expired",
        "user_disabled",
        "tenant_disabled",
        "membership_disabled",
        "service_expired",
    ],
)
def test_every_new_request_rejects_changed_security_state(identity, state):
    engine, user_id, tenant_id, session_id, membership_id = identity
    assert request(engine, user_id, tenant_id)
    with Session(engine) as s:
        if state == "revoked":
            s.get(UserSession, session_id).revoked_at = get_datetime_utc()
        elif state == "expired":
            s.get(UserSession, session_id).expires_at = get_datetime_utc() - timedelta(
                seconds=1
            )
        elif state == "user_disabled":
            s.get(User, user_id).is_active = False
        elif state == "tenant_disabled":
            s.get(Tenant, tenant_id).is_active = False
        elif state == "membership_disabled":
            s.get(TenantMembership, membership_id).is_active = False
        else:
            s.add(
                TenantProfile(
                    tenant_id=tenant_id,
                    service_expires_at=get_datetime_utc() - timedelta(days=1),
                )
            )
        s.commit()
    with pytest.raises(HTTPException) as error:
        request(engine, user_id, tenant_id)
    assert error.value.status_code == 403
