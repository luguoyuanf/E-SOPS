"""Frozen dual-dialect platform-unit migration shared by the two histories.

This file is immutable migration source, independent of application models.
Existing same-name units keep their IDs and become canonical read-only copies.
Downgrade keeps tenant unit rows and every existing product/document reference.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

UNITS = (
    ("PCS", "件", None), ("EA", "个", None), ("SET", "套", None),
    ("UNIT", "台", None), ("PACK", "包", None), ("BOX", "箱", None),
    ("ROLL", "卷", None), ("SHEET", "张", None), ("PIECE", "片", None),
    ("STICK", "支", None), ("STRIP", "条", None), ("M", "米", "m"),
    ("M2", "平方米", "m²"), ("KG", "千克", "kg"), ("G", "克", "g"),
    ("T", "吨", "t"), ("L", "升", "L"), ("ML", "毫升", "mL"),
)
NAMESPACE = uuid.UUID("7c1d4c31-f292-4b54-9989-3aacb650c1cd")


def upgrade(*, is_mysql: bool) -> None:
    schema = None if is_mysql else "erp"
    unit_table = "erp_product_unit" if is_mysql else "product_unit"
    catalog_table = "erp_platform_product_unit" if is_mysql else "platform_product_unit"
    units = "erp_product_unit" if is_mysql else "erp.product_unit"
    catalog = "erp_platform_product_unit" if is_mysql else "erp.platform_product_unit"
    tenants = "tenant" if is_mysql else "public.tenant"
    connection = op.get_bind()
    if not op.get_context().as_sql:
        # Abort before MySQL's nontransactional DDL if a canonical code would
        # rename an unrelated legacy unit or collide with same-name adoption.
        for code, name, _symbol in UNITS:
            if connection.execute(sa.text(
                f"SELECT id FROM {units} WHERE code=:code AND name<>:name LIMIT 1"
            ), {"code": code, "name": name}).first():
                raise RuntimeError(f"Platform unit migration collision for code {code}; resolve legacy code first")
    date_type = mysql.DATETIME(fsp=6) if is_mysql else sa.DateTime(timezone=True)
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"} if is_mysql else {}
    op.create_table(catalog_table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", date_type, nullable=False),
        sa.Column("updated_at", date_type, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_erp_platform_product_unit_code"),
        sa.UniqueConstraint("name", name="uq_erp_platform_product_unit_name"),
        schema=schema, **options,
    )
    op.add_column(unit_table, sa.Column("platform_unit_id", sa.Uuid(), nullable=True), schema=schema)
    op.create_unique_constraint("uq_erp_product_unit_tenant_platform", unit_table,
                                ["tenant_id", "platform_unit_id"], schema=schema)
    op.create_foreign_key("fk_erp_product_unit_platform", unit_table, catalog_table,
                          ["platform_unit_id"], ["id"], source_schema=schema,
                          referent_schema=schema, ondelete="RESTRICT")
    seed = sa.table(catalog_table,
        sa.column("id", sa.Uuid()), sa.column("code", sa.String(50)),
        sa.column("name", sa.String(100)), sa.column("symbol", sa.String(20)),
        sa.column("is_active", sa.Boolean()), sa.column("created_at", date_type),
        sa.column("updated_at", date_type), schema=schema)
    now = datetime.now(UTC)
    op.bulk_insert(seed, [{"id": uuid.uuid5(NAMESPACE, code), "code": code, "name": name,
                              "symbol": symbol, "is_active": True, "created_at": now,
                              "updated_at": now} for code, name, symbol in UNITS])
    if is_mysql:
        op.execute(f"UPDATE {units} u JOIN {catalog} c ON u.name=c.name "
                   "SET u.platform_unit_id=c.id,u.code=c.code,u.symbol=c.symbol,u.is_active=c.is_active")
        row_id = "MD5(CONCAT(t.id, ':', c.id))"
    else:
        op.execute(f"UPDATE {units} u SET platform_unit_id=c.id,code=c.code,"
                   f"symbol=c.symbol,is_active=c.is_active FROM {catalog} c WHERE u.name=c.name")
        row_id = "md5(t.id::text || ':' || c.id::text)::uuid"
    op.execute(f"INSERT INTO {units} (id,tenant_id,platform_unit_id,code,name,symbol,is_active,created_at,updated_at) "
               f"SELECT {row_id},t.id,c.id,c.code,c.name,c.symbol,c.is_active,c.created_at,c.updated_at "
               f"FROM {tenants} t CROSS JOIN {catalog} c "
               f"WHERE NOT EXISTS (SELECT 1 FROM {units} u WHERE u.tenant_id=t.id AND u.platform_unit_id=c.id)")


def downgrade(*, is_mysql: bool) -> None:
    schema = None if is_mysql else "erp"
    unit_table = "erp_product_unit" if is_mysql else "product_unit"
    catalog_table = "erp_platform_product_unit" if is_mysql else "platform_product_unit"
    op.drop_constraint("fk_erp_product_unit_platform", unit_table, type_="foreignkey", schema=schema)
    op.drop_constraint("uq_erp_product_unit_tenant_platform", unit_table, type_="unique", schema=schema)
    op.drop_column(unit_table, "platform_unit_id", schema=schema)
    op.drop_table(catalog_table, schema=schema)
