"""Superadministrator control plane for the ERP platform unit catalog."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import func, select

from app.core.clock import get_datetime_utc
from app.modules.erp.application.platform_units import (
    ensure_catalog_unique,
    platform_unit_write_scope,
    sync_tenant_product_units,
)
from app.modules.erp.infrastructure.models import PlatformProductUnit
from app.modules.erp.public_api.dto import (
    PlatformProductUnitPublic,
    PlatformProductUnitsPublic,
    ProductUnitCreate,
    ProductUnitUpdate,
)
from app.platform.public_api.codes import generate_entity_code
from app.platform.web_api import (
    CurrentPrincipal,
    SessionDep,
    TenantDirectoryDep,
    normalize_pagination,
    require_module_access,
)

router = APIRouter(prefix="/erp/platform-product-units", tags=["erp-platform-units"])


def require_platform_admin(principal: CurrentPrincipal) -> None:
    if not principal.is_superuser:
        raise HTTPException(status_code=403, detail="Platform administrator is required")


@router.get("", response_model=PlatformProductUnitsPublic, dependencies=[
    Depends(require_platform_admin),
    Depends(require_module_access("erp", "platform:erp-unit:list")),
])
def list_platform_product_units(
    session: SessionDep, page: int = 1, page_size: int = 20, keyword: str | None = None,
    created_from: datetime | None = None, created_to: datetime | None = None,
) -> PlatformProductUnitsPublic:
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    filters = []
    if keyword:
        filters.append((PlatformProductUnit.code.ilike(f"%{keyword}%")) |
                       (PlatformProductUnit.name.ilike(f"%{keyword}%")))
    if created_from is not None:
        filters.append(PlatformProductUnit.created_at >= created_from)
    if created_to is not None:
        filters.append(PlatformProductUnit.created_at <= created_to)
    total = session.exec(select(func.count()).select_from(PlatformProductUnit).where(*filters)).one()
    items = session.exec(select(PlatformProductUnit).where(*filters)
        .order_by(PlatformProductUnit.code).offset((page - 1) * page_size).limit(page_size)).all()
    return PlatformProductUnitsPublic(items=[PlatformProductUnitPublic.model_validate(item) for item in items],
                                     total=total, page=page, page_size=page_size)


@router.post("", response_model=PlatformProductUnitPublic, dependencies=[
    Depends(require_platform_admin),
    Depends(require_module_access("erp", "platform:erp-unit:create")),
])
def create_platform_product_unit(
    unit_in: ProductUnitCreate, session: SessionDep, tenants: TenantDirectoryDep
) -> PlatformProductUnit:
    # Serialize catalog mutations and tenant provisioning against the same rows.
    session.exec(select(PlatformProductUnit).order_by(PlatformProductUnit.id).with_for_update()).all()
    tenant_ids = tenants.list_tenant_ids()
    unit_in.code = unit_in.code or generate_entity_code("PUNT")
    ensure_catalog_unique(session, code=unit_in.code, name=unit_in.name)
    with platform_unit_write_scope(session):
        unit = PlatformProductUnit.model_validate(unit_in)
        session.add(unit)
    for tenant_id in tenant_ids:
        sync_tenant_product_units(session, tenant_id, [unit])
    session.commit()
    session.refresh(unit)
    return unit


@router.patch("/{resource_id}", response_model=PlatformProductUnitPublic, dependencies=[
    Depends(require_platform_admin),
    Depends(require_module_access("erp", "platform:erp-unit:update")),
])
def update_platform_product_unit(
    resource_id: uuid.UUID, unit_in: ProductUnitUpdate, session: SessionDep,
    tenants: TenantDirectoryDep,
) -> PlatformProductUnit:
    catalog = session.exec(select(PlatformProductUnit).order_by(PlatformProductUnit.id).with_for_update()).all()
    tenant_ids = tenants.list_tenant_ids()
    unit = next((item for item in catalog if item.id == resource_id), None)
    if unit is None:
        raise HTTPException(status_code=404, detail="Platform product unit not found")
    values = unit_in.model_dump(exclude_unset=True)
    if values.get("code") is None:
        values.pop("code", None)
    if any(values.get(key, getattr(unit, key)) is None for key in ("code", "name", "is_active")):
        raise HTTPException(status_code=422, detail="Platform product unit fields cannot be null")
    ensure_catalog_unique(session, code=values.get("code", unit.code),
                          name=values.get("name", unit.name), resource_id=unit.id)
    with platform_unit_write_scope(session):
        unit.sqlmodel_update(values)
        unit.updated_at = get_datetime_utc()
        session.add(unit)
    for tenant_id in tenant_ids:
        sync_tenant_product_units(session, tenant_id, [unit])
    session.commit()
    session.refresh(unit)
    return unit
