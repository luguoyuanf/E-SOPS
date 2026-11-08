"""Give each production plan its own order allocation."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0032"
down_revision = "mysql_esop_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("esop_production_plan", sa.Column("quantity", sa.Integer(), nullable=True))
    plan = sa.table("esop_production_plan", sa.column("order_id", sa.Uuid()), sa.column("quantity", sa.Integer()))
    order = sa.table("esop_production_order", sa.column("id", sa.Uuid()), sa.column("quantity", sa.Integer()))
    op.get_bind().execute(plan.update().values(
        quantity=sa.select(order.c.quantity).where(order.c.id == plan.c.order_id).scalar_subquery(),
    ))
    op.alter_column("esop_production_plan", "quantity", existing_type=sa.Integer(), nullable=False)
    op.create_table(
        "esop_production_order_supplement",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid()),
        sa.Column("review_note", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_esop_order_supplement_tenant_order", "esop_production_order_supplement", ["tenant_id", "order_id"])


def downgrade() -> None:
    plan = sa.table("esop_production_plan", sa.column("order_id", sa.Uuid()), sa.column("quantity", sa.Integer()))
    order = sa.table("esop_production_order", sa.column("id", sa.Uuid()), sa.column("quantity", sa.Integer()))
    split = op.get_bind().execute(sa.select(plan.c.order_id).join(
        order, order.c.id == plan.c.order_id,
    ).where(plan.c.quantity != order.c.quantity).limit(1)).first()
    if split:
        raise RuntimeError("Cannot downgrade after split production plans have been created")
    supplements = sa.table("esop_production_order_supplement", sa.column("id", sa.Uuid()))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(supplements)):
        raise RuntimeError("Cannot downgrade while production order supplements exist")
    op.drop_index("ix_esop_order_supplement_tenant_order", table_name="esop_production_order_supplement")
    op.drop_table("esop_production_order_supplement")
    op.drop_column("esop_production_plan", "quantity")
