"""Allow new production plans to use approved product SOPs without a process route."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0013_sop_direct_publish"
down_revision = "esop_0012_operation_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("production_plan", "route_id", schema="esop", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM esop.production_plan WHERE route_id IS NULL")).scalar_one():
        raise RuntimeError("Cannot downgrade while route-free production plans exist")
    op.alter_column("production_plan", "route_id", schema="esop", existing_type=sa.Uuid(), nullable=False)
