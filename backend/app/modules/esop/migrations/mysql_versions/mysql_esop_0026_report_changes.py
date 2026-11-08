"""Manager review of terminal report change requests; effective reports stay intact."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0026"
down_revision = "mysql_esop_0025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("esop_production_report_change",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("requested_by_name", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_name", sa.String(255), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=True),
        sa.UniqueConstraint("tenant_id", "report_id", "request_id", name="uq_esop_report_change_request"), mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci", mysql_engine="InnoDB")
    op.create_index("ix_esop_production_report_change_tenant_id", "esop_production_report_change", ["tenant_id"])
    op.create_index("ix_esop_production_report_change_report_id", "esop_production_report_change", ["report_id"])


def downgrade():
    rows = sa.table("esop_production_report_change", sa.column("id", sa.Uuid()))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(rows)):
        raise RuntimeError("Cannot downgrade while report change requests exist")
    op.drop_table("esop_production_report_change")
