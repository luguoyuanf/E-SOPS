"""Configurable group transition and monotonic station task cursor."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0028_group_switch_mode"
down_revision = "esop_0027_report_deletion"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("production_plan_group", sa.Column("switch_mode", sa.String(16), nullable=False, server_default="together"), schema="esop")
    op.add_column("station", sa.Column("current_release_id", sa.Uuid(), nullable=True), schema="esop")


def downgrade():
    groups = sa.table("production_plan_group", sa.column("switch_mode", sa.String(16)), schema="esop")
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(groups).where(groups.c.switch_mode == "independent")):
        raise RuntimeError("Cannot downgrade while independent task groups exist")
    op.drop_column("station", "current_release_id", schema="esop")
    op.drop_column("production_plan_group", "switch_mode", schema="esop")
