"""Auditable tenant-scoped report corrections with optimistic concurrency."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0021"
down_revision = "mysql_esop_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("esop_production_report", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("esop_production_report", "revision", existing_type=sa.Integer(), server_default=None)
    op.create_table("esop_production_report_revision",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=False),
        sa.Column("changed_by_name", sa.String(255), nullable=False),
        sa.Column("changed_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.UniqueConstraint("tenant_id", "report_id", "revision", name="uq_esop_report_revision"), mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci", mysql_engine="InnoDB")
    op.create_index("ix_esop_production_report_revision_tenant_id", "esop_production_report_revision", ["tenant_id"])
    op.create_index("ix_esop_production_report_revision_report_id", "esop_production_report_revision", ["report_id"])


def downgrade():
    history = sa.table("esop_production_report_revision", sa.column("id", sa.Uuid()))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(history)):
        raise RuntimeError("Cannot downgrade while report correction history exists")
    op.drop_table("esop_production_report_revision")
    op.drop_column("esop_production_report", "revision")
