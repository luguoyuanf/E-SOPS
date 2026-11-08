from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool

from app.core.config import settings
from app.modules.esop.infrastructure.models import ALL_MODELS

config = context.config
is_mysql = settings.DATABASE_TYPE == "mysql"
mysql_chain = "mysql_versions" in (config.get_main_option("version_locations") or "")
if is_mysql != mysql_chain:
    raise RuntimeError("ESOP MySQL and PostgreSQL migration histories must not be mixed")
target_metadata = MetaData()
for model in ALL_MODELS:
    model.__table__.to_metadata(target_metadata)


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    if type_ == "schema":
        return name is None if is_mysql else name == "esop"
    if type_ == "table":
        return name in target_metadata.tables if is_mysql else parent_names.get("schema_name") == "esop"
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=str(settings.SQLALCHEMY_DATABASE_URI),
        literal_binds=True,
        target_metadata=target_metadata,
        include_schemas=not is_mysql,
        include_name=include_name,
        version_table="alembic_version_esop",
        version_table_schema=None if is_mysql else "public",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = str(settings.SQLALCHEMY_DATABASE_URI)
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=not is_mysql,
            include_name=include_name,
            version_table="alembic_version_esop",
            version_table_schema=None if is_mysql else "public",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
