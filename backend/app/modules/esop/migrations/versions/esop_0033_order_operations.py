"""Pin selected operations on new or individually confirmed orders."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "esop_0033_order_operations"
down_revision = "esop_0032_plan_quantity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("production_order", sa.Column("product_sop_version_id", sa.Uuid(), nullable=True), schema="esop")
    op.add_column("production_order", sa.Column("operation_ids", JSONB(), nullable=True), schema="esop")
    op.create_index("ix_esop_production_order_product_sop_version_id", "production_order", ["product_sop_version_id"], schema="esop")


def downgrade() -> None:
    op.drop_index("ix_esop_production_order_product_sop_version_id", table_name="production_order", schema="esop")
    op.drop_column("production_order", "operation_ids", schema="esop")
    op.drop_column("production_order", "product_sop_version_id", schema="esop")
