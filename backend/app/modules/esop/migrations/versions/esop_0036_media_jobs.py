"""Persist operation attachment conversion jobs."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0036_media_jobs"
down_revision = "esop_0035_station_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_media_job",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("original_file_id", sa.Uuid(), nullable=False),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "original_file_id", name="uq_esop_operation_media_job_file"),
        schema="esop",
    )
    op.create_index("ix_esop_operation_media_job_tenant_id", "operation_media_job", ["tenant_id"], schema="esop")
    op.create_index("ix_esop_operation_media_job_original_file_id", "operation_media_job", ["original_file_id"], schema="esop")
    op.execute("ALTER TABLE esop.operation_media_job ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE esop.operation_media_job FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY esop_operation_media_job_tenant ON esop.operation_media_job "
               "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN "
               "GRANT SELECT, INSERT, UPDATE ON esop.operation_media_job TO app_runtime; END IF; END $$")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS esop_operation_media_job_tenant ON esop.operation_media_job")
    op.drop_index("ix_esop_operation_media_job_original_file_id", table_name="operation_media_job", schema="esop")
    op.drop_index("ix_esop_operation_media_job_tenant_id", table_name="operation_media_job", schema="esop")
    op.drop_table("operation_media_job", schema="esop")
