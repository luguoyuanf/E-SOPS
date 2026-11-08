"""Persist product operation ordering; retain existing code order for ties."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0012_operation_order"
down_revision = "esop_0011_operation_product"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operation", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"), schema="esop")


def downgrade() -> None:
    op.drop_column("operation", "sort_order", schema="esop")
