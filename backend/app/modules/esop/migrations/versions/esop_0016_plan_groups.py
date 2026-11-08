"""Independent plan queues and optional schedule windows."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0016_plan_groups"
down_revision = "esop_0015_purchase_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("group_position", sa.Integer(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("production_plan", column, schema="esop")
    op.create_index("ix_production_plan_group_id", "production_plan", ["group_id"], schema="esop")
    op.create_table(
        "production_plan_group",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="esop",
    )
    op.create_index("ix_production_plan_group_tenant_id", "production_plan_group", ["tenant_id"], schema="esop")


def downgrade() -> None:
    op.drop_table("production_plan_group", schema="esop")
    op.drop_index("ix_production_plan_group_id", table_name="production_plan", schema="esop")
    for column in ("end_at", "start_at", "group_position", "group_id", "created_by"):
        op.drop_column("production_plan", column, schema="esop")
