"""Record the last network address seen on terminal heartbeat."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0034"
down_revision = "mysql_esop_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("esop_terminal", sa.Column("last_ip", sa.String(45), nullable=True))


def downgrade() -> None:
    op.drop_column("esop_terminal", "last_ip")
