"""Platform migrations; PostgreSQL history and MySQL baseline are separate chains."""
from importlib import import_module
from logging.config import fileConfig

from alembic import context
from sqlalchemy import MetaData, String, engine_from_config, pool
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel

from app.core.config import settings
from app.platform.migration_metadata import (
    import_platform_model_groups,
    platform_table_owners,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = str(settings.SQLALCHEMY_DATABASE_URI)
is_mysql = make_url(url).get_backend_name() == "mysql"
mysql_chain = "mysql_versions" in (config.get_main_option("version_locations") or "")
if is_mysql != mysql_chain:
    raise RuntimeError(
        "MySQL requires alembic-mysql.ini; PostgreSQL requires alembic.ini. "
        "The dialect migration histories must never be mixed."
    )

import_platform_model_groups()
if is_mysql:
    # The owner registry is the sole Platform metadata source. Optional module
    # tables must never appear in this namespace, even if imported elsewhere.
    target_metadata = MetaData()
    for name in sorted(platform_table_owners()):
        SQLModel.metadata.tables[name].to_metadata(target_metadata)
    # Department leaders reference memberships, while memberships reference
    # departments. Defer this edge for deterministic metadata dependency order.
    for constraint in target_metadata.tables["department"].foreign_key_constraints:
        if constraint.referred_table.name == "tenantmembership":
            constraint.use_alter = True
else:
    # Preserve the existing PostgreSQL migration/autogeneration contract.
    import_module("app.models")
    target_metadata = SQLModel.metadata


def include_object(_object, name, type_, _reflected, _compare_to):
    if type_ == "table":
        return not (name.startswith("alembic_version_") or (
            is_mysql and name.startswith(("erp_", "esop_"))
        ))
    # mysql_platform_0007 introduced this nullable compatibility column. Session
    # ownership now lives in UserSession; retain the exact historical column
    # until an explicit migration removes it. Other column drift stays visible.
    if (is_mysql and type_ == "column" and _reflected and _compare_to is None
        and _object.table.name == "user" and name == "current_backoffice_jti"
        and isinstance(_object.type, String) and _object.type.length == 64
        and _object.nullable and _object.server_default is None):
        return False
    return True


def run_migrations_offline():
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        migrate_connection(supplied_connection)
        return
    configuration = config.get_section(config.config_ini_section)
    assert configuration is not None
    configuration["sqlalchemy.url"] = url
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        migrate_connection(connection)


def migrate_connection(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
