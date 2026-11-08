"""Scheduled multimedia advertisements, independent of ticker settings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0019"
down_revision = "mysql_esop_0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("esop_advertisement",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("layout", sa.String(16), nullable=False),
        sa.Column("playback", sa.String(16), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("starts_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("ends_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("daily_start", sa.String(5), nullable=True),
        sa.Column("daily_end", sa.String(5), nullable=True),
        sa.Column("media", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False), mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci", mysql_engine="InnoDB")
    op.create_index("ix_esop_advertisement_tenant_id", "esop_advertisement", ["tenant_id"])


def downgrade():
    op.drop_table("esop_advertisement")
