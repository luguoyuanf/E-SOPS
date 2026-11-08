"""Explicit provisioning of read-only tenant units from the platform catalog."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.clock import get_datetime_utc
from app.modules.erp.infrastructure.models import PlatformProductUnit, ProductUnit
from app.modules.erp.infrastructure.tenant_uow import ErpTenantUnitOfWork


@contextmanager
def platform_unit_write_scope(session: Session) -> Iterator[None]:
    """Entered only by authorized platform commands or tenant provisioning."""
    previous = session.info.get("erp_platform_unit_write", False)
    session.info["erp_platform_unit_write"] = True
    try:
        yield
        session.flush()
    finally:
        if previous:
            session.info["erp_platform_unit_write"] = previous
        else:
            session.info.pop("erp_platform_unit_write", None)


def ensure_catalog_unique(
    session: Session, *, code: str, name: str, resource_id: uuid.UUID | None = None
) -> None:
    conflicts = session.exec(select(PlatformProductUnit).where(
        (PlatformProductUnit.code == code) | (PlatformProductUnit.name == name)
    ).with_for_update()).all()
    if any(item.id != resource_id for item in conflicts):
        raise HTTPException(status_code=409, detail="Platform product unit code or name already exists")


def ensure_custom_unit_available(session: Session, *, code: str, name: str) -> None:
    if session.exec(select(PlatformProductUnit.id).where(
        (PlatformProductUnit.code == code) | (PlatformProductUnit.name == name)
    )).first() is not None:
        raise HTTPException(status_code=409, detail="Product unit code or name is reserved by platform")


def sync_tenant_product_units(
    session: Session, tenant_id: uuid.UUID, catalog: list[PlatformProductUnit]
) -> None:
    """Preserve row IDs and fail atomically on tenant custom-unit collisions."""
    with ErpTenantUnitOfWork(session=session, tenant_id=tenant_id):
        with platform_unit_write_scope(session):
            for source in catalog:
                existing = session.exec(select(ProductUnit).where(
                    ProductUnit.platform_unit_id == source.id
                ).with_for_update()).first()
                conflicts = session.exec(select(ProductUnit).where(
                    (ProductUnit.code == source.code) | (ProductUnit.name == source.name)
                ).with_for_update()).all()
                if any(existing is None or unit.id != existing.id for unit in conflicts):
                    raise HTTPException(status_code=409, detail="Platform product unit conflicts with tenant custom unit")
                values = {"code": source.code, "name": source.name, "symbol": source.symbol,
                              "is_active": source.is_active}
                if existing is None:
                    session.add(ProductUnit(tenant_id=tenant_id, platform_unit_id=source.id, **values))
                else:
                    existing.sqlmodel_update(values)
                    existing.updated_at = get_datetime_utc()
                    session.add(existing)
                session.flush()



def lock_platform_unit_catalog(session: Session) -> None:
    """Always acquire catalog locks before new tenant rows to avoid inversion."""
    session.exec(select(PlatformProductUnit).order_by(PlatformProductUnit.id).with_for_update()).all()

def initialize_tenant_product_units(session: Session, tenant_id: uuid.UUID) -> None:
    # Catalog rows are installed by migrations, never by a read request.
    catalog = list(session.exec(select(PlatformProductUnit).order_by(PlatformProductUnit.id).with_for_update()).all())
    sync_tenant_product_units(session, tenant_id, catalog)
