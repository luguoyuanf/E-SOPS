"""ESOP storage grants enforce upload limits without changing other editions."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.quotas import ensure_file_quota
from app.platform.core.esop_commercial import (
    CERTIFIED_BYTES,
    REGISTERED_BYTES,
    certify_esop_tenant,
    ensure_esop_storage_account,
    esop_storage_limit,
)
from app.platform.core.esop_commercial_models import EsopStorageGrant
from app.platform.core.tenancy_models import Tenant, TenantPlan
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)


def test_certification_paid_activation_and_annual_expiry() -> None:
    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(engine, tables=[SQLModel.metadata.tables[name] for name in names])
    with Session(engine) as session:
        plan = TenantPlan(code=f"esop-{uuid.uuid4().hex}", name="ESOP", max_storage_bytes=None)
        tenant = Tenant(code=f"t-{uuid.uuid4().hex}", name="Factory", plan_id=plan.id)
        session.add_all([plan, tenant])
        session.commit()

        account = ensure_esop_storage_account(session=session, tenant_id=tenant.id)
        session.commit()
        gifts = session.exec(select(EsopStorageGrant).where(EsopStorageGrant.tenant_id == tenant.id)).all()
        assert len(gifts) == 1
        assert gifts[0].source == "opening_gift" and gifts[0].note == "开户赠送"
        assert gifts[0].expires_at is None and gifts[0].capacity_bytes == REGISTERED_BYTES
        ensure_esop_storage_account(session=session, tenant_id=tenant.id)
        session.commit()
        assert len(session.exec(select(EsopStorageGrant)).all()) == 1
        # The legacy account snapshot cannot add capacity on top of the ledger.
        account.base_bytes = 9 * REGISTERED_BYTES
        session.add(account)
        session.commit()
        assert esop_storage_limit(session=session, tenant_id=tenant.id) == (REGISTERED_BYTES, 0)
        ensure_file_quota(session=session, tenant_id=tenant.id, incoming_size=REGISTERED_BYTES)
        with pytest.raises(HTTPException, match="storage quota exceeded"):
            ensure_file_quota(session=session, tenant_id=tenant.id, incoming_size=REGISTERED_BYTES + 1)

        certify_esop_tenant(session=session, tenant_id=tenant.id)
        session.commit()
        ensure_file_quota(session=session, tenant_id=tenant.id, incoming_size=CERTIFIED_BYTES)
        with pytest.raises(HTTPException, match="storage quota exceeded"):
            ensure_file_quota(session=session, tenant_id=tenant.id, incoming_size=CERTIFIED_BYTES + 1)

        now = datetime.now(UTC)
        session.add(
            EsopStorageGrant(
                tenant_id=tenant.id,
                capacity_bytes=200,
                starts_at=now - timedelta(days=1),
                expires_at=now + timedelta(days=364),
            )
        )
        session.commit()
        assert esop_storage_limit(session=session, tenant_id=tenant.id, now=now) == (CERTIFIED_BYTES, 200)
        assert esop_storage_limit(session=session, tenant_id=tenant.id, now=now + timedelta(days=365)) == (CERTIFIED_BYTES, 0)

