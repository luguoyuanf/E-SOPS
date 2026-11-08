"""Report deletion requests retain facts while effective statistics exclude approved deletions."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0027"
down_revision = "mysql_esop_0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("esop_production_report", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("esop_production_report_change", sa.Column("kind", sa.String(16), nullable=False, server_default="edit"))


def downgrade():
    reports = sa.table("esop_production_report", sa.column("is_deleted", sa.Boolean()))
    changes = sa.table("esop_production_report_change", sa.column("kind", sa.String(16)))
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.func.count()).select_from(reports).where(reports.c.is_deleted == sa.true())) or bind.scalar(sa.select(sa.func.count()).select_from(changes).where(changes.c.kind == "delete")):
        raise RuntimeError("Cannot downgrade while report deletion audit exists")
    op.drop_column("esop_production_report_change", "kind")
    op.drop_column("esop_production_report", "is_deleted")
