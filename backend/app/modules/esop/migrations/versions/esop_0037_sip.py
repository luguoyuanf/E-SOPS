"""Record inspected quantities against reported production."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "esop_0037_sip"
down_revision = "esop_0036_media_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sip_inspection",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("terminal_id", sa.Uuid(), nullable=False),
        sa.Column("staff_user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("report_allocations", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "terminal_id", "request_id", name="uq_esop_sip_terminal_request"),
        schema="esop",
    )
    for column in ("tenant_id", "release_id", "operation_id", "station_id", "terminal_id"):
        op.create_index(f"ix_esop_sip_inspection_{column}", "sip_inspection", [column], schema="esop")
    op.execute("ALTER TABLE esop.sip_inspection ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE esop.sip_inspection FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY esop_sip_inspection_tenant ON esop.sip_inspection "
               "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN "
               "GRANT SELECT, INSERT ON esop.sip_inspection TO app_runtime; END IF; END $$")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS esop_sip_inspection_tenant ON esop.sip_inspection")
    op.drop_table("sip_inspection", schema="esop")
