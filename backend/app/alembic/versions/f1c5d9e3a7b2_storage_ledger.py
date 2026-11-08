"""Record opening gifts and derive capacity from the complete grant ledger."""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "f1c5d9e3a7b2"
down_revision = "f0b4c8d2e6a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_esopstoragegrant_valid", "esopstoragegrant", type_="check")
    op.add_column("esopstoragegrant", sa.Column("source", sa.String(32), nullable=False, server_default="expansion"))
    op.alter_column("esopstoragegrant", "expires_at", existing_type=sa.DateTime(timezone=True), nullable=True)
    op.create_check_constraint("ck_esopstoragegrant_valid", "esopstoragegrant",
        "(source = 'opening_gift' AND capacity_bytes >= 0 AND expires_at IS NULL) OR "
        "(source = 'expansion' AND capacity_bytes > 0 AND expires_at IS NOT NULL AND expires_at > starts_at)")
    account = sa.table("esoptenantstorage", sa.column("tenant_id", sa.Uuid()), sa.column("base_bytes", sa.BigInteger()))
    grant = sa.table("esopstoragegrant", sa.column("id", sa.Uuid()), sa.column("tenant_id", sa.Uuid()),
        sa.column("capacity_bytes", sa.BigInteger()), sa.column("source", sa.String()),
        sa.column("starts_at", sa.DateTime()), sa.column("expires_at", sa.DateTime()),
        sa.column("created_at", sa.DateTime()), sa.column("note", sa.String()))
    connection = op.get_bind()
    now = datetime.now(UTC)
    for tenant_id, capacity in connection.execute(sa.select(account.c.tenant_id, account.c.base_bytes)):
        connection.execute(grant.insert().values(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"esop-storage-opening:{tenant_id}"), tenant_id=tenant_id,
            capacity_bytes=capacity, source="opening_gift", starts_at=now,
            expires_at=None, created_at=now, note="开户赠送（历史基础容量补记）",
        ))


def downgrade() -> None:
    op.drop_constraint("ck_esopstoragegrant_valid", "esopstoragegrant", type_="check")
    grant = sa.table("esopstoragegrant", sa.column("source", sa.String()))
    op.get_bind().execute(grant.delete().where(grant.c.source == "opening_gift"))
    op.alter_column("esopstoragegrant", "expires_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    op.drop_column("esopstoragegrant", "source")
    op.create_check_constraint("ck_esopstoragegrant_valid", "esopstoragegrant", "capacity_bytes > 0 AND expires_at > starts_at")
