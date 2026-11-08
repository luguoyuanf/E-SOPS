"""Track the current back-office session on the global user identity."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_platform_0007"
down_revision = "mysql_platform_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user", sa.Column("current_backoffice_jti", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user", "current_backoffice_jti")
