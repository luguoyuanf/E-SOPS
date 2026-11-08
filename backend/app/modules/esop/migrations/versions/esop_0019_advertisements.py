"""Scheduled multimedia advertisements, independent of ticker settings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "esop_0019_advertisements"
down_revision = "esop_0018_plan_code"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("advertisement",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("layout", sa.String(16), nullable=False),
        sa.Column("playback", sa.String(16), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_start", sa.String(5), nullable=True),
        sa.Column("daily_end", sa.String(5), nullable=True),
        sa.Column("media", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), schema="esop")
    op.create_index("ix_esop_advertisement_tenant_id", "advertisement", ["tenant_id"], schema="esop")
    op.execute("ALTER TABLE esop.advertisement ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE esop.advertisement FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY esop_advertisement_tenant ON esop.advertisement "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade():
    op.drop_table("advertisement", schema="esop")
