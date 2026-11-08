"""Record creation time for legacy setup tables; historical values stay NULL."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0022"
down_revision = "mysql_esop_0021"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("esop_workshop", "esop_production_line", "esop_channel", "esop_hardware_model"):
        op.add_column(table, sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=True))


def downgrade():
    for table in ("esop_hardware_model", "esop_channel", "esop_production_line", "esop_workshop"):
        op.drop_column(table, "created_at")
