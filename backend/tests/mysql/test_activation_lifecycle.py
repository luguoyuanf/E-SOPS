"""Activation authorization on the fixed online MySQL, all fixtures rolled back."""
import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.modules.esop import activation_routes as routes
from app.modules.esop import channel_routes
from app.modules.esop.infrastructure import device_auth
from app.modules.esop.infrastructure.models import (
    ActivationKey,
    ActivationUnbindLog,
    Channel,
    ChannelAdmin,
    ChannelCustomerTenant,
)
from app.modules.esop.infrastructure.tenant_uow import TenantScopeError
from app.modules.esop.public_api.channel_dto import KeyAssignInput
from app.modules.esop.public_api.terminal_dto import ActivationUnbindInput
from app.platform.web_api import Principal, TenantContext


def test_permanent_owner_role_scope_revocation_and_reactivation(monkeypatch):
    assert settings.DATABASE_TYPE == 'mysql'
    assert settings.MYSQL_DB == 'esop_fva_test_20261024'
    monkeypatch.setattr(device_auth, 'ensure_paid_activation_storage', lambda **kwargs: None)
    a, b, root_id, channel_id, actor_id = [uuid.uuid4() for _ in range(5)]
    root = Principal(id=root_id, is_superuser=True)
    actor = Principal(id=actor_id, is_superuser=False)
    tenant_user = Principal(id=uuid.uuid4(), is_superuser=False)
    ctx = TenantContext(tenant_id=a, tenant_code='test', user_id=actor_id)
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
                session.add(Channel(id=channel_id, code=uuid.uuid4().hex, name='Activation test'))
                session.add(ChannelAdmin(channel_id=channel_id, user_id=actor_id))
                session.add_all([ChannelCustomerTenant(channel_id=channel_id, tenant_id=t, created_by=root_id) for t in (a,b)])
                key, plaintext = device_auth.issue_key(session, None, channel_id=channel_id, batch_id=uuid.uuid4())
                other, _ = device_auth.issue_key(session, b)
                session.commit()
                channel_routes.assign_channel_keys(session, actor, KeyAssignInput(tenant_id=a, key_ids=[key.id]))
                with pytest.raises(HTTPException) as transfer:
                    channel_routes.assign_channel_keys(session, actor, KeyAssignInput(tenant_id=b, key_ids=[key.id]))
                assert transfer.value.status_code == 409
                visible = routes.list_activation_keys(session, tenant_user, ctx)
                assert key.id in {row.id for row in visible.items} and other.id not in {row.id for row in visible.items}
                assert other.id in {row.id for row in routes.list_activation_keys(session, actor, ctx).items}
                assert routes.list_activation_keys(session, tenant_user, ctx, tenant_id=b).total == 0
                identity, token = device_auth.activate_device(session, key=plaintext, device_code='activation-' + uuid.uuid4().hex, old_token=None)
                assert device_auth.resolve_device(session, token) == identity
                assert device_auth.activate_device(session, key=plaintext, device_code=session.exec(select(routes.DeviceCredential).where(routes.DeviceCredential.terminal_id == identity.terminal_id)).one().device_code, old_token=token) == (identity, token)
                with pytest.raises(HTTPException):
                    device_auth.activate_device(session, key=plaintext, device_code='second-' + uuid.uuid4().hex, old_token=None)
                used = routes.list_activation_keys(session, root, ctx, True, a)
                assert used.items[0].device_code and used.items[0].used_at
                with pytest.raises(HTTPException) as forbidden:
                    routes.unbind_activation_key(session, actor, key.id, ActivationUnbindInput(reason='replace'))
                assert forbidden.value.status_code == 403
                result = routes.unbind_activation_key(session, root, key.id, ActivationUnbindInput(reason='replace'))
                assert result.tenant_id == a and not result.is_used
                with pytest.raises(HTTPException) as revoked:
                    device_auth.resolve_device(session, token)
                assert revoked.value.status_code == 401
                assert session.exec(select(ActivationUnbindLog).where(ActivationUnbindLog.key_id == key.id)).one().actor_id == root_id
                with pytest.raises(HTTPException):
                    channel_routes.assign_channel_keys(session, actor, KeyAssignInput(tenant_id=b, key_ids=[key.id]))
                new_identity, new_token = device_auth.activate_device(session, key=plaintext, device_code=used.items[0].device_code, old_token=None)
                assert new_identity.tenant_id == a and new_token != token
                with pytest.raises(HTTPException):
                    device_auth.resolve_device(session, token)
                assert device_auth.resolve_device(session, new_token) == new_identity
                # Export and history use exactly the same visibility boundary as the list.
                response = routes.export_activation_keys(session, actor, ctx, tenant_id=uuid.uuid4())
                async def export_text():
                    return ''.join([chunk if isinstance(chunk, str) else chunk.decode() async for chunk in response.body_iterator])
                assert plaintext not in asyncio.run(export_text())
                assert len(routes.activation_unbind_history(session, actor, ctx, key.id)) == 1
                with pytest.raises(HTTPException):
                    routes.activation_unbind_history(session, tenant_user, ctx, other.id)
                with pytest.raises(HTTPException) as issue_forbidden:
                    routes.issue_activation_key(session, actor, routes.ActivationIssueInput(tenant_id=a))
                assert issue_forbidden.value.status_code == 403
                # Database guard also rejects direct DML outside the ORM mutation path.
                with pytest.raises(DBAPIError), session.begin_nested():
                    session.execute(update(ActivationKey).where(ActivationKey.id == key.id).values(tenant_id=b))
                key.tenant_id = b
                with pytest.raises(TenantScopeError):
                    session.flush()
                session.rollback()
        finally:
            outer.rollback()
