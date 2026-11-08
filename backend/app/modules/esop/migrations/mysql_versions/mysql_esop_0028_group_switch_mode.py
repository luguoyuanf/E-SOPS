"""Configurable group transition and monotonic station task cursor."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0028"
down_revision = "mysql_esop_0027"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("esop_production_plan_group", sa.Column("switch_mode", sa.String(16), nullable=False, server_default="together"))
    op.add_column("esop_station", sa.Column("current_release_id", sa.Uuid(), nullable=True))


def downgrade():
    groups = sa.table("esop_production_plan_group", sa.column("switch_mode", sa.String(16)))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(groups).where(groups.c.switch_mode == "independent")):
        raise RuntimeError("Cannot downgrade while independent task groups exist")
    op.drop_column("esop_station", "current_release_id")
    op.drop_column("esop_production_plan_group", "switch_mode")
