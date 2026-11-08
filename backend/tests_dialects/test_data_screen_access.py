"""Read-only keys must not become login sessions or bypass live permissions."""

import uuid
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import pytest
from fastapi import HTTPException

from app.api.deps import get_user_from_token_payload
from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.models import TokenPayload
from app.platform import view_access


@pytest.fixture
def owner(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), is_active=True, hashed_password="test-hash")
    tenant = uuid.uuid4()
    session = Mock()
    session.get.return_value = user
    monkeypatch.setattr(
        view_access, "PlatformTenantUnitOfWork", lambda *_: nullcontext()
    )
    monkeypatch.setattr(
        view_access, "get_active_tenant_membership", lambda **_: (None, None)
    )
    monkeypatch.setattr(
        view_access, "evaluate_module_access", lambda **_: SimpleNamespace(allowed=True)
    )
    monkeypatch.setattr(view_access, "user_has_permission", lambda **_: True)
    return session, user, tenant


def issue(owner):
    session, user, tenant = owner
    return view_access.issue_view_key(
        session=session,
        user_id=user.id,
        tenant_id=tenant,
        audience="esop:data-screen",
        module="esop",
        permission="dashboard:view",
    )[0]


def resolve(owner, key):
    return view_access.resolve_view_key(
        session=owner[0],
        key=key,
        audience="esop:data-screen",
        module="esop",
        permission="dashboard:view",
    )


def test_key_is_user_and_tenant_bound_but_not_a_login_token(owner):
    key = issue(owner)
    assert resolve(owner, key) == owner[2]
    payload = jwt.decode(
        key, settings.SECRET_KEY, algorithms=["HS256"], audience="esop:data-screen"
    )
    assert payload["owner"] == str(owner[1].id)
    assert "sub" not in payload and "jti" not in payload
    with pytest.raises(HTTPException):
        get_user_from_token_payload(
            session=owner[0], token_data=TokenPayload(**payload)
        )


@pytest.mark.parametrize("kind", ["tampered", "expired", "audience", "missing-claim"])
def test_invalid_keys_are_rejected(owner, kind):
    key = issue(owner)
    if kind == "tampered":
        key = key[:10] + ("A" if key[10] != "A" else "B") + key[11:]
    else:
        payload = jwt.decode(
            key, settings.SECRET_KEY, algorithms=["HS256"], audience="esop:data-screen"
        )
        if kind == "expired":
            payload["exp"] = get_datetime_utc() - timedelta(seconds=10)
        if kind == "audience":
            payload["aud"] = "another-view"
        if kind == "missing-claim":
            payload.pop("tenant")
        key = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(HTTPException) as error:
        resolve(owner, key)
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "revoked", ["password", "disabled", "membership", "permission", "module"]
)
def test_live_revocation_is_checked(owner, monkeypatch, revoked):
    key = issue(owner)
    if revoked == "password":
        owner[1].hashed_password = "new-hash"
    if revoked == "disabled":
        owner[1].is_active = False
    if revoked == "membership":
        monkeypatch.setattr(
            view_access, "get_active_tenant_membership", lambda **_: None
        )
    if revoked == "permission":
        monkeypatch.setattr(view_access, "user_has_permission", lambda **_: False)
    if revoked == "module":
        monkeypatch.setattr(
            view_access,
            "evaluate_module_access",
            lambda **_: SimpleNamespace(
                allowed=False, error_code="TENANT_MODULE_DISABLED"
            ),
        )
    with pytest.raises(HTTPException) as error:
        resolve(owner, key)
    assert error.value.status_code == 403
