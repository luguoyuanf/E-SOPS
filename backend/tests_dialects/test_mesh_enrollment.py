"""Authenticated native-device enrollment with no shared APK secret."""

import json
import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import get_db
from app.core.clock import get_datetime_utc
from app.modules.esop import mesh_routes
from app.modules.esop.application import mesh_enrollment as service
from app.modules.esop.infrastructure.device_auth import _digest
from app.modules.esop.infrastructure.models import DeviceCredential, Terminal
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.mesh_dto import MeshEnrollmentPublic


@pytest.fixture(autouse=True)
def issuer_config(monkeypatch):
    monkeypatch.setenv("ESOPS_MESH_CONTROL_URL", "https://mesh.example.test")
    monkeypatch.setenv("ESOPS_HEADSCALE_URL", "http://headscale.test:8080")
    monkeypatch.setenv("ESOPS_HEADSCALE_API_KEY", "test-admin-api-secret")
    monkeypatch.setenv("ESOPS_HEADSCALE_USER_ID", "2")
    with service._rate_lock:
        service._recent_devices.clear()


@pytest.fixture
def device_api(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[Terminal.__table__, DeviceCredential.__table__])
    tenant_id, terminal_id = uuid.uuid4(), uuid.uuid4()
    tokens = {"native": "a" * 64, "web": "b" * 64, "revoked": "c" * 64}
    with Session(engine) as session:
        with EsopTenantUnitOfWork(session, tenant_id):
            for kind, token in tokens.items():
                device_id = terminal_id if kind == "native" else uuid.uuid4()
                code = "WEB" if kind == "web" else f"test-{kind}"
                session.add(Terminal(
                    id=device_id, tenant_id=tenant_id, device_code=code,
                    is_active=kind != "revoked",
                ))
                session.add(DeviceCredential(
                    device_code=f"web:{tenant_id}" if kind == "web" else code,
                    terminal_id=device_id, tenant_id=tenant_id,
                    token_hash=_digest(f"token:{token}"),
                ))
        session.commit()

    def session_dependency():
        with Session(engine) as session:
            yield session

    checked = []

    def allow_module(**kwargs):
        checked.append((kwargs["tenant_id"], kwargs["module_code"]))

    monkeypatch.setattr(mesh_routes, "require_resolved_tenant_module_access", allow_module)
    monkeypatch.setattr(
        "app.modules.esop.infrastructure.device_auth.require_resolved_tenant_module_access",
        allow_module,
    )
    app = FastAPI()
    app.include_router(mesh_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = session_dependency
    with TestClient(app) as client:
        yield client, tokens, tenant_id, terminal_id, checked
    engine.dispose()


def test_missing_unknown_and_revoked_credentials_are_rejected(device_api, monkeypatch):
    client, tokens, *_ = device_api
    monkeypatch.setattr(mesh_routes, "issue_enrollment", lambda *_: pytest.fail("Unauthorized issuance"))
    path = "/api/v1/esop/terminal/mesh-enrollment"
    for token in (None, "invalid", "d" * 64, tokens["revoked"]):
        headers = {} if token is None else {"X-Device-Token": token}
        assert client.post(path, headers=headers).status_code == 401


def test_web_device_cannot_request_mesh_credential(device_api, monkeypatch):
    client, tokens, *_ = device_api
    monkeypatch.setattr(mesh_routes, "issue_enrollment", lambda *_: pytest.fail("Web issuance"))
    assert client.post(
        "/api/v1/esop/terminal/mesh-enrollment", headers={"X-Device-Token": tokens["web"]},
    ).status_code == 403


def test_trusted_identity_scopes_issuance_and_secret_response_is_not_cached(device_api, monkeypatch):
    client, tokens, tenant_id, terminal_id, checked = device_api
    calls = []

    def issue(tenant, terminal):
        calls.append((tenant, terminal))
        return MeshEnrollmentPublic(
            controlUrl="https://mesh.example.test", authKey="hskey-auth-test-only",
            expiresAt=get_datetime_utc() + timedelta(minutes=10),
        )

    monkeypatch.setattr(mesh_routes, "issue_enrollment", issue)
    response = client.post(
        "/api/v1/esop/terminal/mesh-enrollment?tenantId=forged&tags=tag:maintenance",
        headers={"X-Device-Token": tokens["native"]},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert calls == [(tenant_id, terminal_id)]
    assert checked == [(tenant_id, "esop")]
    assert set(response.json()) == {"controlUrl", "authKey", "expiresAt"}
    injected = client.post(
        "/api/v1/esop/terminal/mesh-enrollment",
        headers={"X-Device-Token": tokens["native"]},
        json={"tenantId": str(uuid.uuid4()), "tags": ["tag:maintenance"]},
    )
    assert injected.status_code == 422
    assert len(calls) == 1


def test_disabled_module_is_rejected_before_issuance(device_api, monkeypatch):
    client, tokens, *_ = device_api

    def deny(**_):
        raise HTTPException(status_code=403, detail="MODULE_DISABLED")

    monkeypatch.setattr(mesh_routes, "require_resolved_tenant_module_access", deny)
    monkeypatch.setattr(mesh_routes, "issue_enrollment", lambda *_: pytest.fail("Disabled issuance"))
    response = client.post(
        "/api/v1/esop/terminal/mesh-enrollment", headers={"X-Device-Token": tokens["native"]},
    )
    assert response.status_code == 403


def test_headscale_request_is_single_use_terminal_only_and_ten_minutes(monkeypatch):
    requests = []
    original_client = httpx.Client

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={"preAuthKey": {
            "key": "hskey-auth-test-issued", "expiration": body["expiration"],
            "aclTags": ["tag:terminal"],
        }})

    monkeypatch.setattr(service.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    before = get_datetime_utc()
    result = service.issue_enrollment(uuid.uuid4(), uuid.uuid4())
    request = requests[0]
    body = json.loads(request.content)
    assert request.url == "http://headscale.test:8080/api/v1/preauthkey"
    assert request.headers["authorization"] == "Bearer test-admin-api-secret"
    assert body["user"] == "2"
    assert body["reusable"] is False and body["ephemeral"] is False
    assert body["aclTags"] == ["tag:terminal"]
    assert before + timedelta(minutes=9, seconds=59) < result.expiresAt < before + timedelta(minutes=10, seconds=1)
    assert result.authKey == "hskey-auth-test-issued"
    assert "test-admin-api-secret" not in result.model_dump_json()


def test_repeat_requests_are_limited_without_retaining_keys(monkeypatch):
    original_client = httpx.Client
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"preAuthKey": {
            "key": "hskey-auth-test-issued", "expiration": json.loads(request.content)["expiration"],
            "aclTags": ["tag:terminal"],
        }})

    monkeypatch.setattr(service.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    tenant_id, device_id = uuid.uuid4(), uuid.uuid4()
    service.issue_enrollment(tenant_id, device_id)
    with pytest.raises(HTTPException) as repeated:
        service.issue_enrollment(tenant_id, device_id)
    assert repeated.value.status_code == 429
    assert repeated.value.headers["Retry-After"] == "60"
    assert len(calls) == 1
    assert all(isinstance(value, float) for value in service._recent_devices.values())


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="test-admin-api-secret hskey-auth-DO-NOT-EXPOSE"),
    httpx.Response(200, json={"preAuthKey": {"key": "hskey-auth-unbounded", "expiration": "9999-12-31T23:59:59Z"}}),
    httpx.Response(200, json={}),
])
def test_upstream_errors_and_unbounded_credentials_fail_closed(monkeypatch, response):
    original_client = httpx.Client
    monkeypatch.setattr(service.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda _: response), **kwargs,
    ))
    with pytest.raises(HTTPException) as failed:
        service.issue_enrollment(uuid.uuid4(), uuid.uuid4())
    assert failed.value.status_code == 503
    assert failed.value.detail == "Terminal mesh enrollment unavailable"
    assert "secret" not in str(failed.value.detail) and "hskey" not in str(failed.value.detail)
