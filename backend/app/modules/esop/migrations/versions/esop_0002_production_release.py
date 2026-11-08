"""Add workshop, order, plan and immutable release tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "esop_0002_production_release"
down_revision = "esop_0001_process_sop"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE esop.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE esop.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY esop_{table}_tenant ON esop.{table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def _indexes(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_esop_{table}_{column}", table, [column], schema="esop")


def upgrade() -> None:
    op.create_table(
        "workshop",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_esop_workshop_tenant_code"),
        schema="esop",
    )
    _indexes("workshop", "tenant_id")
    op.create_table(
        "production_line",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workshop_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("layout", sa.String(16), nullable=False),
        sa.Column("station_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_esop_line_tenant_code"),
        schema="esop",
    )
    _indexes("production_line", "tenant_id", "workshop_id")
    op.create_table(
        "station",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("row", sa.Integer(), nullable=False),
        sa.Column("column", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "line_id", "position", name="uq_esop_station_line_position"),
        schema="esop",
    )
    _indexes("station", "tenant_id", "line_id")
    op.create_table(
        "production_order",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_esop_order_tenant_code"),
        schema="esop",
    )
    _indexes("production_order", "tenant_id", "product_id")
    op.create_table(
        "production_plan",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("route_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("assignments", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="esop",
    )
    _indexes("production_plan", "tenant_id", "order_id", "line_id", "route_id")
    op.create_table(
        "work_release",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("assignments", JSONB(), nullable=False),
        sa.Column("published_by", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "plan_id", "version", name="uq_esop_release_plan_version"),
        schema="esop",
    )
    _indexes("work_release", "tenant_id", "plan_id", "order_id", "line_id", "product_id")
    for table in (
        "workshop", "production_line", "station", "production_order",
        "production_plan", "work_release",
    ):
        _rls(table)


def downgrade() -> None:
    for table in (
        "work_release", "production_plan", "production_order", "station",
        "production_line", "workshop",
    ):
        op.drop_table(table, schema="esop")
