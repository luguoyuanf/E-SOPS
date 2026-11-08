"""Add ESOP enterprise storage entitlements and annual grants."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_platform_0004"
down_revision = "mysql_platform_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "esoptenantstorage",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("base_bytes", sa.BigInteger(), nullable=False, server_default="104857600"),
        sa.Column("certified_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "esopstoragegrant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("capacity_bytes", sa.BigInteger(), nullable=False),
        sa.Column("starts_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("ix_esopstoragegrant_tenant_id", "esopstoragegrant", ["tenant_id"])
    op.execute("""CREATE TRIGGER esopstoragegrant_valid_bi BEFORE INSERT ON esopstoragegrant
        FOR EACH ROW BEGIN
            IF NEW.capacity_bytes <= 0 OR NEW.expires_at <= NEW.starts_at THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Invalid ESOP storage grant';
            END IF;
        END""")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS esopstoragegrant_valid_bi")
    op.drop_index("ix_esopstoragegrant_tenant_id", table_name="esopstoragegrant")
    op.drop_table("esopstoragegrant")
    op.drop_table("esoptenantstorage")
