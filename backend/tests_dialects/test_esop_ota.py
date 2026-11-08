"""OTA release stays bound to the activated hardware profile."""

import uuid
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.modules.esop.infrastructure.device_auth import activate_device, issue_key
from app.modules.esop.infrastructure.models import (
    ALL_MODELS,
    ActivationKey,
    Channel,
    ChannelCustomerTenant,
    HardwareModel,
    Terminal,
)
from app.modules.esop.infrastructure.registration_activation import (
    DIRECT_A133_ID,
    DIRECT_CHANNEL_ID,
    bind_official_tenant,
    issue_free_key,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.ota_routes import (
    create_channel,
    create_hardware_model,
    create_ota_package,
    publish_ota_package,
    terminal_ota,
    update_hardware_model,
)
from app.modules.esop.public_api.ota_dto import (
    ChannelInput,
    HardwareInput,
    OtaPackageInput,
)
from app.platform.public_api.files import FileAssetSummary
from app.platform.web_api import Principal


class Files:
    def __init__(self, tenant_id: uuid.UUID, file_id: uuid.UUID) -> None:
        self.tenant_id, self.file_id = tenant_id, file_id

    def get_accessible_file(self, *, tenant_id: uuid.UUID, file_id: uuid.UUID):
        if (tenant_id, file_id) != (self.tenant_id, self.file_id):
            return None
        return FileAssetSummary(
            id=file_id, original_name="device.apk", content_type="application/vnd.android.package-archive",
            size=123, sha256="a" * 64,
        )


@pytest.fixture(autouse=True)
def activation_cipher(monkeypatch):
    monkeypatch.setattr(settings, "ESOP_ACTIVATION_CIPHER_KEY", Fernet.generate_key().decode())


def test_ota_manifest_matches_channel_model_and_active_release(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS])
    tenant, file_id = uuid.uuid4(), uuid.uuid4()
    admin = Principal(id=uuid.uuid4(), is_superuser=True)
    monkeypatch.setattr("app.platform.web_api.resolve_channel_customer_code",
        lambda **kwargs: SimpleNamespace(id=tenant, code="test-tenant", name="Test"))
    monkeypatch.setattr("app.modules.esop.ota_routes.get_authorized_file",
        lambda **kwargs: Files(tenant, file_id).get_accessible_file(tenant_id=tenant, file_id=file_id))
    with Session(engine) as session:
        channel = create_channel(session, admin, ChannelInput(code="C1", name="渠道一"))
        hardware = create_hardware_model(session, admin, HardwareInput(
            channel_id=channel.id, code="A133", name="A133", abi="arm64-v8a",
        ))
        session.add(ChannelCustomerTenant(channel_id=channel.id, tenant_id=tenant, created_by=admin.id))
        key_row, key = issue_key(
            session, tenant, grant_type="free", channel_id=channel.id,
            hardware_model_id=hardware.id,
        )
        session.commit()
        identity, _ = activate_device(session, key=key, device_code="A133-001", old_token=None, tenant_code="test-tenant")
        with pytest.raises(HTTPException) as incompatible:
            update_hardware_model(session, admin, hardware.id, HardwareInput(
                channel_id=channel.id, code="A133", name="A133", abi="armeabi-v7a",
            ))
        assert incompatible.value.status_code == 409
        assert key_row.used_terminal_id == identity.terminal_id
        assert terminal_ota(session, identity) is None
        with EsopTenantUnitOfWork(session, tenant) as uow:
            package = create_ota_package(uow, admin, Files(tenant, file_id), OtaPackageInput(
                channel_id=channel.id, hardware_model_id=hardware.id, version="1.0.0",
                version_code=100, package_name="com.example.esop", file_id=file_id,
            ))
        assert package.status == "draft"
        assert terminal_ota(session, identity) is None
        publish_ota_package(session, admin, package.id)
        manifest = terminal_ota(session, identity)
        assert manifest.versionCode == 100
        assert manifest.sha256 == "a" * 64
        assert manifest.size == 123
        assert manifest.package == "com.example.esop"
        with EsopTenantUnitOfWork(session, tenant) as uow:
            newer = create_ota_package(uow, admin, Files(tenant, file_id), OtaPackageInput(
                channel_id=channel.id, hardware_model_id=hardware.id, version="1.1.0",
                version_code=110, package_name="com.example.esop", file_id=file_id,
            ))
        publish_ota_package(session, admin, newer.id)
        assert terminal_ota(session, identity).versionCode == 110
        with pytest.raises(HTTPException) as republish:
            publish_ota_package(session, admin, newer.id)
        assert republish.value.status_code == 409


def test_registration_free_key_uses_direct_a133_and_stays_in_caller_transaction(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS])
    tenant = uuid.uuid4()
    monkeypatch.setattr("app.platform.web_api.resolve_channel_customer_code",
        lambda **kwargs: SimpleNamespace(id=tenant, code="test-tenant", name="Test"))
    with Session(engine) as session:
        issue_free_key(session, tenant)
        session.rollback()
        assert session.exec(select(ActivationKey)).all() == []
        assert session.exec(select(Channel)).all() == []
        bind_official_tenant(session, tenant, uuid.uuid4())
        key_id, key = issue_free_key(session, tenant)
        record = session.get(ActivationKey, key_id)
        hardware = session.get(HardwareModel, DIRECT_A133_ID)
        assert record.grant_type == "free"
        assert record.channel_id == DIRECT_CHANNEL_ID
        assert record.hardware_model_id == DIRECT_A133_ID
        assert hardware.abi == "armeabi-v7a"
        session.commit()
        identity, _ = activate_device(session, key=key, device_code="A133-FREE", old_token=None, tenant_code="test-tenant")
        with EsopTenantUnitOfWork(session, tenant):
            terminal = session.get(Terminal, identity.terminal_id)
            assert terminal.channel_id == DIRECT_CHANNEL_ID
            assert terminal.hardware_model_id == DIRECT_A133_ID
