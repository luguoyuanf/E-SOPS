"""Add an optional product model separate from specification."""

import sqlalchemy as sa
from alembic import op

revision = "erp_product_model"
down_revision = "erp_platform_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("product", sa.Column("model", sa.String(100), nullable=True), schema="erp")


def downgrade() -> None:
    op.drop_column("product", "model", schema="erp")
