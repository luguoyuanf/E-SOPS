"""Keep employee hire date on the tenant membership, separate from shared identity."""
import sqlalchemy as sa
from alembic import op

revision = "f2d6e0a4b8c3"
down_revision = "f1c5d9e3a7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenantmembership", sa.Column("hire_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenantmembership", "hire_date")
