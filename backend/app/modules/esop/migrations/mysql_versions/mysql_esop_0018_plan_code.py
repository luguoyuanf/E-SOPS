"""Give existing and new production plans a tenant-unique business code."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0018"
down_revision = "mysql_esop_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("esop_production_plan", sa.Column("code", sa.String(50), nullable=True))
    plans = sa.table(
        "esop_production_plan",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("code", sa.String(50)),
        sa.column("created_at", sa.DateTime()),
    )
    counts = {}
    connection = op.get_bind()
    for plan_id, tenant_id in connection.execute(
        sa.select(plans.c.id, plans.c.tenant_id).order_by(plans.c.tenant_id, plans.c.created_at, plans.c.id)
    ):
        counts[tenant_id] = counts.get(tenant_id, 0) + 1
        connection.execute(
            sa.update(plans).where(plans.c.id == plan_id).values(code=f"PLAN{counts[tenant_id]:08d}")
        )
    op.alter_column("esop_production_plan", "code", existing_type=sa.String(50), nullable=False)
    op.create_unique_constraint(
        "uq_esop_production_plan_tenant_code", "esop_production_plan", ["tenant_id", "code"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_esop_production_plan_tenant_code", "esop_production_plan", type_="unique")
    op.drop_column("esop_production_plan", "code")
