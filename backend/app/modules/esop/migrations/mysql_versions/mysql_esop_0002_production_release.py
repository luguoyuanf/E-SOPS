"""MySQL 5.7 production setup and release tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0002"
down_revision = "mysql_esop_0001"
branch_labels = None
depends_on = None

OPTIONS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def _indexes(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "esop_workshop",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_esop_workshop_tenant_code"),
        **OPTIONS,
    )
    _indexes("esop_workshop", "tenant_id")
    op.create_table(
        "esop_production_line",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workshop_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("layout", sa.String(16), nullable=False),
        sa.Column("station_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_esop_line_tenant_code"),
        **OPTIONS,
    )
    _indexes("esop_production_line", "tenant_id", "workshop_id")
    op.create_table(
        "esop_station",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("row", sa.Integer(), nullable=False),
        sa.Column("column", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "line_id", "position", name="uq_esop_station_line_position"),
        **OPTIONS,
    )
    _indexes("esop_station", "tenant_id", "line_id")
    op.create_table(
        "esop_production_order",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_esop_order_tenant_code"),
        **OPTIONS,
    )
    _indexes("esop_production_order", "tenant_id", "product_id")
    op.create_table(
        "esop_production_plan",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("route_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("assignments", mysql.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        **OPTIONS,
    )
    _indexes("esop_production_plan", "tenant_id", "order_id", "line_id", "route_id")
    op.create_table(
        "esop_work_release",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("assignments", mysql.JSON(), nullable=False),
        sa.Column("published_by", sa.Uuid(), nullable=False),
        sa.Column("published_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("tenant_id", "plan_id", "version", name="uq_esop_release_plan_version"),
        **OPTIONS,
    )
    _indexes("esop_work_release", "tenant_id", "plan_id", "order_id", "line_id", "product_id")


def downgrade() -> None:
    for table in (
        "esop_work_release", "esop_production_plan", "esop_production_order",
        "esop_station", "esop_production_line", "esop_workshop",
    ):
        op.drop_table(table)
