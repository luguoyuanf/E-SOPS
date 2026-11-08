"""Global installation serials, independent of tenant activation."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0024_terminal_installation"
down_revision = "esop_0023_broadcast_records"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("terminal_installation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("installation_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("device_code", sa.String(10), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), schema="esop")


def downgrade():
    op.drop_table("terminal_installation", schema="esop")
