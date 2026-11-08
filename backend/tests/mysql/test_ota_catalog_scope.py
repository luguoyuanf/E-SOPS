"""Read-only regression against the configured online test database."""
import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.modules.esop.infrastructure.models import ChannelCustomerTenant, OtaPackage
from app.modules.esop.ota_routes import download_installation_package, list_ota_packages
from app.platform.infra.file_directory import SqlFileAssetDirectory
from app.platform.tenant_uow import PlatformTenantScopeError, PlatformTenantUnitOfWork
from app.platform.web_api import Principal, TenantContext, get_authorized_file


def test_published_catalog_switches_only_authorized_file_scope_and_restores_customer():
    assert settings.DATABASE_TYPE == "mysql" and settings.MYSQL_DB == "esop_fva_test_20261024"
    with Session(engine) as session:
        package = session.exec(select(OtaPackage).where(OtaPackage.status == "published")).first()
        assert package is not None, "Regression requires an existing published installation package"
        customer = session.exec(select(ChannelCustomerTenant).where(
            ChannelCustomerTenant.channel_id == package.channel_id,
            ChannelCustomerTenant.tenant_id != package.file_owner_tenant_id,
        )).first()
        assert customer is not None
        owner, file_id, package_id = package.file_owner_tenant_id, package.file_id, package.id
        tenant_id = customer.tenant_id
        principal = Principal(id=uuid.uuid4(), is_superuser=False)
        with PlatformTenantUnitOfWork(session, tenant_id):
            with pytest.raises(PlatformTenantScopeError):
                SqlFileAssetDirectory(session).get_accessible_file(tenant_id=owner, file_id=file_id)
            result = list_ota_packages(session, principal, TenantContext(
                tenant_id=tenant_id, tenant_code="regression", user_id=principal.id,
            ))
            assert any(row.id == package_id and row.file_name for row in result["items"])
            assert session.info["platform_tenant_id"] == tenant_id
            assert get_authorized_file(session=session, tenant_id=owner, file_id=uuid.uuid4()) is None
            assert session.info["platform_tenant_id"] == tenant_id
        with PlatformTenantUnitOfWork(session, uuid.uuid4()):
            tenant = TenantContext(tenant_id=session.info["platform_tenant_id"], tenant_code="unlinked", user_id=principal.id)
            assert list_ota_packages(session, principal, tenant)["items"] == []
            with pytest.raises(HTTPException) as denied:
                download_installation_package(session, principal, tenant, package_id)
            assert denied.value.status_code == 404
