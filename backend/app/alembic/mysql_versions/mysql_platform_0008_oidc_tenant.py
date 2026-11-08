"""Pin Google identities and one-use login tickets to a tenant."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_platform_0008"
down_revision = "mysql_platform_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("enterpriseoidcauthorizationstate", sa.Column("purpose", sa.String(16), nullable=False, server_default="login"))
    op.add_column("enterpriseoidcauthorizationstate", sa.Column("binding_user_id", sa.Uuid(), nullable=True))
    op.add_column("enterpriseoidcauthorizationstate", sa.Column("binding_tenant_id", sa.Uuid(), nullable=True))
    op.add_column("enterpriseoidcauthorizationstate", sa.Column("binding_session_jti", sa.String(64), nullable=True))
    for table in ("enterpriseoidcidentity", "enterpriseoidcloginticket"):
        op.add_column(table, sa.Column("tenant_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(f"fk_{table}_tenant_id", table, "tenant", ["tenant_id"], ["id"])
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in ("enterpriseoidcloginticket", "enterpriseoidcidentity"):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")
    for column in ("binding_session_jti", "binding_tenant_id", "binding_user_id", "purpose"):
        op.drop_column("enterpriseoidcauthorizationstate", column)
