"""Give existing and new production plans a tenant-unique business code."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0018_plan_code"
down_revision = "esop_0017_station_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("production_plan", sa.Column("code", sa.String(50), nullable=True), schema="esop")
    plans = sa.table(
        "production_plan",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("code", sa.String(50)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        schema="esop",
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
    op.alter_column("production_plan", "code", existing_type=sa.String(50), nullable=False, schema="esop")
    op.create_unique_constraint(
        "uq_esop_production_plan_tenant_code", "production_plan", ["tenant_id", "code"], schema="esop"
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_esop_production_plan_tenant_code", "production_plan", type_="unique", schema="esop"
    )
    op.drop_column("production_plan", "code", schema="esop")
