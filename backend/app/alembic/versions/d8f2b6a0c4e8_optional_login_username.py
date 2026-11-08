"""Optional globally unique username; existing email login is unchanged."""
from alembic import op
import sqlalchemy as sa

revision = 'd8f2b6a0c4e8'
down_revision = 'c7e1a5f9b3d6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('username', sa.String(64), nullable=True))
    op.create_index('ix_user_username', 'user', ['username'], unique=True)


def downgrade():
    op.drop_index('ix_user_username', table_name='user')
    op.drop_column('user', 'username')
