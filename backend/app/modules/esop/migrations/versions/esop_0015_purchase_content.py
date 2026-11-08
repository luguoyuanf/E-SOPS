"""Shared purchase page content with existing menu authorization preserved."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "esop_0015_purchase_content"
down_revision = "esop_0014_product_sop"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("purchase_content",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), schema="esop",
    )
    # Bind a permission to the existing page; its ID, role links and ordering stay intact.
    menu = sa.table("menu", sa.column("route_name", sa.String()), sa.column("permission_code", sa.String()))
    op.execute(sa.update(menu).where(menu.c.route_name == "EsopPurchase", menu.c.permission_code.is_(None)).values(permission_code="esop:purchase:list"))


def downgrade():
    menu = sa.table("menu", sa.column("route_name", sa.String()), sa.column("permission_code", sa.String()))
    op.execute(sa.update(menu).where(menu.c.route_name == "EsopPurchase", menu.c.permission_code == "esop:purchase:list").values(permission_code=None))
    op.drop_table("purchase_content", schema="esop")
