"""Scope login usernames to tenant memberships."""
import sqlalchemy as sa
from alembic import op

revision = "f4e8b2c6d0a5"
down_revision = "f3e7a1b5c9d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenantmembership", sa.Column("username", sa.String(64), nullable=True))
    op.execute('UPDATE tenantmembership AS m SET username = u.username FROM "user" AS u WHERE u.id = m.user_id')
    op.create_unique_constraint("uq_tenantmembership_tenant_username", "tenantmembership", ["tenant_id", "username"])
    op.drop_index("ix_user_username", table_name="user")
    op.create_index("ix_user_username", "user", ["username"], unique=False)


def downgrade():
    connection = op.get_bind()
    duplicates = connection.execute(sa.text('SELECT COUNT(*) FROM (SELECT username FROM "user" WHERE username IS NOT NULL GROUP BY username HAVING COUNT(*) > 1) duplicate_names')).scalar()
    if duplicates:
        raise RuntimeError("Cannot restore global username uniqueness while duplicate usernames exist")
    op.drop_index("ix_user_username", table_name="user")
    op.create_index("ix_user_username", "user", ["username"], unique=True)
    op.drop_constraint("uq_tenantmembership_tenant_username", "tenantmembership", type_="unique")
    op.drop_column("tenantmembership", "username")
