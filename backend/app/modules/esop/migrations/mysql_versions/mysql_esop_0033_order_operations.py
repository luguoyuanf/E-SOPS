"""Pin selected operations on new or individually confirmed orders."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0033"
down_revision = "mysql_esop_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("esop_production_order", sa.Column("product_sop_version_id", sa.Uuid(), nullable=True))
    op.add_column("esop_production_order", sa.Column("operation_ids", sa.JSON(), nullable=True))
    op.create_index("ix_esop_production_order_product_sop_version_id", "esop_production_order", ["product_sop_version_id"])


def downgrade() -> None:
    op.drop_index("ix_esop_production_order_product_sop_version_id", table_name="esop_production_order")
    op.drop_column("esop_production_order", "operation_ids")
    op.drop_column("esop_production_order", "product_sop_version_id")
