"""Record authenticated alarm ownership; historical alarms remain unassigned."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0029_alarm_staff"
down_revision = "esop_0028_group_switch_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("alarm_event", sa.Column("staff_user_id", sa.Uuid(), nullable=True), schema="esop")
    op.create_index("ix_alarm_event_staff_user_id", "alarm_event", ["staff_user_id"], schema="esop")


def downgrade():
    alarms = sa.table("alarm_event", sa.column("staff_user_id", sa.Uuid()), schema="esop")
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(alarms).where(alarms.c.staff_user_id.is_not(None))):
        raise RuntimeError("Cannot downgrade while user-owned alarms exist")
    op.drop_index("ix_alarm_event_staff_user_id", table_name="alarm_event", schema="esop")
    op.drop_column("alarm_event", "staff_user_id", schema="esop")
