"""Record creation time for legacy setup tables; historical values stay NULL."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0022_created_at"
down_revision = "esop_0021_report_revisions"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("workshop", "production_line", "channel", "hardware_model"):
        op.add_column(table, sa.Column("created_at", sa.DateTime(timezone=True), nullable=True), schema="esop")


def downgrade():
    for table in ("hardware_model", "channel", "production_line", "workshop"):
        op.drop_column(table, "created_at", schema="esop")
