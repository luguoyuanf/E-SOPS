"""Independent plan queues and optional schedule windows."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0016"
down_revision = "mysql_esop_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("esop_production_plan", sa.Column("created_by", sa.Uuid(), nullable=True))
    op.add_column("esop_production_plan", sa.Column("group_id", sa.Uuid(), nullable=True))
    op.add_column("esop_production_plan", sa.Column("group_position", sa.Integer(), nullable=True))
    op.add_column("esop_production_plan", sa.Column("start_at", mysql.DATETIME(fsp=6), nullable=True))
    op.add_column("esop_production_plan", sa.Column("end_at", mysql.DATETIME(fsp=6), nullable=True))
    op.create_index("ix_esop_production_plan_group_id", "esop_production_plan", ["group_id"])
    op.create_table(
        "esop_production_plan_group",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("start_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci", mysql_engine="InnoDB",
    )
    op.create_index("ix_esop_production_plan_group_tenant_id", "esop_production_plan_group", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("esop_production_plan_group")
    op.drop_index("ix_esop_production_plan_group_id", table_name="esop_production_plan")
    for column in ("end_at", "start_at", "group_position", "group_id", "created_by"):
        op.drop_column("esop_production_plan", column)
