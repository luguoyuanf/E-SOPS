"""Tenant broadcast settings for terminal tickers."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0006_broadcast"
down_revision = "esop_0005_channel_inventory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("broadcast",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.String(8), nullable=False),
        sa.Column("content", sa.String(500), nullable=False),
        sa.Column("font_size", sa.Integer(), nullable=False),
        sa.Column("background_color", sa.String(7), nullable=False),
        sa.Column("font_color", sa.String(7), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "position", name="uq_esop_broadcast_tenant_position"),
        schema="esop")
    op.create_index("ix_esop_broadcast_tenant_id", "broadcast", ["tenant_id"], schema="esop")
    op.execute("ALTER TABLE esop.broadcast ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE esop.broadcast FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY esop_broadcast_tenant ON esop.broadcast "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade():
    op.drop_table("broadcast", schema="esop")
