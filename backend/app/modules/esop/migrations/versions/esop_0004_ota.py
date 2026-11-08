"""Global channel models and matching OTA packages."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "esop_0004_ota"
down_revision = "esop_0003_terminal_reporting"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("activation_key", sa.Column("channel_id", sa.Uuid()), schema="esop")
    op.add_column("activation_key", sa.Column("hardware_model_id", sa.Uuid()), schema="esop")
    op.add_column("terminal", sa.Column("channel_id", sa.Uuid()), schema="esop")
    op.add_column("terminal", sa.Column("hardware_model_id", sa.Uuid()), schema="esop")
    op.create_table("channel",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False), schema="esop")
    op.create_table("hardware_model",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("abi", sa.String(30), nullable=False),
        sa.UniqueConstraint("channel_id", "code", name="uq_esop_hardware_channel_code"),
        schema="esop")
    op.create_index("ix_esop_hardware_model_channel_id", "hardware_model", ["channel_id"], schema="esop")
    op.create_table("ota_package",
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
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), schema="esop")
    for column in ("channel_id", "hardware_model_id"):
        op.create_index(f"ix_esop_ota_package_{column}", "ota_package", [column], schema="esop")
    op.create_unique_constraint("uq_esop_ota_model_version", "ota_package", ["hardware_model_id", "version"], schema="esop")
    op.create_index("uq_esop_ota_published_model", "ota_package", ["hardware_model_id"], unique=True, schema="esop", postgresql_where=sa.text("status = 'published'"))
    op.bulk_insert(
        sa.table("channel", sa.column("id", sa.Uuid()), sa.column("code", sa.String()), sa.column("name", sa.String()), schema="esop"),
        [{"id": uuid.UUID("7d78561a-ae5e-4ea8-a283-b9b01af49101"), "code": "DIRECT", "name": "直客"}],
    )
    op.bulk_insert(
        sa.table("hardware_model", sa.column("id", sa.Uuid()), sa.column("channel_id", sa.Uuid()), sa.column("code", sa.String()), sa.column("name", sa.String()), sa.column("abi", sa.String()), schema="esop"),
        [{"id": uuid.UUID("7d78561a-ae5e-4ea8-a283-b9b01af49102"), "channel_id": uuid.UUID("7d78561a-ae5e-4ea8-a283-b9b01af49101"), "code": "A133", "name": "A133", "abi": "armeabi-v7a"}],
    )


def downgrade():
    op.drop_table("ota_package", schema="esop")
    op.drop_table("hardware_model", schema="esop")
    op.drop_table("channel", schema="esop")
    op.drop_column("terminal", "hardware_model_id", schema="esop")
    op.drop_column("terminal", "channel_id", schema="esop")
    op.drop_column("activation_key", "hardware_model_id", schema="esop")
    op.drop_column("activation_key", "channel_id", schema="esop")
