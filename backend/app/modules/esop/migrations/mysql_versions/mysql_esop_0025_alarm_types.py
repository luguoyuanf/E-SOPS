"""Tenant alarm preferences and category snapshot on alarm events."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0025"
down_revision = "mysql_esop_0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("esop_alarm_event", sa.Column("type_code", sa.String(100), nullable=True))
    op.add_column("esop_alarm_event", sa.Column("type_name", sa.String(100), nullable=True))
    op.create_table(
        "esop_alarm_type_preference",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type_code", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "type_code", name="uq_esop_alarm_type_preference"),
        mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci", mysql_engine="InnoDB",
    )
    op.create_index("ix_esop_alarm_type_preference_tenant_id", "esop_alarm_type_preference", ["tenant_id"])


def downgrade():
    op.drop_table("esop_alarm_type_preference")
    op.drop_column("esop_alarm_event", "type_name")
    op.drop_column("esop_alarm_event", "type_code")
