"""Allow device-independent web reporting with operator attribution and retry safety."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0020"
down_revision = "mysql_esop_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("esop_production_report", "terminal_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("esop_production_report", sa.Column("submitted_by", sa.Uuid(), nullable=True))
    op.create_unique_constraint("uq_esop_report_web_request", "esop_production_report", ["tenant_id", "submitted_by", "request_id"])


def downgrade():
    reports = sa.table("esop_production_report", sa.column("terminal_id", sa.Uuid()))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(reports).where(reports.c.terminal_id.is_(None))):
        raise RuntimeError("Cannot downgrade while web reports exist; preserve the reporting history")
    op.drop_constraint("uq_esop_report_web_request", "esop_production_report", type_="unique")
    op.drop_column("esop_production_report", "submitted_by")
    op.alter_column("esop_production_report", "terminal_id", existing_type=sa.Uuid(), nullable=False)
