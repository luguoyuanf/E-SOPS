"""Record inspected quantities against reported production."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0037"
down_revision = "mysql_esop_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "esop_sip_inspection",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("terminal_id", sa.Uuid(), nullable=False),
        sa.Column("staff_user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("report_allocations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "terminal_id", "request_id", name="uq_esop_sip_terminal_request"),
        mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci", mysql_engine="InnoDB",
    )
    for column in ("tenant_id", "release_id", "operation_id", "station_id", "terminal_id"):
        op.create_index(f"ix_esop_sip_inspection_{column}", "esop_sip_inspection", [column])


def downgrade() -> None:
    op.drop_table("esop_sip_inspection")
