"""Tenant broadcast settings for MySQL 5.7."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0006"
down_revision = "mysql_esop_0005"
branch_labels = None
depends_on = None

OPTIONS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade():
    op.create_table("esop_broadcast",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.String(8), nullable=False),
        sa.Column("content", sa.String(500), nullable=False),
        sa.Column("font_size", sa.Integer(), nullable=False),
        sa.Column("background_color", sa.String(7), nullable=False),
        sa.Column("font_color", sa.String(7), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("tenant_id", "position", name="uq_esop_broadcast_tenant_position"),
        **OPTIONS)
    op.create_index("ix_esop_broadcast_tenant_id", "esop_broadcast", ["tenant_id"])


def downgrade():
    op.drop_table("esop_broadcast")
