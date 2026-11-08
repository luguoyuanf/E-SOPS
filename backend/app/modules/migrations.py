import logging

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlmodel import Session

from app.core.database import engine
from app.modules.access import reconcile_module_runtime, set_module_observed_state
from app.modules.manifest import build_manifest
from app.modules.outbox import enqueue_event
from app.modules.platform_events import ModuleObservedStateChangedV1
from app.modules.registry import get_module_definitions
from app.platform.core.runtime_models import ModuleObservedState, ModuleRegistry
from app.platform.tenant_uow import PlatformGlobalUnitOfWork

logger = logging.getLogger(__name__)
MIGRATION_LOCK_KEY = 921_735_021


def migration_order(*, edition: str) -> list[str]:
    """Return the dependency-resolved modules that the edition will migrate."""
    return [module.code for module in build_manifest(edition=edition).modules]


def module_alembic_config(namespace: str) -> Config:
    if namespace == "platform":
        return Config("alembic-mysql.ini" if engine.dialect.name == "mysql" else "alembic.ini")
    if engine.dialect.name == "mysql":
        if namespace not in {"erp", "esop"}:
            raise ValueError("MySQL 5.7 supports Platform, ERP and ESOP only")
        config = Config("alembic-mysql.ini")
        config.set_main_option("script_location", f"app/modules/{namespace}/migrations")
        config.set_main_option("version_locations", f"app/modules/{namespace}/migrations/mysql_versions")
        config.set_main_option("version_table", f"alembic_version_{namespace}")
        return config
    config = Config("alembic.ini")
    config.set_main_option("script_location", f"app/modules/{namespace}/migrations")
    config.set_main_option("version_table", f"alembic_version_{namespace}")
    config.set_main_option("version_table_schema", "public")
    return config


def migration_is_current(*, config: Config, connection) -> bool:
    """Return whether the namespace version table already matches its heads."""
    # Application Sessions on this coordinator connection have closed.
    connection.info.pop("platform_scope_session", None)
    connection.info.pop("erp_scope_session", None)
    script = ScriptDirectory.from_config(config)
    context = MigrationContext.configure(
        connection,
        opts={
            "version_table": config.get_main_option("version_table") or "alembic_version",
            "version_table_schema": config.get_main_option("version_table_schema"),
        },
    )
    return set(context.get_current_heads()) == set(script.get_heads())


def transition_module_observed_state(
    *,
    session: Session,
    registry: ModuleRegistry,
    observed_state: ModuleObservedState,
    actual_revision: str | None = None,
    reason: str,
) -> None:
    previous_state = registry.observed_state
    set_module_observed_state(
        session=session,
        registry=registry,
        observed_state=observed_state,
        actual_revision=actual_revision,
        reason=reason,
    )
    if previous_state != observed_state:
        enqueue_event(
            session=session,
            module_code="platform",
            event_type="platform.module.observed_state.changed",
            tenant_id=None,
            aggregate_id=registry.code,
            payload=ModuleObservedStateChangedV1(
                module_code=registry.code,
                previous_state=previous_state,
                observed_state=observed_state,
                actual_revision=actual_revision,
                reason=reason,
            ).model_dump(mode="json"),
            allow_zero_subscribers=True,
        )


def migrate_edition(*, edition: str) -> list[str]:
    """Run the current edition under a database-level migration lock.

    Each module namespace has a separate Alembic version table. The platform
    namespace is always run first because Manifest dependency resolution puts it
    first for every supported edition.
    """
    manifest = build_manifest(edition=edition)
    modules = [module.code for module in manifest.modules]
    mysql = engine.dialect.name == "mysql"
    if mysql and not set(modules) <= {"platform", "erp", "esop"}:
        raise ValueError("MySQL 5.7 supports Platform, ERP and ESOP only")
    definitions = get_module_definitions()
    with engine.connect() as connection:
        if mysql:
            acquired = connection.scalar(text("SELECT GET_LOCK(:key, 30)"), {"key": f"fast-vben:{engine.url.database}:migration"})
            if acquired != 1:
                raise RuntimeError("Could not acquire the database migration lock")
        else:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
        runtime_initialized = False
        active_module: str | None = None
        try:
            # Platform creates the state tables that make module-level failure
            # recovery auditable, so it must run before runtime records exist.
            active_module = "platform"
            platform_config = module_alembic_config("platform")
            platform_needs_migration = not migration_is_current(
                config=platform_config, connection=connection
            )
            if platform_needs_migration:
                command.upgrade(platform_config, "head")
            with Session(bind=connection) as session, PlatformGlobalUnitOfWork(session):
                reconcile_module_runtime(session, manifest=manifest)
                runtime_initialized = True
                platform_registry = session.get(ModuleRegistry, "platform")
                assert platform_registry is not None
                if platform_needs_migration or (
                    platform_registry.observed_state != ModuleObservedState.READY
                ):
                    transition_module_observed_state(
                        session=session,
                        registry=platform_registry,
                        observed_state=ModuleObservedState.READY,
                        actual_revision="platform-head",
                        reason=(
                            "platform migration completed"
                            if platform_needs_migration
                            else "platform schema already at head; runtime recovered"
                        ),
                    )
                session.commit()
                connection.commit()
            migrated_namespaces = {"platform"}
            for module_code in modules:
                namespace = definitions[module_code].migration.namespace
                if namespace in migrated_namespaces:
                    continue
                active_module = module_code
                config = module_alembic_config(namespace)
                needs_migration = not migration_is_current(
                    config=config, connection=connection
                )
                if needs_migration:
                    with Session(bind=connection) as session, PlatformGlobalUnitOfWork(session):
                        registry = session.get(ModuleRegistry, module_code)
                        assert registry is not None
                        transition_module_observed_state(
                            session=session,
                            registry=registry,
                            observed_state=ModuleObservedState.MIGRATING,
                            reason=f"{namespace} migration started",
                        )
                        session.commit()
                        connection.commit()
                    command.upgrade(config, "head")
                with Session(bind=connection) as session, PlatformGlobalUnitOfWork(session):
                    registry = session.get(ModuleRegistry, module_code)
                    assert registry is not None
                    if needs_migration or registry.observed_state != ModuleObservedState.READY:
                        transition_module_observed_state(
                            session=session,
                            registry=registry,
                            observed_state=ModuleObservedState.READY,
                            actual_revision=f"{namespace}-head",
                            reason=(
                                f"{namespace} migration completed"
                                if needs_migration
                                else f"{namespace} schema already at head; runtime recovered"
                            ),
                        )
                    session.commit()
                    connection.commit()
                migrated_namespaces.add(namespace)
        except Exception:
            if runtime_initialized and active_module is not None:
                with Session(bind=connection) as session, PlatformGlobalUnitOfWork(session):
                    registry = session.get(ModuleRegistry, active_module)
                    if registry is not None:
                        transition_module_observed_state(
                            session=session,
                            registry=registry,
                            observed_state=ModuleObservedState.DEGRADED,
                            reason="migration failed; retry after remediation",
                        )
                    session.commit()
                    connection.commit()
            raise
        finally:
            # All application Sessions above are closed; this connection now
            # belongs solely to the trusted migration lock coordinator.
            connection.info.pop("platform_scope_session", None)
            if mysql:
                connection.execute(text("SELECT RELEASE_LOCK(:key)"), {"key": f"fast-vben:{engine.url.database}:migration"})
            else:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
            connection.commit()
    logger.info("Migration completed for edition %s: %s", edition, ", ".join(modules))
    return modules
