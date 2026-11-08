"""Frozen MySQL chain checks; live tests require an explicit isolated test schema.

Run independently of the PostgreSQL suite fixtures:
    uv run pytest --confcutdir=tests/mysql tests/mysql/test_migrations.py -q
Set MYSQL_MIGRATION_TEST=1 only for a dedicated esop_fva_test_* database.
"""
import io
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint, inspect, text
from sqlmodel import SQLModel

from app.core.config import settings
from app.core.database import engine
from app.platform.migration_metadata import (
    import_platform_model_groups,
    platform_table_owners,
)

BACKEND = Path(__file__).resolve().parents[2]


def mysql_config(output_buffer=None):
    config = Config(str(BACKEND / 'alembic-mysql.ini'), output_buffer=output_buffer)
    config.set_main_option('script_location', str(BACKEND / 'app/alembic'))
    config.set_main_option('version_locations', str(BACKEND / 'app/alembic/mysql_versions'))
    return config


def test_mysql_has_one_independent_frozen_baseline():
    script = ScriptDirectory.from_config(mysql_config())
    assert script.get_heads() == ['mysql_platform_0001']
    revision = script.get_revision('head')
    assert revision.down_revision is None
    source = Path(revision.path).read_text()
    assert 'create_all' not in source
    assert 'target_metadata' not in source
    assert 'app.platform' not in source
    assert source.count('op.create_table(') == len(platform_table_owners())
    pg_config = Config(str(BACKEND / 'alembic.ini'))
    pg_config.set_main_option('script_location', str(BACKEND / 'app/alembic'))
    assert 'mysql_platform_0001' not in ScriptDirectory.from_config(pg_config).get_heads()



def test_foreign_keys_match_parent_index_order_for_mysql():
    import_platform_model_groups()
    for name in platform_table_owners():
        for foreign_key in SQLModel.metadata.tables[name].foreign_key_constraints:
            parent = foreign_key.referred_table
            target = tuple(element.column.name for element in foreign_key.elements)
            indexes = [tuple(column.name for column in index.columns) for index in parent.indexes]
            indexes += [tuple(column.name for column in constraint.columns)
                        for constraint in parent.constraints
                        if isinstance(constraint, (PrimaryKeyConstraint, UniqueConstraint))]
            assert any(target == index[:len(target)] for index in indexes), (name, target)


def test_mysql_offline_upgrade_and_downgrade_compile(monkeypatch):
    monkeypatch.setattr(settings, 'DATABASE_TYPE', 'mysql')
    output = io.StringIO()
    command.upgrade(mysql_config(output), 'head', sql=True)
    sql = output.getvalue()
    assert sql.count('CREATE TABLE ') == len(platform_table_owners()) + 1
    assert 'MEDIUMTEXT' in sql
    assert 'DATETIME(6)' in sql
    assert 'CHAR(32)' in sql
    assert 'ROW LEVEL SECURITY' not in sql
    assert 'CREATE SCHEMA' not in sql
    output = io.StringIO()
    command.downgrade(mysql_config(output), 'mysql_platform_0001:base', sql=True)
    assert output.getvalue().count('DROP TABLE ') == len(platform_table_owners()) + 1


@pytest.mark.skipif(os.environ.get('MYSQL_MIGRATION_TEST') != '1', reason='explicit disposable MySQL test schema required')
def test_live_upgrade_repeat_preserves_rows_and_has_no_model_drift():
    assert settings.DATABASE_TYPE == 'mysql'
    assert settings.MYSQL_DB.startswith('esop_fva_test_')
    command.upgrade(mysql_config(), 'head')
    with engine.begin() as connection:
        assert connection.exec_driver_sql('SELECT VERSION()').scalar_one().startswith('5.7.')
        assert set(inspect(connection).get_table_names()) == set(platform_table_owners()) | {'alembic_version'}
        marker = uuid.uuid4().hex
        connection.execute(text(
            'INSERT INTO tenantplan (id,code,name,is_default,is_active) '
            'VALUES (:id,:code,:name,0,1)'
        ), {'id': marker, 'code': 'migration-' + marker, 'name': 'Migration persistence check'})
    try:
        command.upgrade(mysql_config(), 'head')
        with engine.connect() as connection:
            assert connection.execute(text('SELECT name FROM tenantplan WHERE id=:id'), {'id': marker}).scalar_one() == 'Migration persistence check'
        command.check(mysql_config())
    finally:
        with engine.begin() as connection:
            connection.execute(text('DELETE FROM tenantplan WHERE id=:id'), {'id': marker})
