"""Unassigned channel inventory and customer tenant links."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0005_channel_inventory"
down_revision = "esop_0004_ota"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("activation_key", "tenant_id", existing_type=sa.Uuid(), nullable=True, schema="esop")
    op.add_column("activation_key", sa.Column("batch_id", sa.Uuid()), schema="esop")
    op.create_index("ix_esop_activation_key_batch_id", "activation_key", ["batch_id"], schema="esop")
    op.create_table("channel_admin",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False, unique=True),
        schema="esop")
    op.create_index("ix_esop_channel_admin_channel_id", "channel_admin", ["channel_id"], schema="esop")
    op.create_table("channel_customer_tenant",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="esop")
    op.create_index("ix_esop_channel_customer_tenant_channel_id", "channel_customer_tenant", ["channel_id"], schema="esop")


def downgrade():
    op.drop_table("channel_customer_tenant", schema="esop")
    op.drop_table("channel_admin", schema="esop")
    op.drop_index("ix_esop_activation_key_batch_id", table_name="activation_key", schema="esop")
    op.drop_column("activation_key", "batch_id", schema="esop")
    op.alter_column("activation_key", "tenant_id", existing_type=sa.Uuid(), nullable=False, schema="esop")
