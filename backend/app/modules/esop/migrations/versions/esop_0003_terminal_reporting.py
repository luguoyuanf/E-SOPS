"""Terminal activation, offline reports and alarm trace."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0003_terminal_reporting"
down_revision = "esop_0002_production_release"
branch_labels = None
depends_on = None


def _base(table, *columns, unique=()):
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        *columns,
        *unique,
        schema="esop",
    )
    op.create_index(f"ix_esop_{table}_tenant_id", table, ["tenant_id"], schema="esop")


def _index(table, *columns):
    for column in columns:
        op.create_index(f"ix_esop_{table}_{column}", table, [column], schema="esop")


def _rls(table):
    op.execute(f"ALTER TABLE esop.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE esop.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY esop_{table}_tenant ON esop.{table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade():
    op.add_column("work_release", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), schema="esop")
    _base("activation_key",
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("grant_type", sa.String(8), nullable=False, server_default="paid"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("used_terminal_id", sa.Uuid()),
    )
    _base("device_credential",
        sa.Column("device_code", sa.String(120), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("terminal_id", sa.Uuid(), nullable=False, unique=True),
    )
    _base("terminal",
        sa.Column("device_code", sa.String(120), nullable=False),
        sa.Column("station_id", sa.Uuid()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("app_version", sa.String(80)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        unique=(sa.UniqueConstraint("tenant_id", "device_code", name="uq_esop_terminal_tenant_device"),),
    )
    _index("terminal", "station_id")
    _base("production_report",
        sa.Column("terminal_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("staff_user_id", sa.Uuid(), nullable=False),
        sa.Column("staff_name", sa.String(200), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("order_code", sa.String(60), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("station_position", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("sop_id", sa.Uuid(), nullable=False),
        sa.Column("sop_version", sa.Integer(), nullable=False),
        sa.Column("sop_title", sa.String(200), nullable=False),
        sa.Column("input_qty", sa.Integer(), nullable=False),
        sa.Column("good_qty", sa.Integer(), nullable=False),
        sa.Column("defect_qty", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        unique=(sa.UniqueConstraint("tenant_id", "terminal_id", "request_id", name="uq_esop_report_device_request"),),
    )
    _index("production_report", "terminal_id", "staff_user_id", "release_id", "order_id", "station_id", "operation_id", "sop_id")
    _base("alarm_event",
        sa.Column("terminal_id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("release_id", sa.Uuid()),
        sa.Column("level", sa.String(12), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        unique=(sa.UniqueConstraint("tenant_id", "terminal_id", "request_id", name="uq_esop_alarm_device_request"),),
    )
    _index("alarm_event", "terminal_id", "station_id", "release_id")
    for table in ("terminal", "production_report", "alarm_event"):
        _rls(table)


def downgrade():
    for table in ("alarm_event", "production_report", "terminal", "device_credential", "activation_key"):
        op.drop_table(table, schema="esop")
    op.drop_column("work_release", "is_active", schema="esop")
