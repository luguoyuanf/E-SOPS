"""Unassigned channel inventory and customer tenant links on MySQL 5.7."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0005"
down_revision = "mysql_esop_0004"
branch_labels = None
depends_on = None

OPTIONS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade():
    op.alter_column("esop_activation_key", "tenant_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("esop_activation_key", sa.Column("batch_id", sa.Uuid()))
    op.create_index("ix_esop_activation_key_batch_id", "esop_activation_key", ["batch_id"])
    op.create_table("esop_channel_admin",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False, unique=True),
        **OPTIONS)
    op.create_index("ix_esop_channel_admin_channel_id", "esop_channel_admin", ["channel_id"])
    op.create_table("esop_channel_customer_tenant",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        **OPTIONS)
    op.create_index("ix_esop_channel_customer_tenant_channel_id", "esop_channel_customer_tenant", ["channel_id"])


def downgrade():
    op.drop_table("esop_channel_customer_tenant")
    op.drop_table("esop_channel_admin")
    op.drop_index("ix_esop_activation_key_batch_id", table_name="esop_activation_key")
    op.drop_column("esop_activation_key", "batch_id")
    op.alter_column("esop_activation_key", "tenant_id", existing_type=sa.Uuid(), nullable=False)
