"""Tenant-scoped database boundary for the ERP business module."""

import uuid
from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import event, inspect, text
from sqlalchemy.dialects.mysql import Insert as MySQLInsert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import with_loader_criteria
from sqlalchemy.pool import Pool
from sqlalchemy.sql import visitors
from sqlmodel import Session

from app.core.cache import CacheNamespace
from app.core.transaction_cache import register_tenant_cache_models
from app.modules.erp.infrastructure.models import (
    ERP_TENANT_SCOPED_MODELS,
    DocumentActionLog,
    DocumentSequence,
    PlatformProductUnit,
    Product,
    ProductCategory,
    ProductUnit,
    StockBalance,
    StockLedger,
)
from app.platform.web_api import CurrentTenant, SessionDep

register_tenant_cache_models(CacheNamespace.PRODUCT_DIRECTORY, (Product, ProductCategory))

class TenantScopeError(RuntimeError):
    """Raised when an ERP operation escapes its tenant boundary."""


@dataclass
class ErpTenantUnitOfWork:
    session: Session
    tenant_id: uuid.UUID

    def __enter__(self) -> ErpTenantUnitOfWork:
        existing = self.session.info.get("erp_tenant_id")
        self._previous_tenant_id = existing
        if existing is not None and existing != self.tenant_id:
            raise TenantScopeError("A session cannot serve multiple tenants")
        self.session.info["erp_tenant_id"] = self.tenant_id
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
                self.session.info.pop("erp_tenant_id", None)
                for entity in list(self.session.identity_map.values()):
                    if isinstance(entity, ERP_TENANT_SCOPED_MODELS):
                        self.session.expunge(entity)
            else:
                self.session.info["erp_tenant_id"] = self._previous_tenant_id


def get_erp_tenant_uow(
    session: SessionDep, tenant_context: CurrentTenant
) -> Generator[ErpTenantUnitOfWork]:
    with ErpTenantUnitOfWork(session=session, tenant_id=tenant_context.tenant_id) as uow:
        yield uow


ErpTenantUowDep = Annotated[ErpTenantUnitOfWork, Depends(get_erp_tenant_uow)]


@event.listens_for(Session, "after_begin")
def set_transaction_tenant(session: Session, transaction: Any, connection: Any) -> None:
    tenant_id = session.info.get("erp_tenant_id")
    connection.info["erp_scope_session"] = session
    if connection.dialect.name == "mysql":
        return
    if tenant_id is None or transaction.nested:
        return
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def _erp_tables(statement: Any) -> bool:
    tables = {model.__table__ for model in ERP_TENANT_SCOPED_MODELS}
    return any(node in tables for node in visitors.iterate(statement))


@event.listens_for(Session, "do_orm_execute")
def enforce_erp_query_scope(execute_state: Any) -> None:
    tenant_id = execute_state.session.info.get("erp_tenant_id")
    if any(node in {PlatformProductUnit.__table__} for node in visitors.iterate(execute_state.statement)):
        if not execute_state.is_select or not execute_state.is_orm_statement:
            raise TenantScopeError("Platform product units require checked catalog operations")
        execute_state.update_execution_options(erp_catalog_checked=True)
    if execute_state.session.get_bind().dialect.name == "mysql" and _erp_tables(execute_state.statement):
        if tenant_id is None:
            raise TenantScopeError("ERP data requires an explicit UnitOfWork")
        if execute_state.is_insert:
            statement = execute_state.statement
            upsert_tenant = execute_state.execution_options.get("erp_upsert_tenant")
            values = getattr(statement, "_values", {}) or {}
            values = {getattr(key, "key", key): value for key, value in values.items()}
            allowed_columns = {
                DocumentSequence.__table__.name: {"tenant_id", "prefix", "sequence_date", "next_value"},
                StockBalance.__table__.name: {"tenant_id", "product_id", "warehouse_id", "quantity", "version", "updated_at"},
            }.get(statement.table.name, set())
            if not (
                isinstance(statement, MySQLInsert)
                and upsert_tenant == tenant_id
                and getattr(values.get("tenant_id"), "value", None) == tenant_id
                and set(values) <= allowed_columns
                and statement._post_values_clause is not None
                and isinstance(statement._post_values_clause.update, dict)
                and set(statement._post_values_clause.update) <= {"next_value", "quantity"}
            ):
                raise TenantScopeError("ERP data must use tenant-checked ORM operations")
        elif not execute_state.is_orm_statement:
            raise TenantScopeError("ERP data must use ORM operations")
        execute_state.update_execution_options(erp_uow_checked=True)
    if tenant_id is None:
        return
    if execute_state.is_update or execute_state.is_delete:
        raise TenantScopeError("Tenant UnitOfWork forbids ORM bulk DML")
    if execute_state.is_select:
        for model in ERP_TENANT_SCOPED_MODELS:
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    model,
                    lambda entity: entity.tenant_id == tenant_id,
                    include_aliases=True,
                )
            )


@event.listens_for(Session, "before_flush")
def enforce_erp_write_scope(
    session: Session, _flush_context: Any, _instances: Any
) -> None:
    tenant_id = session.info.get("erp_tenant_id")
    if not session.info.get("erp_platform_unit_write"):
        for entity in (*session.new, *session.dirty, *session.deleted):
            if isinstance(entity, PlatformProductUnit):
                raise TenantScopeError("Platform product units require an authorized catalog command")
            if isinstance(entity, ProductUnit):
                source_history = inspect(entity).attrs.platform_unit_id.history
                if entity.platform_unit_id is not None or source_history.has_changes():
                    if entity in session.new and entity.platform_unit_id is None:
                        continue
                    raise TenantScopeError("Platform product unit is read-only")
    mysql = session.get_bind().dialect.name == "mysql"
    if mysql and tenant_id is None and any(
        isinstance(entity, ERP_TENANT_SCOPED_MODELS)
        for entity in (*session.new, *session.dirty, *session.deleted)
    ):
        raise TenantScopeError("ERP data requires an explicit UnitOfWork")
    if tenant_id is None:
        return
    for entity in session.deleted:
        if isinstance(entity, ERP_TENANT_SCOPED_MODELS) and entity.tenant_id != tenant_id:
            raise TenantScopeError("ERP tenant_id does not match the active tenant")
        if isinstance(entity, (DocumentActionLog, StockLedger)):
            raise TenantScopeError("ERP append-only record is immutable")
    for entity in (*session.new, *session.dirty):
        if not isinstance(entity, ERP_TENANT_SCOPED_MODELS):
            continue
        if isinstance(entity, (DocumentActionLog, StockLedger)) and entity in session.dirty:
            raise TenantScopeError("ERP append-only record is immutable")
        if entity.tenant_id != tenant_id:
            raise TenantScopeError("ERP tenant_id does not match the active tenant")
        if entity in session.dirty and inspect(entity).attrs.tenant_id.history.has_changes():
            raise TenantScopeError("ERP tenant_id is immutable")


@event.listens_for(Engine, "before_execute")
def guard_erp_connection(connection: Any, clause: Any, _multiparams: Any, _params: Any, execution_options: Any) -> None:
    session = connection.info.get("erp_scope_session")
    if session is not None and any(node in {PlatformProductUnit.__table__} for node in visitors.iterate(clause)):
        if not (execution_options.get("erp_catalog_checked") or
                (session._flushing and session.info.get("erp_platform_unit_write"))):
            raise TenantScopeError("Platform product units require checked catalog operations")
    if connection.dialect.name != "mysql" or session is None or not _erp_tables(clause):
        return
    if not (execution_options.get("erp_uow_checked") or session._flushing):
        raise TenantScopeError("ERP data must use the checked ORM session")


@event.listens_for(Pool, "checkin")
def clear_erp_connection_scope(_dbapi_connection: Any, connection_record: Any) -> None:
    connection_record.info.pop("erp_scope_session", None)
