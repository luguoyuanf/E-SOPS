"""Record the last network address seen on terminal heartbeat."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0034_terminal_ip"
down_revision = "esop_0033_order_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("terminal", sa.Column("last_ip", sa.String(45), nullable=True), schema="esop")


def downgrade() -> None:
    op.drop_column("terminal", "last_ip", schema="esop")
