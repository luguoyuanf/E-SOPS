"""Tenant-scoped database boundary for Platform operational data."""

import uuid
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import with_loader_criteria
from sqlalchemy.pool import Pool
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import ColumnClause, TextClause
from sqlmodel import Session

from app.core.cache import CacheNamespace
from app.core.transaction_cache import register_tenant_cache_models
from app.platform.core.authorization_models import (
    Department,
    Post,
    Role,
    RoleDataScopeDepartment,
    UserPost,
    UserRole,
)
from app.platform.core.configuration_models import (
    DictionaryItem,
    DictionaryType,
    Notice,
    SiteMessageTemplate,
    SystemSetting,
    UserMessage,
)
from app.platform.core.identity_models import SocialClient, SocialUser, UserSession
from app.platform.core.runtime_models import (
    TenantModule,
    TenantModuleEntitlementOverride,
)
from app.platform.infra.audit_models import LoginLog, OperationLog
from app.platform.infra.file_models import FileAsset, FileStorageChannel
from app.platform.infra.mail_models import MailAccount, MailLog, MailTemplate
from app.platform.infra.sms_models import SmsChannel, SmsLog, SmsTemplate

register_tenant_cache_models(CacheNamespace.FILE_ASSETS, (FileAsset,))

class PlatformTenantScopeError(RuntimeError):
    """Raised when Platform operational data escapes its tenant boundary."""


TENANT_SCOPED_MODELS = (
    Department,
    Post,
    Role,
    RoleDataScopeDepartment,
    UserPost,
    UserRole,
    DictionaryItem,
    DictionaryType,
    Notice,
    SiteMessageTemplate,
    SystemSetting,
    UserMessage,
    FileAsset,
    FileStorageChannel,
    MailAccount,
    MailTemplate,
    MailLog,
    LoginLog,
    OperationLog,
    SmsChannel,
    SmsTemplate,
    SmsLog,
    SocialClient,
    SocialUser,
    UserSession,
    TenantModule,
    TenantModuleEntitlementOverride,
)


def _set_transaction_tenant(session: Session, tenant_id: uuid.UUID) -> None:
    if session.get_bind().dialect.name != "postgresql" or not session.is_active:
        return
    session.connection().execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def _clear_transaction_tenant(session: Session) -> None:
    if session.get_bind().dialect.name != "postgresql" or not session.is_active:
        return
    session.connection().execute(text("SELECT set_config('app.tenant_id', '', true)"))


def _mysql(session: Session) -> bool:
    return session.get_bind().dialect.name == "mysql"


def _clear_identity(session: Session) -> None:
    for entity in list(session.identity_map.values()):
        if isinstance(entity, TENANT_SCOPED_MODELS):
            session.expunge(entity)


def _change_scope(session: Session) -> None:
    # Identity-map hits bypass ORM query hooks; never carry cached tenant entities
    # across a scope change. Pending writes must be resolved by their owner first.
    if session.new or session.dirty or session.deleted:
        raise PlatformTenantScopeError(
            "Resolve pending writes before changing tenant scope"
        )
    _clear_identity(session)


def activate_platform_tenant_scope(
    session: Session, tenant_id: uuid.UUID, *, privileged: bool = False
) -> None:
    """Bind one verified tenant; privileged permits switching, not global access."""
    existing = session.info.get("platform_tenant_id")
    if existing is not None and existing != tenant_id and not privileged:
        raise PlatformTenantScopeError("A session cannot serve multiple tenants")
    if existing != tenant_id or session.info.get("platform_global_scope"):
        _change_scope(session)
    session.info.pop("platform_global_scope", None)
    session.info["platform_tenant_id"] = tenant_id
    _set_transaction_tenant(session, tenant_id)


@dataclass
class PlatformTenantUnitOfWork:
    session: Session
    tenant_id: uuid.UUID
    privileged: bool = False

    def __enter__(self) -> PlatformTenantUnitOfWork:
        self._previous_tenant_id = self.session.info.get("platform_tenant_id")
        self._previous_global = self.session.info.get("platform_global_scope", False)
        activate_platform_tenant_scope(
            self.session, self.tenant_id, privileged=self.privileged
        )
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        # Flush in the owning scope, never defer writes until a parent scope.
        try:
            if exc_type is None:
                self.session.flush()
        finally:
            _clear_identity(self.session)
            if self._previous_tenant_id is None:
                self.session.info.pop("platform_tenant_id", None)
                _clear_transaction_tenant(self.session)
            else:
                self.session.info["platform_tenant_id"] = self._previous_tenant_id
                _set_transaction_tenant(self.session, self._previous_tenant_id)
            if self._previous_global:
                self.session.info["platform_global_scope"] = True
            else:
                self.session.info.pop("platform_global_scope", None)


@dataclass
class PlatformGlobalUnitOfWork:
    """Cross-tenant control-plane scope; caller MUST first authorize platform root.

    This explicit scope is never inferred from request tenant IDs or user input.
    It does not grant PostgreSQL BYPASSRLS or replace database authorization.
    """

    session: Session

    def __enter__(self) -> PlatformGlobalUnitOfWork:
        self._previous_tenant_id = self.session.info.get("platform_tenant_id")
        self._previous_global = self.session.info.get("platform_global_scope", False)
        _change_scope(self.session)
        self.session.info.pop("platform_tenant_id", None)
        self.session.info["platform_global_scope"] = True
        _clear_transaction_tenant(self.session)
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            if exc_type is None:
                self.session.flush()
        finally:
            _clear_identity(self.session)
            if self._previous_tenant_id is not None:
                self.session.info["platform_tenant_id"] = self._previous_tenant_id
                _set_transaction_tenant(self.session, self._previous_tenant_id)
            else:
                self.session.info.pop("platform_tenant_id", None)
            if self._previous_global:
                self.session.info["platform_global_scope"] = True
            else:
                self.session.info.pop("platform_global_scope", None)


def get_platform_tenant_uow(
    session: Session, tenant_id: uuid.UUID
) -> Generator[PlatformTenantUnitOfWork]:
    with PlatformTenantUnitOfWork(session=session, tenant_id=tenant_id) as uow:
        yield uow


@event.listens_for(Session, "after_begin")
def set_transaction_tenant(session: Session, transaction: Any, connection: Any) -> None:
    if connection.dialect.name == "mysql":
        connection.info["platform_scope_session"] = session
        return
    tenant_id = session.info.get("platform_tenant_id")
    if (
        tenant_id is None
        or transaction.nested
        or connection.dialect.name != "postgresql"
    ):
        return
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def _tenant_tables(statement: Any) -> bool:
    names = {model.__table__.name for model in TENANT_SCOPED_MODELS}
    return any(
        getattr(node, "__visit_name__", None) == "table" and node.name in names
        for node in visitors.iterate(statement)
    )


def _raw_fragments(statement: Any) -> bool:
    return any(
        isinstance(node, TextClause)
        or (
            isinstance(node, ColumnClause)
            and node.is_literal
            and not str(node).replace("_", "").isalnum()
            and str(node) != "*"
        )
        for node in visitors.iterate(statement)
    )


def _health_sql(statement: str) -> bool:
    return statement.strip().rstrip(";").upper() == "SELECT 1"


@event.listens_for(Session, "do_orm_execute")
def enforce_platform_query_scope(execute_state: Any) -> None:
    session = execute_state.session
    tenant_id = session.info.get("platform_tenant_id")
    global_scope = session.info.get("platform_global_scope", False)
    statement = execute_state.statement
    if _mysql(session):
        if isinstance(statement, TextClause):
            if not _health_sql(statement.text):
                raise PlatformTenantScopeError(
                    "Raw SQL is forbidden in application sessions"
                )
            return
        if _raw_fragments(statement):
            raise PlatformTenantScopeError(
                "Raw SQL fragments are forbidden in application sessions"
            )
        if _tenant_tables(statement):
            if tenant_id is None and not global_scope:
                raise PlatformTenantScopeError(
                    "Tenant-owned data requires an explicit UnitOfWork"
                )
            if not execute_state.is_orm_statement or execute_state.is_insert:
                raise PlatformTenantScopeError(
                    "Use ORM operations for tenant-owned data"
                )
            # ORM bulk inserts bypass before_flush; use normal add/flush instead.
            if execute_state.is_update:
                values = getattr(statement, "_values", {}) or {}
                if any(getattr(key, "key", key) == "tenant_id" for key in values):
                    raise PlatformTenantScopeError("tenant_id is immutable")
                parameters = execute_state.parameters
                if isinstance(parameters, dict):
                    parameters = [parameters]
                if parameters and any("tenant_id" in value for value in parameters):
                    raise PlatformTenantScopeError("tenant_id is immutable")
        execute_state.update_execution_options(platform_uow_checked=True)
    if tenant_id is None or global_scope:
        return
    if execute_state.is_select or execute_state.is_update or execute_state.is_delete:
        for model in TENANT_SCOPED_MODELS:
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    model,
                    lambda entity: entity.tenant_id == tenant_id,
                    include_aliases=True,
                )
            )


@event.listens_for(Session, "before_flush")
def enforce_platform_write_scope(
    session: Session, _flush_context: Any, _instances: Any
) -> None:
    tenant_id = session.info.get("platform_tenant_id")
    global_scope = session.info.get("platform_global_scope", False)
    for entity in (*session.new, *session.dirty, *session.deleted):
        if not isinstance(entity, TENANT_SCOPED_MODELS):
            continue
        if _mysql(session) and tenant_id is None and not global_scope:
            raise PlatformTenantScopeError(
                "Tenant-owned data requires an explicit UnitOfWork"
            )
        if tenant_id is not None and not global_scope and entity.tenant_id != tenant_id:
            raise PlatformTenantScopeError(
                f"{type(entity).__name__} tenant_id does not match the active tenant"
            )
        if (
            entity in session.dirty
            and inspect(entity).attrs.tenant_id.history.has_changes()
        ):
            raise PlatformTenantScopeError(
                f"{type(entity).__name__} tenant_id is immutable"
            )

    session.info["platform_checked_flush"] = True


@event.listens_for(Session, "after_flush_postexec")
def clear_checked_flush(session: Session, _flush_context: Any) -> None:
    session.info.pop("platform_checked_flush", None)


@event.listens_for(Session, "after_soft_rollback")
def clear_rolled_back_flush(session: Session, _previous_transaction: Any) -> None:
    session.info.pop("platform_checked_flush", None)


@event.listens_for(Engine, "before_execute")
def guard_session_connection(
    connection: Any,
    clause: Any,
    _multiparams: Any,
    _params: Any,
    execution_options: Any,
) -> None:
    """Stop Session.connection() from bypassing the checked ORM boundary."""
    session = connection.info.get("platform_scope_session")
    if connection.dialect.name != "mysql" or session is None:
        return
    if isinstance(clause, TextClause):
        if not _health_sql(clause.text):
            raise PlatformTenantScopeError(
                "Raw SQL is forbidden in application sessions"
            )
    elif _raw_fragments(clause):
        raise PlatformTenantScopeError(
            "Raw SQL fragments are forbidden in application sessions"
        )
    elif _tenant_tables(clause) and not (
        execution_options.get("platform_uow_checked")
        or (session._flushing and session.info.get("platform_checked_flush"))
    ):
        raise PlatformTenantScopeError("Tenant data must use the checked ORM session")


@event.listens_for(Engine, "before_cursor_execute")
def guard_driver_sql(
    connection: Any,
    _cursor: Any,
    statement: str,
    _parameters: Any,
    context: Any,
    _executemany: Any,
) -> None:
    if (
        connection.dialect.name == "mysql"
        and connection.info.get("platform_scope_session") is not None
        and context.compiled is None
        and not _health_sql(statement)
    ):
        raise PlatformTenantScopeError(
            "Driver SQL is forbidden in application sessions"
        )


@event.listens_for(Pool, "checkin")
def clear_connection_scope(_dbapi_connection: Any, connection_record: Any) -> None:
    connection_record.info.pop("platform_scope_session", None)
