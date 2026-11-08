"""Product-wide immutable SOP reviews and converted operation media."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_esop_0014"
down_revision = "mysql_esop_0013"
branch_labels = None
depends_on = None

OPTIONS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    op.add_column("esop_operation", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0"))
    for table in ("esop_production_plan", "esop_work_release"):
        op.add_column(table, sa.Column("product_sop_version_id", sa.Uuid(), nullable=True))
        op.create_index(f"ix_{table}_product_sop_version_id", table, ["product_sop_version_id"])
    op.create_table(
        "esop_product_sop_lock",
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Uuid(), primary_key=True),
        **OPTIONS,
    )
    op.create_table(
        "esop_product_sop_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("operations", mysql.JSON(), nullable=False),
        sa.Column("base_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=True),
        sa.UniqueConstraint("tenant_id", "product_id", "version", name="uq_esop_product_sop_version"),
        **OPTIONS,
    )
    op.create_table(
        "esop_operation_file_rendition",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("original_file_id", sa.Uuid(), nullable=False),
        sa.Column("display_file_id", sa.Uuid(), nullable=False),
        sa.Column("page_file_ids", mysql.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("tenant_id", "original_file_id", name="uq_esop_operation_file_rendition"),
        **OPTIONS,
    )
    for table, columns in (
        ("esop_product_sop_version", ("tenant_id", "product_id")),
        ("esop_operation_file_rendition", ("tenant_id", "original_file_id")),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    bind = op.get_bind()
    for name in ("esop_product_sop_version", "esop_operation_file_rendition"):
        table = sa.table(name, sa.column("id"), schema=None)
        if bind.scalar(sa.select(sa.func.count()).select_from(table)):
            raise RuntimeError("存在产品 SOP 版本或转换记录，不能直接回退并丢失审核历史")
    operations = sa.table("esop_operation", sa.column("is_deleted", sa.Boolean()), schema=None)
    if bind.scalar(sa.select(sa.func.count()).select_from(operations).where(operations.c.is_deleted.is_(True))):
        raise RuntimeError("存在草稿删除记录，回退前必须先保留并处理数据")
    for table in ("esop_operation_file_rendition", "esop_product_sop_version", "esop_product_sop_lock"):
        op.drop_table(table)
    for table in ("esop_production_plan", "esop_work_release"):
        op.drop_index(f"ix_{table}_product_sop_version_id", table_name=table)
        op.drop_column(table, "product_sop_version_id")
    op.drop_column("esop_operation", "is_deleted")
