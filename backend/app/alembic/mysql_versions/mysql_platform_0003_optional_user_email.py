"""Allow username login accounts without an email address."""
from alembic import op
import sqlalchemy as sa

revision = "mysql_platform_0003"
down_revision = "mysql_platform_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("user", "email", existing_type=sa.String(255), nullable=True)


def downgrade():
    users = sa.table("user", sa.column("email"))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(users).where(users.c.email.is_(None))):
        raise RuntimeError("Assign emails to all users before downgrading")
    op.alter_column("user", "email", existing_type=sa.String(255), nullable=False)
