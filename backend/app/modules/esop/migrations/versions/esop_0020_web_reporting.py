"""Allow device-independent web reporting with operator attribution and retry safety."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0020_web_reporting"
down_revision = "esop_0019_advertisements"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("production_report", "terminal_id", existing_type=sa.Uuid(), nullable=True, schema="esop")
    op.add_column("production_report", sa.Column("submitted_by", sa.Uuid(), nullable=True), schema="esop")
    op.create_unique_constraint("uq_esop_report_web_request", "production_report", ["tenant_id", "submitted_by", "request_id"], schema="esop")


def downgrade():
    reports = sa.table("production_report", sa.column("terminal_id", sa.Uuid()), schema="esop")
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(reports).where(reports.c.terminal_id.is_(None))):
        raise RuntimeError("Cannot downgrade while web reports exist; preserve the reporting history")
    op.drop_constraint("uq_esop_report_web_request", "production_report", type_="unique", schema="esop")
    op.drop_column("production_report", "submitted_by", schema="esop")
    op.alter_column("production_report", "terminal_id", existing_type=sa.Uuid(), nullable=False, schema="esop")
