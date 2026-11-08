"""Track alarm resolution without changing original alarm details."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0030_alarm_resolution"
down_revision = "esop_0029_alarm_staff"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("alarm_event", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True), schema="esop")
    op.add_column("alarm_event", sa.Column("resolved_by", sa.Uuid(), nullable=True), schema="esop")


def downgrade():
    alarms = sa.table("alarm_event", sa.column("resolved_at", sa.DateTime(timezone=True)), schema="esop")
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(alarms).where(alarms.c.resolved_at.is_not(None))):
        raise RuntimeError("Cannot downgrade while resolved alarms exist")
    op.drop_column("alarm_event", "resolved_by", schema="esop")
    op.drop_column("alarm_event", "resolved_at", schema="esop")
