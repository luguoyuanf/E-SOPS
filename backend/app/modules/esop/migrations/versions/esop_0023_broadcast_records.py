"""Persist editable ticker publication records; preserve existing terminal slots."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0023_broadcast_records"
down_revision = "esop_0022_created_at"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("broadcast_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.String(8), nullable=False),
        sa.Column("content", sa.String(500), nullable=False),
        sa.Column("font_size", sa.Integer(), nullable=False),
        sa.Column("background_color", sa.String(7), nullable=False),
        sa.Column("font_color", sa.String(7), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), schema="esop")
    op.create_index("ix_esop_broadcast_record_tenant_id", "broadcast_record", ["tenant_id"], schema="esop")
    fields = ["id", "tenant_id", "position", "content", "font_size", "background_color", "font_color", "is_active", "updated_at"]
    source = sa.table("broadcast", *(sa.column(name) for name in fields), schema="esop")
    target = sa.table("broadcast_record", *(sa.column(name) for name in [*fields, "created_at"]), schema="esop")
    op.get_bind().execute(target.insert().from_select([*fields, "created_at"], sa.select(*(source.c[name] for name in fields), source.c.updated_at)))
    op.execute("ALTER TABLE esop.broadcast_record ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE esop.broadcast_record FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY esop_broadcast_record_tenant ON esop.broadcast_record "
               "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def downgrade():
    op.drop_table("broadcast_record", schema="esop")
