"""Report deletion requests retain facts while effective statistics exclude approved deletions."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0027_report_deletion"
down_revision = "esop_0026_report_changes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("production_report", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()), schema="esop")
    op.add_column("production_report_change", sa.Column("kind", sa.String(16), nullable=False, server_default="edit"), schema="esop")


def downgrade():
    reports = sa.table("production_report", sa.column("is_deleted", sa.Boolean()), schema="esop")
    changes = sa.table("production_report_change", sa.column("kind", sa.String(16)), schema="esop")
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.func.count()).select_from(reports).where(reports.c.is_deleted == sa.true())) or bind.scalar(sa.select(sa.func.count()).select_from(changes).where(changes.c.kind == "delete")):
        raise RuntimeError("Cannot downgrade while report deletion audit exists")
    op.drop_column("production_report_change", "kind", schema="esop")
    op.drop_column("production_report", "is_deleted", schema="esop")
