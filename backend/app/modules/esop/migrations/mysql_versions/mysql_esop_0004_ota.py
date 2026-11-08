"""Global channel models and matching OTA packages for MySQL 5.7."""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0004"
down_revision = "mysql_esop_0003"
branch_labels = None
depends_on = None

OPTIONS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade():
    for table in ("esop_activation_key", "esop_terminal"):
        op.add_column(table, sa.Column("channel_id", sa.Uuid()))
        op.add_column(table, sa.Column("hardware_model_id", sa.Uuid()))
    op.create_table("esop_channel",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False), **OPTIONS)
    op.create_table("esop_hardware_model",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("abi", sa.String(30), nullable=False),
        sa.UniqueConstraint("channel_id", "code", name="uq_esop_hardware_channel_code"), **OPTIONS)
    op.create_index("ix_esop_hardware_model_channel_id", "esop_hardware_model", ["channel_id"])
    op.create_table("esop_ota_package",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("hardware_model_id", sa.Uuid(), nullable=False),
        sa.Column("file_owner_tenant_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("version_code", sa.Integer(), nullable=False),
        sa.Column("package_name", sa.String(200), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("published_at", mysql.DATETIME(fsp=6)),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("hardware_model_id", "version", name="uq_esop_ota_model_version"), **OPTIONS)
    for column in ("channel_id", "hardware_model_id"):
        op.create_index(f"ix_esop_ota_package_{column}", "esop_ota_package", [column])
    op.bulk_insert(
        sa.table("esop_channel", sa.column("id", sa.Uuid()), sa.column("code", sa.String()), sa.column("name", sa.String())),
        [{"id": uuid.UUID("7d78561a-ae5e-4ea8-a283-b9b01af49101"), "code": "DIRECT", "name": "直客"}],
    )
    op.bulk_insert(
        sa.table("esop_hardware_model", sa.column("id", sa.Uuid()), sa.column("channel_id", sa.Uuid()), sa.column("code", sa.String()), sa.column("name", sa.String()), sa.column("abi", sa.String())),
        [{"id": uuid.UUID("7d78561a-ae5e-4ea8-a283-b9b01af49102"), "channel_id": uuid.UUID("7d78561a-ae5e-4ea8-a283-b9b01af49101"), "code": "A133", "name": "A133", "abi": "armeabi-v7a"}],
    )


def downgrade():
    op.drop_table("esop_ota_package")
    op.drop_table("esop_hardware_model")
    op.drop_table("esop_channel")
    for table in ("esop_terminal", "esop_activation_key"):
        op.drop_column(table, "hardware_model_id")
        op.drop_column(table, "channel_id")
