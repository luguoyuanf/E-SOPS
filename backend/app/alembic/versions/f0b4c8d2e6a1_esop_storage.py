"""Add ESOP enterprise storage entitlements and annual grants."""

import sqlalchemy as sa
from alembic import op

revision = "f0b4c8d2e6a1"
down_revision = "e9a3c7b1d5f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "esoptenantstorage",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("base_bytes", sa.BigInteger(), nullable=False, server_default="104857600"),
        sa.Column("certified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "esopstoragegrant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("capacity_bytes", sa.BigInteger(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("capacity_bytes > 0 AND expires_at > starts_at", name="ck_esopstoragegrant_valid"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_esopstoragegrant_tenant_id", "esopstoragegrant", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_esopstoragegrant_tenant_id", table_name="esopstoragegrant")
    op.drop_table("esopstoragegrant")
    op.drop_table("esoptenantstorage")
