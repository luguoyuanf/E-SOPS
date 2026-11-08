"""ESOP tenant boundary for both MySQL and PostgreSQL."""

import uuid
from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import event, inspect, text
from sqlalchemy.orm import with_loader_criteria
from sqlalchemy.sql import visitors
from sqlmodel import Session

from app.core.cache import CacheNamespace
from app.core.transaction_cache import register_tenant_cache_models
from app.modules.esop.infrastructure.models import (
    OWNED_MODELS,
    ActivationKey,
    Operation,
    OperationFileRendition,
    ProductSopVersion,
    SopDocument,
)
from app.platform.web_api import CurrentTenant, SessionDep

register_tenant_cache_models(CacheNamespace.SOP_GUIDANCE, (Operation, ProductSopVersion, SopDocument, OperationFileRendition))

class TenantScopeError(RuntimeError):
    pass


@dataclass
class EsopTenantUnitOfWork:
    session: Session
    tenant_id: uuid.UUID

    def __enter__(self) -> EsopTenantUnitOfWork:
        existing = self.session.info.get("esop_tenant_id")
        if existing is not None and existing != self.tenant_id:
            raise TenantScopeError("A session cannot serve multiple ESOP tenants")
        self._previous_tenant_id = existing
        self.session.info["esop_tenant_id"] = self.tenant_id
        if self.session.get_bind().dialect.name == "postgresql" and self.session.in_transaction():
            self.session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(self.tenant_id)},
            )
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            if exc_type is None:
                self.session.flush()
        finally:
            if self._previous_tenant_id is None:
                if self.session.get_bind().dialect.name == "postgresql" and self.session.is_active:
                    self.session.execute(
                        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                        {"tenant_id": str(self.session.info.get("platform_tenant_id") or "")},
                    )
                self.session.info.pop("esop_tenant_id", None)
                for entity in list(self.session.identity_map.values()):
                    if isinstance(entity, OWNED_MODELS):
                        self.session.expunge(entity)
            else:
                self.session.info["esop_tenant_id"] = self._previous_tenant_id


def get_esop_tenant_uow(
    session: SessionDep, tenant_context: CurrentTenant
) -> Generator[EsopTenantUnitOfWork]:
    with EsopTenantUnitOfWork(session, tenant_context.tenant_id) as uow:
        yield uow


EsopTenantUowDep = Annotated[EsopTenantUnitOfWork, Depends(get_esop_tenant_uow)]


def _touches_esop(statement: Any) -> bool:
    tables = {model.__table__ for model in OWNED_MODELS}
    return any(node in tables for node in visitors.iterate(statement))


@event.listens_for(Session, "after_begin")
def set_transaction_tenant(session: Session, transaction: Any, connection: Any) -> None:
    tenant_id = session.info.get("esop_tenant_id")
    if tenant_id is not None and not transaction.nested and connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )


@event.listens_for(Session, "do_orm_execute")
def enforce_esop_query_scope(state: Any) -> None:
    if not _touches_esop(state.statement):
        return
    tenant_id = state.session.info.get("esop_tenant_id")
    if tenant_id is None:
        raise TenantScopeError("ESOP data requires an explicit UnitOfWork")
    if state.is_update or state.is_delete or not state.is_orm_statement:
        raise TenantScopeError("ESOP data requires tenant-checked ORM operations")
    if state.is_select:
        for model in OWNED_MODELS:
            state.statement = state.statement.options(
                with_loader_criteria(
                    model,
                    lambda entity: entity.tenant_id == tenant_id,
                    include_aliases=True,
                )
            )


@event.listens_for(Session, "before_flush")
def enforce_esop_write_scope(
    session: Session, _flush_context: Any, _instances: Any
) -> None:
    for entity in (*session.new, *session.dirty, *session.deleted):
        if isinstance(entity, ActivationKey) and entity in session.dirty:
            history = inspect(entity).attrs.tenant_id.history
            if history.has_changes() and history.deleted and history.deleted[0] is not None:
                raise TenantScopeError("Activation key tenant ownership is permanent")
        if not isinstance(entity, OWNED_MODELS):
            continue
        tenant_id = session.info.get("esop_tenant_id")
        if tenant_id is None or entity.tenant_id != tenant_id:
            raise TenantScopeError("ESOP write tenant does not match active scope")
        if entity in session.dirty and inspect(entity).attrs.tenant_id.history.has_changes():
            raise TenantScopeError("ESOP tenant_id is immutable")
