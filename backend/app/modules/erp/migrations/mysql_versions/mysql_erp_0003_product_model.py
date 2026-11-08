"""Add an optional product model separate from specification."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_erp_0003_product_model"
down_revision = "mysql_erp_0002_platform_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("erp_product", sa.Column("model", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("erp_product", "model")
