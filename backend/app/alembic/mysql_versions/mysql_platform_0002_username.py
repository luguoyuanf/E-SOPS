"""Add an optional globally unique username without changing existing emails."""
from alembic import op
import sqlalchemy as sa

revision = 'mysql_platform_0002'
down_revision = 'mysql_platform_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('username', sa.String(64), nullable=True))
    op.create_index('ix_user_username', 'user', ['username'], unique=True)


def downgrade():
    op.drop_index('ix_user_username', table_name='user')
    op.drop_column('user', 'username')
