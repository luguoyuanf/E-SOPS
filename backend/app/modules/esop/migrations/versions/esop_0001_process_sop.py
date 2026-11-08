"""Initial tenant-owned process and SOP version tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "esop_0001_process_sop"
down_revision = None
branch_labels = ("esop",)
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE esop.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE esop.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY esop_{table}_tenant ON esop.{table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS esop")
    op.create_table(
        "operation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_esop_operation_tenant_code"),
        schema="esop",
    )
    op.create_index("ix_esop_operation_tenant_id", "operation", ["tenant_id"], schema="esop")
    op.create_table(
        "process_route",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("operation_ids", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_esop_route_tenant_code"),
        schema="esop",
    )
    op.create_index("ix_esop_process_route_tenant_id", "process_route", ["tenant_id"], schema="esop")
    op.create_table(
        "sop_document",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("pages", JSONB(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid()),
        sa.Column("review_note", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "family_id", "version", name="uq_esop_sop_family_version"),
        sa.UniqueConstraint("tenant_id", "product_id", "operation_id", "version", name="uq_esop_sop_product_operation_version"),
        schema="esop",
    )
    for column in ("tenant_id", "family_id", "product_id", "operation_id"):
        op.create_index(f"ix_esop_sop_document_{column}", "sop_document", [column], schema="esop")
    for table in ("operation", "process_route", "sop_document"):
        _rls(table)


def downgrade() -> None:
    for table in ("sop_document", "process_route", "operation"):
        op.drop_table(table, schema="esop")
    op.execute("DROP SCHEMA IF EXISTS esop")
