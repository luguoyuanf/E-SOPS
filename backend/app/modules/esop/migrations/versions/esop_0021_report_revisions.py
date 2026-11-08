"""Auditable tenant-scoped report corrections with optimistic concurrency."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "esop_0021_report_revisions"
down_revision = "esop_0020_web_reporting"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("production_report", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"), schema="esop")
    op.alter_column("production_report", "revision", existing_type=sa.Integer(), server_default=None, schema="esop")
    op.create_table("production_report_revision",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=False),
        sa.Column("changed_by_name", sa.String(255), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("tenant_id", "report_id", "revision", name="uq_esop_report_revision"), schema="esop")
    op.create_index("ix_esop_production_report_revision_tenant_id", "production_report_revision", ["tenant_id"], schema="esop")
    op.create_index("ix_esop_production_report_revision_report_id", "production_report_revision", ["report_id"], schema="esop")
    op.execute("ALTER TABLE esop.production_report_revision ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE esop.production_report_revision FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY esop_report_revision_tenant ON esop.production_report_revision "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN GRANT SELECT, INSERT ON esop.production_report_revision TO app_runtime; END IF; END $$")


def downgrade():
    history = sa.table("production_report_revision", sa.column("id", sa.Uuid()), schema="esop")
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(history)):
        raise RuntimeError("Cannot downgrade while report correction history exists")
    op.drop_table("production_report_revision", schema="esop")
    op.drop_column("production_report", "revision", schema="esop")
