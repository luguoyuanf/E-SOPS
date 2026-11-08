"""Product-bound operations with private file references; preserve legacy rows."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0011"
down_revision = "mysql_esop_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("esop_operation", sa.Column("product_id", sa.Uuid(), nullable=True), schema=None)
    op.add_column("esop_operation", sa.Column("attachments", sa.JSON(), nullable=True), schema=None)
    op.execute(sa.text("UPDATE esop_operation SET attachments = '[]' WHERE attachments IS NULL"))
    op.alter_column("esop_operation", "attachments", existing_type=sa.JSON(), nullable=False, schema=None)
    op.create_index("ix_esop_operation_product_id", "esop_operation", ["product_id"], schema=None)


def downgrade() -> None:
    op.drop_index("ix_esop_operation_product_id", table_name="esop_operation", schema=None)
    op.drop_column("esop_operation", "attachments", schema=None)
    op.drop_column("esop_operation", "product_id", schema=None)
