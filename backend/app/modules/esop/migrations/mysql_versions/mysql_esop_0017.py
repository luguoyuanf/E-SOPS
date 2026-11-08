"""Configurable station numbering and names; preserve existing identities."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0017"
down_revision = "mysql_esop_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("esop_production_line", sa.Column("numbering_mode", sa.String(16), nullable=False, server_default="odd_even"))
    op.add_column("esop_station", sa.Column("name", sa.String(100), nullable=False, server_default=""))
    op.alter_column("esop_production_line", "numbering_mode", existing_type=sa.String(16), server_default=None)
    op.alter_column("esop_station", "name", existing_type=sa.String(100), server_default=None)


def downgrade() -> None:
    op.drop_column("esop_station", "name")
    op.drop_column("esop_production_line", "numbering_mode")
