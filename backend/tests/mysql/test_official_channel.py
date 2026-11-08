"""Official defaults use the fixed online services; database writes roll back."""
import uuid

import pytest
from sqlmodel import Session, select
from starlette.requests import Request

from app.api.routes import login, tenants
from app.core.config import settings
from app.core.database import engine
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.modules.esop.activation_routes import issue_activation_key
from app.modules.esop.infrastructure.models import (
    ActivationKey,
    Channel,
    ChannelCustomerTenant,
)
from app.modules.esop.infrastructure.registration_activation import (
    DIRECT_CHANNEL_ID,
    bind_official_tenant,
)
from app.modules.esop.migrations import official_channel_20261026 as migration
from app.modules.esop.public_api.terminal_dto import ActivationIssueInput
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import (
    Tenant,
    TenantCreate,
    TenantRegistrationRequest,
)
from app.platform.infra.registration_email import hash_code, verification_keys
from app.platform.tenant_uow import PlatformGlobalUnitOfWork
from app.platform.web_api import Principal


@pytest.fixture
def session():
    assert settings.DATABASE_TYPE == 'mysql' and settings.MYSQL_DB == 'esop_fva_test_20261024'
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as s:
                yield s
        finally:
            outer.rollback()


def test_admin_provisioning_and_issued_key_inherit_official_channel(session):
    with PlatformGlobalUnitOfWork(session):
        root = session.exec(select(User).where(User.is_superuser, User.is_active)).first()
        assert root is not None
        created = tenants.create_tenant(session=session, current_user=root, tenant_in=TenantCreate(code='official-' + uuid.uuid4().hex[:12], name='Official acceptance'))
        mapping = session.exec(select(ChannelCustomerTenant).where(ChannelCustomerTenant.tenant_id == created.id)).one()
        assert mapping.channel_id == DIRECT_CHANNEL_ID
        bind_official_tenant(session, created.id, root.id)
        assert len(session.exec(select(ChannelCustomerTenant).where(ChannelCustomerTenant.tenant_id == created.id)).all()) == 1
        issued = issue_activation_key(session, Principal(id=root.id, is_superuser=True), ActivationIssueInput(tenant_id=created.id))
        assert issued.channel_id == DIRECT_CHANNEL_ID


def test_self_registration_gets_official_tenant_and_free_key(session):
    suffix = uuid.uuid4().hex[:12]
    email = suffix + '@example.com'
    keys = verification_keys(email)
    assert login.redis_cache.set(keys[0], hash_code(email, '123456'), ttl_seconds=60)
    request = Request({'type':'http', 'method':'POST', 'path':'/api/v1/login/register-tenant', 'headers':[], 'client':('127.0.0.1',1234)})
    try:
        with PlatformGlobalUnitOfWork(session):
            result = login.register_tenant(request=request, session=session, body=TenantRegistrationRequest(
                tenant_code='registered-' + suffix, tenant_name='Registration acceptance', email=email, full_name='Acceptance', password='Acceptance-Only-42!', email_code='123456',
            ))
            assert result.free_activation_key
            assert session.exec(select(User).where(User.email == email)).one().mobile is None
            assert login.redis_cache.get(keys[0]) is None
            mapping = session.exec(select(ChannelCustomerTenant).where(ChannelCustomerTenant.tenant_id == result.tenant_id)).one()
            key = session.exec(select(ActivationKey).where(ActivationKey.tenant_id == result.tenant_id)).one()
            assert mapping.channel_id == key.channel_id == DIRECT_CHANNEL_ID
    finally:
        login.redis_cache.delete(*keys)


def test_migration_preserves_channel_links_and_default_binding_is_idempotent(session):
    with PlatformGlobalUnitOfWork(session):
        root = session.exec(select(User).where(User.is_superuser)).first()
        baseline = session.get(Tenant, DEFAULT_TENANT_ID)
        tenant = Tenant(code='channel-' + uuid.uuid4().hex[:12], name='Existing channel customer', plan_id=baseline.plan_id, initialization_template_id=baseline.initialization_template_id)
        channel = Channel(code=uuid.uuid4().hex, name='Independent channel')
        session.add_all([tenant, channel])
        session.flush()
        mapping = ChannelCustomerTenant(channel_id=channel.id, tenant_id=tenant.id, created_by=root.id)
        session.add(mapping)
        session.flush()
        migration.upgrade(session.connection())
        migration.upgrade(session.connection())
        bind_official_tenant(session, tenant.id, root.id)
        assert session.exec(select(ChannelCustomerTenant).where(ChannelCustomerTenant.tenant_id == tenant.id)).one().channel_id == channel.id
        assert session.get(Channel, DIRECT_CHANNEL_ID).name == '官方渠道'
        assert all(session.exec(select(ChannelCustomerTenant).where(ChannelCustomerTenant.tenant_id == row.id)).first() is not None for row in session.exec(select(Tenant)).all())
        migration.downgrade(session.connection())
        assert session.exec(select(ChannelCustomerTenant).where(ChannelCustomerTenant.tenant_id == tenant.id)).one().channel_id == channel.id
        migration.upgrade(session.connection())


def test_registration_company_code_availability_and_duplicate_rejection(session):
    from fastapi import HTTPException

    from app.core.tenancy_constants import DEFAULT_TENANT_CODE

    email = uuid.uuid4().hex + '@example.com'
    keys = verification_keys(email)
    assert login.redis_cache.set(keys[0], hash_code(email, '123456'), ttl_seconds=60)
    request = Request({'type': 'http', 'headers': [], 'client': ('127.0.0.1', 1234)})
    try:
        with PlatformGlobalUnitOfWork(session):
            assert not login.check_registration_tenant_code(session=session, tenant_code=DEFAULT_TENANT_CODE).available
            assert login.check_registration_tenant_code(session=session, tenant_code='available-' + uuid.uuid4().hex[:12]).available
            with pytest.raises(HTTPException) as exc:
                login.register_tenant(request=request, session=session, body=TenantRegistrationRequest(tenant_code=DEFAULT_TENANT_CODE, tenant_name='Duplicate test', full_name='Owner', email=email, password='Example-only-42!', email_code='123456'))
            assert exc.value.status_code == 409
            assert session.exec(select(User).where(User.email == email)).first() is None
    finally:
        login.redis_cache.delete(*keys)
