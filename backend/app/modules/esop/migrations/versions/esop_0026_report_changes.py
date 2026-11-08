"""Manager review of terminal report change requests; effective reports stay intact."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "esop_0026_report_changes"
down_revision = "esop_0025_alarm_types"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("production_report_change",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("requested_by_name", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_name", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=True),
        sa.UniqueConstraint("tenant_id", "report_id", "request_id", name="uq_esop_report_change_request"), schema="esop")
    op.create_index("ix_esop_production_report_change_tenant_id", "production_report_change", ["tenant_id"], schema="esop")
    op.create_index("ix_esop_production_report_change_report_id", "production_report_change", ["report_id"], schema="esop")
    op.execute("ALTER TABLE esop.production_report_change ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE esop.production_report_change FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY esop_report_change_tenant ON esop.production_report_change "
               "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN GRANT SELECT, INSERT, UPDATE ON esop.production_report_change TO app_runtime; END IF; END $$")


def downgrade():
    rows = sa.table("production_report_change", sa.column("id", sa.Uuid()), schema="esop")
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(rows)):
        raise RuntimeError("Cannot downgrade while report change requests exist")
    op.drop_table("production_report_change", schema="esop")
