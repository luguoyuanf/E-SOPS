"""Preserve activation and revocation history."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0008"
down_revision = "esop_0007_recoverable_keys"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("activation_unbind_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("terminal_id", sa.Uuid(), nullable=False),
        sa.Column("device_code", sa.String(120), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False), schema="esop",
    )
    op.create_index("ix_activation_unbind_log_key_id", "activation_unbind_log", ["key_id"], schema="esop")


def downgrade():
    op.drop_table("activation_unbind_log", schema="esop")
