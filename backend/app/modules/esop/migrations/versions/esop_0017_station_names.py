"""Configurable station numbering and names; preserve existing identities."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0017_station_names"
down_revision = "esop_0016_plan_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("production_line", sa.Column("numbering_mode", sa.String(16), nullable=False, server_default="odd_even"), schema="esop")
    op.add_column("station", sa.Column("name", sa.String(100), nullable=False, server_default=""), schema="esop")
    op.alter_column("production_line", "numbering_mode", existing_type=sa.String(16), server_default=None, schema="esop")
    op.alter_column("station", "name", existing_type=sa.String(100), server_default=None, schema="esop")


def downgrade() -> None:
    op.drop_column("station", "name", schema="esop")
    op.drop_column("production_line", "numbering_mode", schema="esop")
