"""Product-wide immutable SOP reviews and converted operation media."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "esop_0014_product_sop"
down_revision = "esop_0013_sop_direct_publish"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operation", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0"), schema="esop")
    for table in ("production_plan", "work_release"):
        op.add_column(table, sa.Column("product_sop_version_id", sa.Uuid(), nullable=True), schema="esop")
        op.create_index(f"ix_esop_{table}_product_sop_version_id", table, ["product_sop_version_id"], schema="esop")
    op.create_table(
        "product_sop_lock",
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Uuid(), primary_key=True),
        schema="esop",
    )
    op.create_table(
        "product_sop_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("operations", postgresql.JSONB(), nullable=False),
        sa.Column("base_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=True),
        sa.UniqueConstraint("tenant_id", "product_id", "version", name="uq_esop_product_sop_version"),
        schema="esop",
    )
    op.create_table(
        "operation_file_rendition",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("original_file_id", sa.Uuid(), nullable=False),
        sa.Column("display_file_id", sa.Uuid(), nullable=False),
        sa.Column("page_file_ids", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "original_file_id", name="uq_esop_operation_file_rendition"),
        schema="esop",
    )
    for table, columns in (
        ("product_sop_version", ("tenant_id", "product_id")),
        ("operation_file_rendition", ("tenant_id", "original_file_id")),
    ):
        for column in columns:
            op.create_index(f"ix_esop_{table}_{column}", table, [column], schema="esop")
    for table in ("product_sop_lock", "product_sop_version", "operation_file_rendition"):
        op.execute(f"ALTER TABLE esop.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE esop.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY esop_{table}_tenant ON esop.{table} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    for name in ("product_sop_version", "operation_file_rendition"):
        table = sa.table(name, sa.column("id"), schema="esop")
        if bind.scalar(sa.select(sa.func.count()).select_from(table)):
            raise RuntimeError("存在产品 SOP 版本或转换记录，不能直接回退并丢失审核历史")
    operations = sa.table("operation", sa.column("is_deleted", sa.Boolean()), schema="esop")
    if bind.scalar(sa.select(sa.func.count()).select_from(operations).where(operations.c.is_deleted.is_(True))):
        raise RuntimeError("存在草稿删除记录，回退前必须先保留并处理数据")
    for table in ("operation_file_rendition", "product_sop_version", "product_sop_lock"):
        op.drop_table(table, schema="esop")
    for table in ("production_plan", "work_release"):
        op.drop_index(f"ix_esop_{table}_product_sop_version_id", table_name=table, schema="esop")
        op.drop_column(table, "product_sop_version_id", schema="esop")
    op.drop_column("operation", "is_deleted", schema="esop")
