"""Platform-owned default capacity, applied only when opening a storage account."""

import uuid

from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.clock import get_datetime_utc
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.platform.core.configuration_models import SystemSetting
from app.platform.core.esop_commercial import MIB
from app.platform.core.esop_commercial import (
    ensure_esop_storage_account as _ensure_account,
)
from app.platform.core.esop_commercial_models import (
    EsopStorageDefault,
    EsopTenantStorage,
)
from app.platform.tenant_uow import PlatformTenantUnitOfWork

STORAGE_DEFAULT_KEY = "esop.storage.default_capacity_mib"


def read_storage_default(*, session: Session) -> EsopStorageDefault:
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        row = session.exec(select(SystemSetting).where(
            SystemSetting.tenant_id == DEFAULT_TENANT_ID,
            SystemSetting.key == STORAGE_DEFAULT_KEY,
        )).first()
        try:
            return EsopStorageDefault(capacity_mib=row.value if row else 100)
        except ValidationError as exc:
            raise HTTPException(status_code=503, detail="新租户默认存储容量配置无效，请联系管理员") from exc


def save_storage_default(*, session: Session, body: EsopStorageDefault) -> None:
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        row = session.exec(select(SystemSetting).where(
            SystemSetting.tenant_id == DEFAULT_TENANT_ID,
            SystemSetting.key == STORAGE_DEFAULT_KEY,
        )).first()
        if row is None:
            row = SystemSetting(tenant_id=DEFAULT_TENANT_ID, key=STORAGE_DEFAULT_KEY,
                name="新租户默认存储容量（MiB）", value_type="number", group="esop",
                is_system=True, is_public=False,
                description="仅新开通租户继承，已有租户和扩容包不变。")
        row.value = str(body.capacity_mib)
        row.updated_at = get_datetime_utc()
        session.add(row)
        session.flush()


def ensure_esop_storage_account(*, session: Session, tenant_id: uuid.UUID) -> EsopTenantStorage:
    account = session.get(EsopTenantStorage, tenant_id)
    if account is not None:
        return account
    capacity = read_storage_default(session=session).capacity_mib * MIB
    return _ensure_account(session=session, tenant_id=tenant_id, initial_bytes=capacity)


def ensure_paid_activation_storage(*, session: Session, tenant_id: uuid.UUID) -> EsopTenantStorage:
    # Activation must not overwrite capacity already assigned by the administrator.
    return ensure_esop_storage_account(session=session, tenant_id=tenant_id)
