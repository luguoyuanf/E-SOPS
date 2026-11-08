"""Persist product operation ordering; retain existing code order for ties."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0012"
down_revision = "mysql_esop_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("esop_operation", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"), schema=None)


def downgrade() -> None:
    op.drop_column("esop_operation", "sort_order", schema=None)
