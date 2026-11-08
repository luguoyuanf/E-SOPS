"""Keep employee hire date on the tenant membership, separate from shared identity."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_platform_0006"
down_revision = "mysql_platform_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenantmembership", sa.Column("hire_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenantmembership", "hire_date")
