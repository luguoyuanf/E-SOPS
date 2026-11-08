"""Persist editable ticker publication records; preserve existing terminal slots."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0023"
down_revision = "mysql_esop_0022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("esop_broadcast_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.String(8), nullable=False),
        sa.Column("content", sa.String(500), nullable=False),
        sa.Column("font_size", sa.Integer(), nullable=False),
        sa.Column("background_color", sa.String(7), nullable=False),
        sa.Column("font_color", sa.String(7), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False), mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci", mysql_engine="InnoDB")
    op.create_index("ix_esop_broadcast_record_tenant_id", "esop_broadcast_record", ["tenant_id"])
    fields = ["id", "tenant_id", "position", "content", "font_size", "background_color", "font_color", "is_active", "updated_at"]
    source = sa.table("esop_broadcast", *(sa.column(name) for name in fields))
    target = sa.table("esop_broadcast_record", *(sa.column(name) for name in [*fields, "created_at"]))
    op.get_bind().execute(target.insert().from_select([*fields, "created_at"], sa.select(*(source.c[name] for name in fields), source.c.updated_at)))


def downgrade():
    op.drop_table("esop_broadcast_record")
