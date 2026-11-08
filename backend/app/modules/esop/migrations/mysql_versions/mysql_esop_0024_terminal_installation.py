"""Global installation serials, independent of tenant activation."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0024"
down_revision = "mysql_esop_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("esop_terminal_installation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("installation_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("device_code", sa.String(10), nullable=False, unique=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False), mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci", mysql_engine="InnoDB")


def downgrade():
    op.drop_table("esop_terminal_installation")
