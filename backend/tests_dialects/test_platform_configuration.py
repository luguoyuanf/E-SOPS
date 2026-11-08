"""Platform configuration is shared; stored files remain tenant-owned."""

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import deps
from app.api.routes import settings as settings_routes
from app.core.tenancy import TenantContext
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.platform.bootstrap_configuration import seed_settings, seed_storage_channels
from app.platform.core.configuration_models import SystemSetting
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import Tenant, TenantPlan
from app.platform.infra import files_router, storage_impl
from app.platform.infra.file_models import FileAsset, FileStorageChannel
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)
from app.platform.tenant_uow import activate_platform_tenant_scope


@pytest.fixture
def configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_impl.settings, "STORAGE_PROVIDER", "local")
    import_platform_model_groups()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine) as session:
        plan = TenantPlan(code="shared", name="Shared")
        platform = Tenant(id=DEFAULT_TENANT_ID, code="default", name="Platform")
        tenant = Tenant(code="customer", name="Customer", plan_id=plan.id)
        user = User(
            email="config@example.com", hashed_password="unused", is_superuser=True
        )
        session.add_all([plan, platform, tenant, user])
        session.commit()
        seed_settings(session=session, tenant=platform)
        seed_storage_channels(session=session, tenant=platform)
        session.add(
            SystemSetting(
                tenant_id=tenant.id,
                key="upload.allowed_extensions",
                name="Legacy",
                value="exe",
            )
        )
        session.add(
            FileStorageChannel(
                tenant_id=tenant.id,
                name="Legacy",
                code="legacy",
                provider="s3",
                bucket="wrong",
                is_default=True,
            )
        )
        session.commit()
        monkeypatch.setattr(storage_impl.settings, "UPLOAD_DIR", str(tmp_path))
        # Even an explicitly granted permission must not grant config administration.
        monkeypatch.setattr(deps, "user_has_permission", lambda **_: True)
        app = FastAPI()
        app.include_router(settings_routes.router)
        app.include_router(files_router.router)

        def context():
            activate_platform_tenant_scope(session, tenant.id)
            return TenantContext(
                tenant_id=tenant.id, tenant_code=tenant.code, user_id=user.id
            )

        app.dependency_overrides[deps.get_db] = lambda: session
        app.dependency_overrides[deps.get_current_user] = lambda: user
        app.dependency_overrides[deps.get_current_tenant_context] = context
        app.dependency_overrides[deps.get_public_tenant_id] = lambda: (
            context().tenant_id
        )
        app.dependency_overrides[deps.get_optional_tenant_id] = lambda: (
            context().tenant_id
        )
        app.dependency_overrides[deps.get_optional_current_user] = lambda: user
        with TestClient(app) as client:
            yield session, client, platform, tenant, user
    engine.dispose()


def test_new_tenant_does_not_seed_configuration(configuration):
    session, _, _, tenant, _ = configuration
    before_settings = len(session.exec(select(SystemSetting)).all())
    before_channels = len(session.exec(select(FileStorageChannel)).all())
    seed_settings(session=session, tenant=tenant)
    seed_storage_channels(session=session, tenant=tenant)
    assert len(session.exec(select(SystemSetting)).all()) == before_settings
    assert len(session.exec(select(FileStorageChannel)).all()) == before_channels


def test_root_sees_and_updates_only_platform_configuration(configuration):
    session, client, _, tenant, _ = configuration
    for path in ("/settings", "/files/storage-channels"):
        for query in ({}, {"tenant_id": str(tenant.id)}):
            response = client.get(path, params=query)
            assert response.status_code == 200, response.text
            assert {row["tenant_id"] for row in response.json()["items"]} == {
                str(DEFAULT_TENANT_ID)
            }
    response = client.patch("/settings/system.name", json={"value": "Shared platform"})
    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == str(DEFAULT_TENANT_ID)
    assert (
        client.patch(
            "/files/upload-config", json={"allowed_extensions": "txt", "max_size_mb": 1}
        ).status_code
        == 200
    )
    assert client.get("/files/upload-config").json()["allowed_extensions"] == "txt"
    assert client.get("/settings/public").json()[0:]
    assert {row["tenant_id"] for row in client.get("/settings/public").json()} == {
        str(DEFAULT_TENANT_ID)
    }
    channel = client.post(
        "/files/storage-channels", json={"code": "new", "name": "New"}
    )
    assert channel.status_code == 200, channel.text
    assert channel.json()["tenant_id"] == str(DEFAULT_TENANT_ID)
    channel_id = channel.json()["id"]
    assert (
        client.patch(
            f"/files/storage-channels/{channel_id}", json={"name": "Updated"}
        ).status_code
        == 200
    )
    assert client.post(f"/files/storage-channels/{channel_id}/test").status_code == 200
    assert client.delete(f"/files/storage-channels/{channel_id}").status_code == 204
    assert session.info["platform_tenant_id"] == tenant.id


def test_tenant_configuration_management_denied_even_with_permission(configuration):
    session, client, _, _, user = configuration
    channel_id = client.get("/files/storage-channels").json()["items"][0]["id"]
    user.is_superuser = False
    session.commit()
    requests = [
        ("GET", "/settings", None),
        ("PATCH", "/settings/system.name", {"value": "Hacked"}),
        ("GET", "/files/storage-channels", None),
        ("POST", "/files/storage-channels", {"name": "Bad", "code": "bad"}),
        ("PATCH", f"/files/storage-channels/{channel_id}", {"name": "Bad"}),
        ("POST", f"/files/storage-channels/{channel_id}/test", None),
        ("DELETE", f"/files/storage-channels/{channel_id}", None),
        ("GET", "/files/upload-config", None),
        ("PATCH", "/files/upload-config", {"max_size_mb": 100}),
    ]
    for method, path, body in requests:
        response = client.request(method, path, json=body)
        assert response.status_code == 403, (method, path, response.text)


def test_shared_upload_configuration_preserves_file_tenant_and_scope(configuration):
    session, client, _, tenant, user = configuration
    assert (
        client.patch(
            "/files/upload-config", json={"allowed_extensions": "txt", "max_size_mb": 1}
        ).status_code
        == 200
    )
    user.is_superuser = False
    session.commit()
    config = client.get("/files/storage-config")
    assert config.status_code == 200, config.text
    assert config.json()["provider"] == "local"
    assert config.json()["allowed_extensions"] == "txt"
    response = client.post(
        "/files/upload",
        files={"file": ("hello.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 200, response.text
    file = response.json()
    assert file["tenant_id"] == str(tenant.id)
    assert f"tenants/{tenant.id}/" in file["storage_path"]
    assert file["storage_provider"] == "local"
    assert client.get(f"/files/{file['id']}/download").content == b"hello"
    assert session.info["platform_tenant_id"] == tenant.id
    for name, body in (("bad.exe", b"bad"), ("big.txt", b"x" * (1024 * 1024 + 1))):
        assert (
            client.post("/files/upload", files={"file": (name, body)}).status_code
            == 400
        )
    assert len(session.exec(select(FileAsset)).all()) == 1
    other = Tenant(code="other", name="Other")
    session.add(other)
    session.commit()
    activate_platform_tenant_scope(session, other.id, privileged=True)
    assert session.exec(select(FileAsset)).all() == []
    other_context = TenantContext(
        tenant_id=other.id, tenant_code=other.code, user_id=user.id
    )
    client.app.dependency_overrides[deps.get_current_tenant_context] = lambda: (
        other_context
    )
    client.app.dependency_overrides[deps.get_optional_tenant_id] = lambda: other.id
    assert client.get("/files").json()["items"] == []
    assert client.get(f"/files/{file['id']}").status_code == 404
    assert client.get(f"/files/{file['id']}/download").status_code == 404


@pytest.mark.parametrize("provider", ["s3", "oss"])
def test_shared_object_storage_upload_download_and_delete(
    configuration, monkeypatch, provider
):
    session, client, _, tenant, user = configuration
    channel = client.get("/files/storage-channels").json()["items"][0]
    assert (
        client.patch(
            f"/files/storage-channels/{channel['id']}",
            json={
                "provider": provider,
                "bucket": "platform-bucket",
                "object_prefix": "shared",
            },
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/files/upload-config", json={"allowed_extensions": "txt"}
        ).status_code
        == 200
    )
    objects = {}

    class S3:
        def head_bucket(self, *, Bucket):
            assert Bucket == "platform-bucket"

        def upload_fileobj(self, source, bucket, path, **_):
            assert bucket == "platform-bucket"
            objects[path] = source.read()

        def get_object(self, *, Bucket, Key):
            assert Bucket == "platform-bucket"
            return {"Body": io.BytesIO(objects[Key])}

        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            assert operation == "get_object" and Params["Bucket"] == "platform-bucket"
            assert ExpiresIn >= 60
            return "https://example.invalid/signed-download"

        def delete_object(self, *, Bucket, Key):
            assert Bucket == "platform-bucket"
            del objects[Key]

    def client_for_channel(channel):
        assert channel.tenant_id == DEFAULT_TENANT_ID
        assert channel.bucket == "platform-bucket"
        return S3()

    monkeypatch.setattr(storage_impl, "_get_s3_client", client_for_channel)
    monkeypatch.setattr(files_router, "_get_s3_client", client_for_channel)
    assert (
        client.post(f"/files/storage-channels/{channel['id']}/test").status_code == 200
    )
    user.is_superuser = False
    session.commit()
    response = client.post(
        "/files/upload", files={"file": ("shared.txt", b"shared s3")}
    )
    assert response.status_code == 200, response.text
    file = response.json()
    assert file["tenant_id"] == str(tenant.id)
    assert file["storage_provider"] == provider
    assert file["storage_path"].startswith(f"shared/tenants/{tenant.id}/")
    assert client.get(f"/files/{file['id']}/download").content == b"shared s3"
    signed = client.get(f"/files/{file['id']}/download-url")
    assert signed.status_code == 200, signed.text
    assert signed.json()["url"] == "https://example.invalid/signed-download"
    assert signed.json()["expires_in"] >= 60
    assert client.delete(f"/files/{file['id']}").status_code == 204
    assert not objects
    assert session.info["platform_tenant_id"] == tenant.id


def test_oss_deployment_cannot_fall_back_to_local_uploads(configuration, monkeypatch):
    session, _, _, tenant, _ = configuration
    monkeypatch.setattr(storage_impl.settings, "STORAGE_PROVIDER", "oss")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        storage_impl.get_default_storage_channel(session, tenant.id)
    assert error.value.status_code == 503


def test_oss_apk_download_link_keeps_authentication(configuration):
    session, client, _, tenant, user = configuration
    asset = FileAsset(
        tenant_id=tenant.id,
        original_name="app.apk",
        stored_name="app.apk",
        storage_provider="oss",
        storage_path="uploads/tenants/test/app.apk",
        content_type="application/vnd.android.package-archive",
        size=1,
        sha256="0" * 64,
        uploader_id=user.id,
    )
    session.add(asset)
    session.commit()
    response = client.get(f"/files/{asset.id}/download-url")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "url": f"/api/v1/files/{asset.id}/download",
        "expires_in": None,
    }


def test_channel_secret_detail_is_root_only_and_not_cached(configuration):
    session, client, _, tenant, user = configuration
    row = FileStorageChannel(
        tenant_id=DEFAULT_TENANT_ID,
        code="secret-test",
        name="Secret test",
        secret_access_key="synthetic-secret-value",
    )
    session.add(row)
    session.commit()
    channel_id = row.id
    response = client.get(f"/files/storage-channels/{channel_id}")
    assert response.status_code == 200, response.text
    assert response.json()["secret_access_key"] == "synthetic-secret-value"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    listed = client.get("/files/storage-channels").json()["items"]
    assert (
        next(item for item in listed if item["id"] == str(channel_id))[
            "secret_access_key"
        ]
        == "******"
    )
    foreign = FileStorageChannel(
        tenant_id=tenant.id,
        code="foreign",
        name="Foreign",
        secret_access_key="foreign-secret",
    )
    session.add(foreign)
    session.commit()
    assert client.get(f"/files/storage-channels/{foreign.id}").status_code == 404
    user.is_superuser = False
    session.commit()
    assert client.get(f"/files/storage-channels/{channel_id}").status_code == 403
