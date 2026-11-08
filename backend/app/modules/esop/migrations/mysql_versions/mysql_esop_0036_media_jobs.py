"""Persist operation attachment conversion jobs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0036"
down_revision = "mysql_esop_0035"
branch_labels = None
depends_on = None
OPTIONS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    op.create_table(
        "esop_operation_media_job",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("original_file_id", sa.Uuid(), nullable=False),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(255), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("tenant_id", "original_file_id", name="uq_esop_operation_media_job_file"),
        **OPTIONS,
    )
    op.create_index("ix_esop_operation_media_job_tenant_id", "esop_operation_media_job", ["tenant_id"])
    op.create_index("ix_esop_operation_media_job_original_file_id", "esop_operation_media_job", ["original_file_id"])


def downgrade() -> None:
    op.drop_index("ix_esop_operation_media_job_original_file_id", table_name="esop_operation_media_job")
    op.drop_index("ix_esop_operation_media_job_tenant_id", table_name="esop_operation_media_job")
    op.drop_table("esop_operation_media_job")
