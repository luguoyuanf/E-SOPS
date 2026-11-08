"""Tenant alarm preferences and category snapshot on alarm events."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0025_alarm_types"
down_revision = "esop_0024_terminal_installation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("alarm_event", sa.Column("type_code", sa.String(100), nullable=True), schema="esop")
    op.add_column("alarm_event", sa.Column("type_name", sa.String(100), nullable=True), schema="esop")
    op.create_table(
        "alarm_type_preference",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type_code", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "type_code", name="uq_esop_alarm_type_preference"),
        schema="esop",
    )
    op.create_index("ix_esop_alarm_type_preference_tenant_id", "alarm_type_preference", ["tenant_id"], schema="esop")
    op.execute("ALTER TABLE esop.alarm_type_preference ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE esop.alarm_type_preference FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY esop_alarm_type_preference_tenant ON esop.alarm_type_preference "
               "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN "
               "GRANT SELECT, INSERT, UPDATE ON esop.alarm_type_preference TO app_runtime; "
               "END IF; END $$")


def downgrade():
    op.drop_table("alarm_type_preference", schema="esop")
    op.drop_column("alarm_event", "type_name", schema="esop")
    op.drop_column("alarm_event", "type_code", schema="esop")
