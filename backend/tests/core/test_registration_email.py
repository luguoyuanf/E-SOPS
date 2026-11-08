import uuid

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from app.api.routes import login
from app.core.config import settings
from app.platform.core.identity_models import RegistrationEmailCodeRequest
from app.platform.core.tenancy_models import TenantRegistrationRequest
from app.platform.infra import registration_email as email_service


@pytest.fixture
def delivery(monkeypatch):
    values = {}
    ttls = {}
    sent = []

    def put(key, value, *, ttl_seconds):
        values[key] = value
        ttls[key] = ttl_seconds
        return True

    def incr(key, *, ttl_seconds):
        values[key] = int(values.get(key, 0)) + 1
        ttls.setdefault(key, ttl_seconds)
        return values[key]

    monkeypatch.setattr(settings, "RESEND_API_KEY", SecretStr("test-placeholder"))
    monkeypatch.setattr(email_service.redis_cache, "is_enabled", lambda: True)
    monkeypatch.setattr(email_service.redis_cache, "set", put)
    monkeypatch.setattr(email_service.redis_cache, "incr", incr)
    monkeypatch.setattr(email_service.redis_cache, "get", values.get)
    monkeypatch.setattr(
        email_service.redis_cache,
        "delete",
        lambda *keys: [values.pop(k, None) for k in keys],
    )
    monkeypatch.setattr(email_service.secrets, "randbelow", lambda _: 123456)

    def send(url, **kwargs):
        sent.append(kwargs["json"])
        return httpx.Response(
            200, json={"id": str(uuid.uuid4())}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(email_service.httpx, "post", send)
    return values, ttls, sent


def test_send_hashes_code_and_blocks_resend(delivery):
    values, ttls, sent = delivery
    email_service.send_registration_code(
        email="owner@example.com", client_ip="127.0.0.1"
    )
    code_key, _, cooldown = email_service.verification_keys("owner@example.com")
    assert values[code_key] == email_service.hash_code("owner@example.com", "123456")
    assert "123456" not in values[code_key]
    assert ttls[code_key] == 300 and ttls[cooldown] == 60
    assert sent[0]["to"] == ["owner@example.com"]
    with pytest.raises(HTTPException) as exc:
        email_service.send_registration_code(
            email="OWNER@example.com", client_ip="127.0.0.1"
        )
    assert exc.value.status_code == 429 and len(sent) == 1


def test_code_bound_to_email_expiry_and_attempt_limit(delivery):
    values, _, _ = delivery
    email_service.send_registration_code(
        email="owner@example.com", client_ip="127.0.0.1"
    )
    key, attempts, _ = email_service.verification_keys("owner@example.com")
    assert email_service.validate_registration_code(
        email="OWNER@example.com", code="123456"
    ) == (key, attempts)
    with pytest.raises(HTTPException):
        email_service.validate_registration_code(
            email="other@example.com", code="123456"
        )
    for _ in range(4):
        with pytest.raises(HTTPException):
            email_service.validate_registration_code(
                email="owner@example.com", code="000000"
            )
    assert key not in values
    with pytest.raises(HTTPException):
        email_service.validate_registration_code(
            email="owner@example.com", code="123456"
        )
    # Missing / expired codes fail closed.
    with pytest.raises(HTTPException):
        email_service.validate_registration_code(
            email="expired@example.com", code="123456"
        )


def test_provider_failure_does_not_leave_valid_code(delivery, monkeypatch):
    values, _, _ = delivery

    def reject(url, **_kwargs):
        return httpx.Response(
            403, json={"message": "provider detail"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(email_service.httpx, "post", reject)
    with pytest.raises(HTTPException) as exc:
        email_service.send_registration_code(
            email="owner@example.com", client_ip="127.0.0.1"
        )
    assert exc.value.detail == email_service.UNAVAILABLE
    assert email_service.verification_keys("owner@example.com")[0] not in values


def test_missing_configuration_and_cache_fail_closed(delivery, monkeypatch):
    assert delivery
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    assert not email_service.email_verification_enabled()
    with pytest.raises(HTTPException) as exc:
        email_service.send_registration_code(
            email="owner@example.com", client_ip="127.0.0.1"
        )
    assert exc.value.status_code == 503
    monkeypatch.setattr(settings, "RESEND_API_KEY", SecretStr("test-placeholder"))
    monkeypatch.setattr(email_service.redis_cache, "incr", lambda *args, **kwargs: None)
    with pytest.raises(HTTPException) as exc:
        email_service.validate_registration_code(
            email="owner@example.com", code="123456"
        )
    assert exc.value.status_code == 503


def test_send_ip_and_daily_limits(delivery):
    values, _, sent = delivery
    for number in range(10):
        email_service.send_registration_code(
            email=f"owner{number}@example.com", client_ip="127.0.0.1"
        )
    with pytest.raises(HTTPException) as exc:
        email_service.send_registration_code(
            email="over@example.com", client_ip="127.0.0.1"
        )
    assert exc.value.status_code == 429 and len(sent) == 10
    values[email_service.redis_cache.build_key("registration-email", "daily-sends")] = (
        90
    )
    with pytest.raises(HTTPException) as exc:
        email_service.send_registration_code(
            email="daily@example.com", client_ip="127.0.0.2"
        )
    assert exc.value.status_code == 429 and len(sent) == 10


def test_schema_requires_proof_and_accepts_email_without_phone():
    fields = {
        "tenant_code": "example-company",
        "tenant_name": "Test company",
        "full_name": "Test owner",
        "email": "owner@example.com",
        "password": "Example-only-42!",
    }
    assert TenantRegistrationRequest(**fields, email_code="123456").mobile is None
    with pytest.raises(ValidationError):
        TenantRegistrationRequest(**fields)
    with pytest.raises(ValidationError):
        TenantRegistrationRequest(**fields, email_code="abcdef")
    with pytest.raises(ValidationError):
        RegistrationEmailCodeRequest(email="invalid", captcha_verification="test-proof")


def test_closed_registration_never_sends(monkeypatch):
    monkeypatch.setattr(login, "is_public_registration_enabled", lambda **kwargs: False)

    def unexpected(**_kwargs):
        pytest.fail("Closed public registration must not send")

    monkeypatch.setattr(login, "send_registration_code", unexpected)
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    with pytest.raises(HTTPException) as exc:
        login.send_registration_email_code(
            request=request,
            session=None,
            body=RegistrationEmailCodeRequest(email="owner@example.com", captcha_verification="test-proof"),
        )
    assert exc.value.status_code == 403


@pytest.mark.parametrize("code", [None, "", "abcd", "1abcd", "Abcde"])
def test_registration_requires_valid_manual_company_code(code):
    fields = {
        "tenant_name": "Company",
        "full_name": "Owner",
        "email": "owner@example.com",
        "password": "Example-only-42!",
        "email_code": "123456",
    }
    if code is not None:
        fields["tenant_code"] = code
    with pytest.raises(ValidationError):
        TenantRegistrationRequest(**fields)


def test_registration_accepts_five_character_company_code():
    data = TenantRegistrationRequest(
        tenant_code="abcde",
        tenant_name="Company",
        full_name="Owner",
        email="owner@example.com",
        password="Example-only-42!",
        email_code="123456",
    )
    assert data.tenant_code == "abcde"


def test_registration_email_requires_slider_verification(monkeypatch):
    sent = []
    monkeypatch.setattr(login, "is_public_registration_enabled", lambda **kwargs: True)
    monkeypatch.setattr(login, "send_registration_code", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr(login, "validate_slider_captcha_verification", lambda proof: False)
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    body = RegistrationEmailCodeRequest(email="owner@example.com", captcha_verification="test-proof")
    with pytest.raises(HTTPException) as exc:
        login.send_registration_email_code(request=request, session=None, body=body)
    assert exc.value.status_code == 400 and not sent
    monkeypatch.setattr(login, "validate_slider_captcha_verification", lambda proof: True)
    assert login.send_registration_email_code(request=request, session=None, body=body).retry_after_seconds == 60
    assert len(sent) == 1
