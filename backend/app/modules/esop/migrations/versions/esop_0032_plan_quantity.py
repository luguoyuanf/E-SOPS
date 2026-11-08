"""Give each production plan its own order allocation."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0032_plan_quantity"
down_revision = "esop_0031_terminal_display"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("production_plan", sa.Column("quantity", sa.Integer(), nullable=True), schema="esop")
    plan = sa.table("production_plan", sa.column("order_id", sa.Uuid()), sa.column("quantity", sa.Integer()), schema="esop")
    order = sa.table("production_order", sa.column("id", sa.Uuid()), sa.column("quantity", sa.Integer()), schema="esop")
    op.get_bind().execute(plan.update().values(
        quantity=sa.select(order.c.quantity).where(order.c.id == plan.c.order_id).scalar_subquery(),
    ))
    op.alter_column("production_plan", "quantity", existing_type=sa.Integer(), nullable=False, schema="esop")
    op.create_table(
        "production_order_supplement",
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
        schema="esop",
    )
    op.create_index("ix_esop_order_supplement_tenant_order", "production_order_supplement", ["tenant_id", "order_id"], schema="esop")
    op.execute("ALTER TABLE esop.production_order_supplement ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE esop.production_order_supplement FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY esop_order_supplement_tenant ON esop.production_order_supplement "
               "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN GRANT SELECT, INSERT, UPDATE ON esop.production_order_supplement TO app_runtime; END IF; END $$")


def downgrade() -> None:
    plan = sa.table("production_plan", sa.column("order_id", sa.Uuid()), sa.column("quantity", sa.Integer()), schema="esop")
    order = sa.table("production_order", sa.column("id", sa.Uuid()), sa.column("quantity", sa.Integer()), schema="esop")
    split = op.get_bind().execute(sa.select(plan.c.order_id).join(
        order, order.c.id == plan.c.order_id,
    ).where(plan.c.quantity != order.c.quantity).limit(1)).first()
    if split:
        raise RuntimeError("Cannot downgrade after split production plans have been created")
    supplements = sa.table("production_order_supplement", sa.column("id", sa.Uuid()), schema="esop")
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(supplements)):
        raise RuntimeError("Cannot downgrade while production order supplements exist")
    op.drop_index("ix_esop_order_supplement_tenant_order", table_name="production_order_supplement", schema="esop")
    op.drop_table("production_order_supplement", schema="esop")
    op.drop_column("production_plan", "quantity", schema="esop")
