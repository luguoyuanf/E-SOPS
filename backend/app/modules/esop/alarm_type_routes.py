"""Tenant alarm type choices and protected dictionary management."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from app.modules.esop.infrastructure.models import AlarmTypePreference
from app.modules.esop.infrastructure.tenant_uow import (
    EsopTenantUnitOfWork,
    EsopTenantUowDep,
)
from app.modules.esop.terminal_routes import DeviceDep
from app.platform.web_api import (
    AlarmTypeDirectoryDep,
    CurrentPrincipal,
    SessionDep,
    UserDirectoryDep,
    require_module_access,
)

router = APIRouter(prefix="/esop", tags=["esop-alarm-types"])
BUILT_IN = frozenset({"production", "sop", "personnel", "other"})


class AlarmTypePublic(BaseModel):
    code: str
    name: str
    source: Literal["builtin", "platform", "tenant"]
    enabled: bool
    sort: int
    built_in: bool
    tenant_owned: bool


class AlarmTypeList(BaseModel):
    items: list[AlarmTypePublic]
    can_manage_global: bool = False


class AlarmTypeInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class AlarmTypePreferenceInput(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    enabled: bool
    sort: int = Field(ge=0, le=100000)


class AlarmTypePreferencesInput(BaseModel):
    items: list[AlarmTypePreferenceInput]


def _clean_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="报警类型名称不能为空")
    return name


def _categories(
    uow: EsopTenantUnitOfWork, directory: AlarmTypeDirectoryDep,
) -> list[AlarmTypePublic]:
    preferences = {
        row.type_code: row for row in uow.session.exec(select(AlarmTypePreference)).all()
    }
    global_items = directory.list_global()
    tenant_items = directory.list_tenant(uow.tenant_id)
    result = []
    for source, items in (("platform", global_items), ("tenant", tenant_items)):
        for item in items:
            preference = preferences.get(item.code)
            is_builtin = source == "platform" and item.code in BUILT_IN
            result.append(AlarmTypePublic(
                code=item.code, name=item.name,
                source="builtin" if is_builtin else source,
                enabled=item.active and (preference.enabled if preference else True),
                sort=preference.sort if preference else item.sort,
                built_in=is_builtin, tenant_owned=source == "tenant",
            ))
    return sorted(result, key=lambda item: (item.sort, item.name, item.code))


def _admin(principal: CurrentPrincipal, uow: EsopTenantUowDep, users: UserDirectoryDep) -> None:
    if not (principal.is_superuser or users.is_tenant_administrator(principal.id, uow.tenant_id)):
        raise HTTPException(status_code=403, detail="仅租户管理员可管理报警类型")


@router.get("/terminal/alarm-types", response_model=AlarmTypeList)
def terminal_alarm_types(
    session: SessionDep, device: DeviceDep, directory: AlarmTypeDirectoryDep,
) -> AlarmTypeList:
    with EsopTenantUnitOfWork(session, device.tenant_id) as uow:
        return AlarmTypeList(items=[item for item in _categories(uow, directory) if item.enabled])


@router.get(
    "/alarm-types", response_model=AlarmTypeList,
    dependencies=[Depends(require_module_access("esop", "esop:alarm:list"))],
)
def list_alarm_types(
    uow: EsopTenantUowDep, directory: AlarmTypeDirectoryDep,
    principal: CurrentPrincipal,
) -> AlarmTypeList:
    return AlarmTypeList(items=_categories(uow, directory), can_manage_global=principal.is_superuser)


@router.post(
    "/alarm-types", response_model=AlarmTypePublic,
    dependencies=[Depends(require_module_access("esop", "esop:alarm:type:manage"))],
)
def create_tenant_alarm_type(
    body: AlarmTypeInput, uow: EsopTenantUowDep, directory: AlarmTypeDirectoryDep,
    principal: CurrentPrincipal, users: UserDirectoryDep,
) -> AlarmTypePublic:
    _admin(principal, uow, users)
    item = directory.create_tenant(uow.tenant_id, _clean_name(body.name))
    uow.session.commit()
    return AlarmTypePublic(code=item.code, name=item.name, source="tenant", enabled=True,
                           sort=item.sort, built_in=False, tenant_owned=True)


@router.patch(
    "/alarm-types/{code}", response_model=AlarmTypePublic,
    dependencies=[Depends(require_module_access("esop", "esop:alarm:type:manage"))],
)
def rename_tenant_alarm_type(
    code: str, body: AlarmTypeInput, uow: EsopTenantUowDep,
    directory: AlarmTypeDirectoryDep, principal: CurrentPrincipal, users: UserDirectoryDep,
) -> AlarmTypePublic:
    _admin(principal, uow, users)
    if code not in {item.code for item in directory.list_tenant(uow.tenant_id)}:
        raise HTTPException(status_code=403, detail="内置和平台报警类型不能由租户修改")
    item = directory.rename_tenant(uow.tenant_id, code, _clean_name(body.name))
    uow.session.commit()
    return AlarmTypePublic(code=item.code, name=item.name, source="tenant", enabled=item.active,
                           sort=item.sort, built_in=False, tenant_owned=True)


@router.put(
    "/alarm-types/preferences", response_model=AlarmTypeList,
    dependencies=[Depends(require_module_access("esop", "esop:alarm:type:manage"))],
)
def update_alarm_type_preferences(
    body: AlarmTypePreferencesInput, uow: EsopTenantUowDep, directory: AlarmTypeDirectoryDep,
    principal: CurrentPrincipal, users: UserDirectoryDep,
) -> AlarmTypeList:
    _admin(principal, uow, users)
    valid = {item.code for item in _categories(uow, directory)}
    codes = [item.code for item in body.items]
    if len(codes) != len(set(codes)) or not set(codes) <= valid:
        raise HTTPException(status_code=422, detail="报警类型包含重复或无效编码")
    existing = {row.type_code: row for row in uow.session.exec(select(AlarmTypePreference)).all()}
    for item in body.items:
        row = existing.get(item.code)
        if row is None:
            row = AlarmTypePreference(tenant_id=uow.tenant_id, type_code=item.code)
        row.enabled = item.enabled
        row.sort = item.sort
        uow.session.add(row)
    uow.session.commit()
    return AlarmTypeList(items=_categories(uow, directory), can_manage_global=principal.is_superuser)


@router.post(
    "/platform/alarm-types", response_model=AlarmTypePublic,
    dependencies=[Depends(require_module_access("esop", "esop:alarm:type:manage"))],
)
def create_platform_alarm_type(
    body: AlarmTypeInput, principal: CurrentPrincipal, directory: AlarmTypeDirectoryDep,
    session: SessionDep,
) -> AlarmTypePublic:
    if not principal.is_superuser:
        raise HTTPException(status_code=403, detail="仅平台管理员可新增全局报警类型")
    item = directory.create_global(_clean_name(body.name))
    session.commit()
    return AlarmTypePublic(code=item.code, name=item.name, source="platform", enabled=True,
                           sort=item.sort, built_in=False, tenant_owned=False)


@router.patch(
    "/platform/alarm-types/{code}", response_model=AlarmTypePublic,
    dependencies=[Depends(require_module_access("esop", "esop:alarm:type:manage"))],
)
def rename_platform_alarm_type(
    code: str, body: AlarmTypeInput, principal: CurrentPrincipal,
    directory: AlarmTypeDirectoryDep, session: SessionDep,
) -> AlarmTypePublic:
    if not principal.is_superuser:
        raise HTTPException(status_code=403, detail="仅平台管理员可修改全局报警类型")
    item = directory.rename_global(code, _clean_name(body.name))
    session.commit()
    is_builtin = code in BUILT_IN
    return AlarmTypePublic(code=item.code, name=item.name,
                           source="builtin" if is_builtin else "platform", enabled=item.active,
                           sort=item.sort, built_in=is_builtin, tenant_owned=False)
