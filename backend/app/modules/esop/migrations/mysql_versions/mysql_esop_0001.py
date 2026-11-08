"""Initial MySQL 5.7 ESOP tables, isolated from PostgreSQL history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0001"
down_revision = None
branch_labels = None
depends_on = None

TABLE_OPTIONS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    op.create_table(
        "esop_operation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_esop_operation_tenant_code"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_esop_operation_tenant_id", "esop_operation", ["tenant_id"])
    op.create_table(
        "esop_process_route",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("operation_ids", mysql.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_esop_route_tenant_code"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_esop_process_route_tenant_id", "esop_process_route", ["tenant_id"])
    op.create_table(
        "esop_sop_document",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("pages", mysql.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid()),
        sa.Column("review_note", sa.String(500)),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6)),
        sa.UniqueConstraint("tenant_id", "family_id", "version", name="uq_esop_sop_family_version"),
        sa.UniqueConstraint("tenant_id", "product_id", "operation_id", "version", name="uq_esop_sop_product_operation_version"),
        **TABLE_OPTIONS,
    )
    for column in ("tenant_id", "family_id", "product_id", "operation_id"):
        op.create_index(f"ix_esop_sop_document_{column}", "esop_sop_document", [column])


def downgrade() -> None:
    for table in ("esop_sop_document", "esop_process_route", "esop_operation"):
        op.drop_table(table)
