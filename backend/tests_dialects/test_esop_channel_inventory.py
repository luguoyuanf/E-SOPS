"""Manual channel stock must remain scoped to its administrator and customers."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.modules.esop import channel_routes
from app.modules.esop.infrastructure import device_auth
from app.modules.esop.infrastructure.device_auth import activate_device
from app.modules.esop.infrastructure.models import ALL_MODELS, ActivationKey, Channel
from app.modules.esop.public_api.channel_dto import (
    BatchIssueInput,
    ChannelAdminInput,
    CustomerInput,
    KeyAssignInput,
    KeyExportInput,
)
from app.platform.public_api.users import UserSummary
from app.platform.web_api import Principal


class Users:
    def __init__(self, active_id: uuid.UUID) -> None:
        self.active_id = active_id

    def get_users(self, ids):
        if self.active_id in ids:
            return [UserSummary(id=self.active_id, full_name="Channel", is_active=True)]
        return []


@pytest.fixture(autouse=True)
def activation_cipher(monkeypatch):
    monkeypatch.setattr(settings, "ESOP_ACTIVATION_CIPHER_KEY", Fernet.generate_key().decode())


def test_channel_batch_customer_assignment_and_cross_channel_rejection(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS])
    admin_id, user_a, user_b, tenant_a, tenant_b = (uuid.uuid4() for _ in range(5))
    superuser = Principal(id=admin_id, is_superuser=True)
    a = Principal(id=user_a, is_superuser=False)
    b = Principal(id=user_b, is_superuser=False)
    created = {}

    def create_tenant(*, session, channel_admin_user_id, customer_name, customer_code):
        del session
        tenant_id = tenant_a if channel_admin_user_id == user_a else tenant_b
        result = SimpleNamespace(id=tenant_id, code=customer_code, name=customer_name)
        created[tenant_id] = result
        return result

    def list_tenants(*, session, tenant_ids):
        del session
        return [created[id] for id in tenant_ids]

    monkeypatch.setattr(channel_routes, "create_channel_customer_tenant", create_tenant)
    monkeypatch.setattr(channel_routes, "get_channel_customer_tenants", list_tenants)
    paid_storage_calls = []
    monkeypatch.setattr(
        device_auth, "ensure_paid_activation_storage",
        lambda *, session, tenant_id: paid_storage_calls.append(tenant_id),
    )
    with Session(engine) as session:
        channels = [Channel(code="A", name="A"), Channel(code="B", name="B")]
        session.add_all(channels)
        session.commit()
        ca, cb = channels
        channel_routes.bind_channel_admin(session, superuser, Users(user_a), ca.id, ChannelAdminInput(user_id=user_a))
        channel_routes.bind_channel_admin(session, superuser, Users(user_b), cb.id, ChannelAdminInput(user_id=user_b))
        with pytest.raises(HTTPException) as wrong_admin:
            channel_routes.bind_channel_admin(session, superuser, Users(user_a), cb.id, ChannelAdminInput(user_id=user_a))
        assert wrong_admin.value.status_code == 409
        batch = channel_routes.issue_channel_batch(session, superuser, ca.id, BatchIssueInput(quantity=100))
        assert len(batch.keys) == 100 and all(len(item.key) == 8 for item in batch.keys)
        assert session.get(ActivationKey, batch.keys[0].id).key_ciphertext != batch.keys[0].key
        page = channel_routes.channel_inventory(session, a, batch.batch_id, 1, 25)
        assert page.total == 100 and len(page.items) == 25
        assert {item.key for item in page.items} <= {item.key for item in batch.keys}
        assert all(item.recoverable and item.status == "unassigned" for item in page.items)
        summary = channel_routes.channel_batches(session, a)
        assert summary.items[0].quantity == 100
        assert summary.items[0].assigned_count == 0
        assert all(row.tenant_id is None for row in session.exec(select(ActivationKey)).all())
        with pytest.raises(HTTPException) as unassigned:
            activate_device(session, key=batch.keys[0].key, device_code="A133-001", old_token=None)
        assert unassigned.value.status_code == 409
        customer_a = channel_routes.create_channel_customer(session, a, CustomerInput(code="cust-a", name="客户A"))
        channel_routes.create_channel_customer(session, b, CustomerInput(code="cust-b", name="客户B"))
        assert channel_routes.channel_customers(session, a).total == 1
        assert channel_routes.channel_inventory(session, a).total == 100
        assert channel_routes.channel_inventory(session, b).total == 0
        with pytest.raises(HTTPException) as cross_customer:
            channel_routes.assign_channel_keys(session, b, KeyAssignInput(
                tenant_id=customer_a.tenant_id, key_ids=[batch.keys[0].id],
            ))
        assert cross_customer.value.status_code == 404
        allocated = channel_routes.assign_channel_keys(session, a, KeyAssignInput(
            tenant_id=customer_a.tenant_id, key_ids=[batch.keys[0].id, batch.keys[1].id],
        ))
        assert allocated.assigned_count == 2
        summary = channel_routes.channel_batches(session, a)
        assert summary.items[0].assigned_count == 2
        assert channel_routes.channel_inventory(session, a).items[0].tenant_id in (None, tenant_a)
        with pytest.raises(HTTPException) as cross_channel_key:
            channel_routes.assign_channel_keys(session, b, KeyAssignInput(
                tenant_id=tenant_b, key_ids=[batch.keys[0].id],
            ))
        assert cross_channel_key.value.status_code == 409
        with pytest.raises(HTTPException) as duplicate:
            channel_routes.assign_channel_keys(session, a, KeyAssignInput(
                tenant_id=tenant_a, key_ids=[batch.keys[0].id, batch.keys[0].id],
            ))
        assert duplicate.value.status_code == 422
        assert session.get(ActivationKey, batch.keys[0].id).tenant_id == tenant_a
        identity, token = activate_device(
            session, key=batch.keys[0].key, device_code="A133-001", old_token=None,
        )
        assert identity.tenant_id == tenant_a and len(token) == 64
        assert paid_storage_calls == [tenant_a]
        summary = channel_routes.channel_batches(session, a)
        assert summary.items[0].activated_count == 1

        response = channel_routes.export_channel_inventory(
            session, a, KeyExportInput(key_ids=[batch.keys[0].id, batch.keys[1].id]),
        )
        async def content():
            return b"".join([
                chunk.encode() if isinstance(chunk, str) else chunk
                async for chunk in response.body_iterator
            ])
        csv_bytes = asyncio.run(content())
        assert response.headers["content-disposition"].startswith("attachment;")
        assert batch.keys[0].key.encode() in csv_bytes
        assert b"activated" in csv_bytes
        with pytest.raises(HTTPException) as other_export:
            channel_routes.export_channel_inventory(
                session, b, KeyExportInput(key_ids=[batch.keys[0].id]),
            )
        assert other_export.value.status_code == 404
        legacy = ActivationKey(
            tenant_id=tenant_a, channel_id=ca.id,
            key_hash="0" * 64, key_ciphertext=None,
        )
        session.add(legacy)
        session.commit()
        old = next(item for item in channel_routes.channel_inventory(session, a).items if item.id == legacy.id)
        assert old.key is None and old.recoverable is False and old.status == "assigned"
        configured_key = settings.ESOP_ACTIVATION_CIPHER_KEY
        monkeypatch.setattr(settings, "ESOP_ACTIVATION_CIPHER_KEY", Fernet.generate_key().decode())
        with pytest.raises(HTTPException) as wrong_cipher:
            channel_routes.channel_inventory(session, a)
        assert wrong_cipher.value.status_code == 503
        monkeypatch.setattr(settings, "ESOP_ACTIVATION_CIPHER_KEY", None)
        with pytest.raises(HTTPException) as unconfigured:
            channel_routes.issue_channel_batch(session, superuser, ca.id, BatchIssueInput(quantity=100))
        assert unconfigured.value.status_code == 503
        monkeypatch.setattr(settings, "ESOP_ACTIVATION_CIPHER_KEY", configured_key)
        activate_device(session, key=batch.keys[0].key, device_code="A133-001", old_token=token)
        assert paid_storage_calls == [tenant_a]
