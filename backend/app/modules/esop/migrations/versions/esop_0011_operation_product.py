"""Product-bound operations with private file references; preserve legacy rows."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "esop_0011_operation_product"
down_revision = "esop_0010_official_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operation", sa.Column("product_id", sa.Uuid(), nullable=True), schema="esop")
    op.add_column("operation", sa.Column("attachments", postgresql.JSONB(), nullable=True), schema="esop")
    op.execute(sa.text("UPDATE esop.operation SET attachments = '[]' WHERE attachments IS NULL"))
    op.alter_column("operation", "attachments", existing_type=postgresql.JSONB(), nullable=False, schema="esop")
    op.create_index("ix_esop_operation_product_id", "operation", ["product_id"], schema="esop")


def downgrade() -> None:
    op.drop_index("ix_esop_operation_product_id", table_name="operation", schema="esop")
    op.drop_column("operation", "attachments", schema="esop")
    op.drop_column("operation", "product_id", schema="esop")
