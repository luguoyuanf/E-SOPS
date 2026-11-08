"""Remember an operator's selected production task at each station."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0035"
down_revision = "mysql_esop_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("esop_station", sa.Column("selected_release_id", sa.Uuid(), nullable=True))
    op.add_column("esop_station", sa.Column("selected_by", sa.Uuid(), nullable=True))
    op.add_column("esop_station", sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("esop_station", "selected_at")
    op.drop_column("esop_station", "selected_by")
    op.drop_column("esop_station", "selected_release_id")
