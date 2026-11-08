"""Remember an operator's selected production task at each station."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0035_station_selection"
down_revision = "esop_0034_terminal_ip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("station", sa.Column("selected_release_id", sa.Uuid(), nullable=True), schema="esop")
    op.add_column("station", sa.Column("selected_by", sa.Uuid(), nullable=True), schema="esop")
    op.add_column("station", sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True), schema="esop")


def downgrade() -> None:
    op.drop_column("station", "selected_at", schema="esop")
    op.drop_column("station", "selected_by", schema="esop")
    op.drop_column("station", "selected_release_id", schema="esop")
