"""Record authenticated alarm ownership; historical alarms remain unassigned."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0029"
down_revision = "mysql_esop_0028"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("esop_alarm_event", sa.Column("staff_user_id", sa.Uuid(), nullable=True))
    op.create_index("ix_esop_alarm_event_staff_user_id", "esop_alarm_event", ["staff_user_id"])


def downgrade():
    alarms = sa.table("esop_alarm_event", sa.column("staff_user_id", sa.Uuid()))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(alarms).where(alarms.c.staff_user_id.is_not(None))):
        raise RuntimeError("Cannot downgrade while user-owned alarms exist")
    op.drop_index("ix_esop_alarm_event_staff_user_id", table_name="esop_alarm_event")
    op.drop_column("esop_alarm_event", "staff_user_id")
