"""Composition-root binding for the ERP product lookup port."""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from app.modules.erp.application.product_directory import SqlProductDirectory
from app.modules.erp.public_api.products import ProductDirectory
from app.platform.web_api import CurrentTenant, SessionDep


def get_product_directory(
    session: SessionDep, tenant_context: CurrentTenant
) -> ProductDirectory:
    return SqlProductDirectory(session, tenant_context.tenant_id)


ProductDirectoryDep = Annotated[ProductDirectory, Depends(get_product_directory)]


def product_directory_for_tenant(
    session: Session, tenant_id: uuid.UUID
) -> ProductDirectory:
    """Bind the ERP product port after a device credential resolves its tenant."""
    return SqlProductDirectory(session, tenant_id)
