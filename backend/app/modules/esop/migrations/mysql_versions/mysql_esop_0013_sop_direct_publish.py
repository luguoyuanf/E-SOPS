"""Allow new production plans to use approved product SOPs without a process route."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0013"
down_revision = "mysql_esop_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("esop_production_plan", "route_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM esop_production_plan WHERE route_id IS NULL")).scalar_one():
        raise RuntimeError("Cannot downgrade while route-free production plans exist")
    op.alter_column("esop_production_plan", "route_id", existing_type=sa.Uuid(), nullable=False)
