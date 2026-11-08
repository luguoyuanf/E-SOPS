import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlmodel import col, func, select

from app.api.deps import (
    PlatformConfigurationTenant,
    PlatformReadTenant,
    PublicTenantId,
    SessionDep,
    get_current_active_superuser,
    normalize_pagination,
    require_permission,
)
from app.core.cache import CacheNamespace, redis_cache
from app.core.clock import get_datetime_utc
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.platform.core.configuration_models import (
    SystemSetting,
    SystemSettingPublic,
    SystemSettingsPublic,
    SystemSettingUpdate,
)
from app.platform.core.esop_commercial_models import EsopStorageDefault
from app.platform.storage_provisioning import STORAGE_DEFAULT_KEY
from app.platform.tenant_uow import PlatformTenantUnitOfWork

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get(
    "",
    dependencies=[
        Depends(require_permission("system:setting:list")),
        Depends(get_current_active_superuser),
    ],
    response_model=SystemSettingsPublic,
)
def read_settings(
    session: SessionDep,
    read_tenant: PlatformReadTenant,  # noqa: ARG001 - legacy filter is ignored
    group: str | None = None,
    page: int = 1,
    page_size: int = 50,
    keyword: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Any:
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        page, page_size = normalize_pagination(page=page, page_size=page_size)
        filters = [SystemSetting.tenant_id == DEFAULT_TENANT_ID]
        if group:
            filters.append(SystemSetting.group == group)
        if keyword:
            pattern = f"%{keyword}%"
            filters.append(
                (col(SystemSetting.key).ilike(pattern))
                | (col(SystemSetting.name).ilike(pattern))
            )

        if created_from is not None:
            filters.append(SystemSetting.created_at >= created_from)
        if created_to is not None:
            filters.append(SystemSetting.created_at <= created_to)
        count_statement = select(func.count()).select_from(SystemSetting)
        if filters:
            count_statement = count_statement.where(*filters)
        count = session.exec(count_statement).one()

        statement = select(SystemSetting)
        if filters:
            statement = statement.where(*filters)
        statement = (
            statement.order_by(col(SystemSetting.group), col(SystemSetting.key))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        settings = session.exec(statement).all()
        return SystemSettingsPublic(
            items=[SystemSettingPublic.model_validate(setting) for setting in settings],
            total=count,
            page=page,
            page_size=page_size,
        )


@router.get("/public", response_model=list[SystemSettingPublic])
def read_public_settings(
    session: SessionDep,
    public_tenant_id: PublicTenantId,  # noqa: ARG001 - authentication only
) -> Any:
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        cache_key = redis_cache.build_versioned_key(
            CacheNamespace.PUBLIC_SETTINGS,
            str(DEFAULT_TENANT_ID),
            "all",
        )
        cached_settings = redis_cache.get_json(cache_key)
        if cached_settings is not None:
            return [
                SystemSettingPublic.model_validate(setting)
                for setting in cached_settings
            ]

        settings = session.exec(
            select(SystemSetting)
            .where(
                SystemSetting.tenant_id == DEFAULT_TENANT_ID,
                SystemSetting.is_public,
            )
            .order_by(col(SystemSetting.group), col(SystemSetting.key))
        ).all()
        public_settings = [
            SystemSettingPublic.model_validate(setting) for setting in settings
        ]
        redis_cache.set_json(
            cache_key,
            [setting.model_dump(mode="json") for setting in public_settings],
        )
        return public_settings


@router.patch(
    "/{key}",
    dependencies=[Depends(require_permission("system:setting:update"))],
    response_model=SystemSettingPublic,
)
def update_setting(
    *,
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,
    key: str,
    setting_in: SystemSettingUpdate,
) -> Any:
    setting = session.exec(
        select(SystemSetting).where(
            SystemSetting.tenant_id == tenant_context.tenant_id,
            SystemSetting.key == key,
        )
    ).first()
    if not setting:
        raise HTTPException(status_code=404, detail="System setting not found")

    update_data = setting_in.model_dump(exclude_unset=True)
    if setting.is_system:
        update_data.pop("is_system", None)
    next_value_type = update_data.get("value_type", setting.value_type)
    next_value = update_data.get("value", setting.value)
    if key == STORAGE_DEFAULT_KEY:
        try:
            update_data["value"] = str(EsopStorageDefault(capacity_mib=next_value).capacity_mib)
            update_data["value_type"] = "number"
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="请输入有效的非负整数容量（MiB）") from exc
    if next_value_type == "json":
        try:
            json.loads(next_value)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Setting value must be JSON")
    setting.sqlmodel_update(update_data)
    setting.updated_at = get_datetime_utc()
    session.add(setting)
    session.commit()
    session.refresh(setting)
    redis_cache.bump_namespace(CacheNamespace.PUBLIC_SETTINGS)
    return setting
