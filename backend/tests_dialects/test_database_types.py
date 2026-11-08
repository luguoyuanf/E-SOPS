from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, Uuid, create_engine, select
from sqlalchemy.dialects import mysql, postgresql

from app.core.config import Settings
from app.core.database_types import LargeString, UTCDateTime


def test_utc_datetime_roundtrip_and_naive_rejection():
    type_ = UTCDateTime()
    source = datetime(2026, 10, 24, 10, 11, 12, 123456, timezone(timedelta(hours=8)))
    stored = type_.process_bind_param(source, mysql.dialect())
    assert stored == datetime(2026, 10, 24, 2, 11, 12, 123456)
    assert type_.process_result_value(stored, mysql.dialect()) == source.astimezone(UTC)
    assert type_.process_bind_param(source, postgresql.dialect()).tzinfo == UTC
    with pytest.raises(ValueError, match="timezone"):
        type_.process_bind_param(datetime(2026, 10, 24), mysql.dialect())
    assert str(type_.compile(dialect=mysql.dialect())) == "DATETIME(6)"
    assert "WITH TIME ZONE" in str(type_.compile(dialect=postgresql.dialect()))


def test_large_string_keeps_postgres_length_and_mysql_unicode_capacity():
    assert str(LargeString(20000).compile(dialect=mysql.dialect())) == "MEDIUMTEXT"
    assert (
        str(LargeString(20000).compile(dialect=postgresql.dialect()))
        == "VARCHAR(20000)"
    )
    metadata = MetaData()
    table = Table(
        "roundtrip",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("uuid", Uuid),
        Column("at", UTCDateTime()),
        Column("text", LargeString(20000)),
    )
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    identifier, timestamp, content = uuid4(), datetime.now(UTC), "中文" * 9000
    with engine.begin() as db:
        db.execute(table.insert().values(uuid=identifier, at=timestamp, text=content))
        row = db.execute(select(table)).one()
        assert row.uuid == identifier and isinstance(row.uuid, UUID)
        assert row.at == timestamp and row.at.tzinfo == UTC
        assert row.text == content


def test_mysql_and_postgres_url_encoding_without_secret_output():
    args = {
        "_env_file": None,
        "PROJECT_NAME": "Test",
        "FIRST_SUPERUSER": "test@example.com",
        "FIRST_SUPERUSER_PASSWORD": "test-only-random-value",
        "POSTGRES_SERVER": "db.example",
        "POSTGRES_USER": "pg_test",
        "POSTGRES_PASSWORD": "p@ss:/?#",
        "POSTGRES_DB": "pg_test",
    }
    # Explicitly select the dialect; _env_file=None does not disable inherited
    # environment variables from the MySQL validation runner.
    postgres = Settings(**args, DATABASE_TYPE="postgresql")
    mysql_settings = Settings(
        **args,
        DATABASE_TYPE="mysql",
        MYSQL_SERVER="mysql.example",
        MYSQL_USER="mysql_test",
        MYSQL_PASSWORD="p@ss:/?#",
        MYSQL_DB="test_schema",
    )
    from sqlalchemy.engine import make_url

    for settings in (postgres, mysql_settings):
        url = make_url(settings.SQLALCHEMY_DATABASE_URI)
        assert url.password == "p@ss:/?#"
    assert (
        make_url(mysql_settings.SQLALCHEMY_DATABASE_URI).drivername == "mysql+pymysql"
    )
    assert make_url(postgres.SQLALCHEMY_DATABASE_URI).drivername == "postgresql+psycopg"
