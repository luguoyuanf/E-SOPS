"""Track alarm resolution without changing original alarm details."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0030"
down_revision = "mysql_esop_0029"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("esop_alarm_event", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("esop_alarm_event", sa.Column("resolved_by", sa.Uuid(), nullable=True))


def downgrade():
    alarms = sa.table("esop_alarm_event", sa.column("resolved_at", sa.DateTime(timezone=True)))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(alarms).where(alarms.c.resolved_at.is_not(None))):
        raise RuntimeError("Cannot downgrade while resolved alarms exist")
    op.drop_column("esop_alarm_event", "resolved_by")
    op.drop_column("esop_alarm_event", "resolved_at")
