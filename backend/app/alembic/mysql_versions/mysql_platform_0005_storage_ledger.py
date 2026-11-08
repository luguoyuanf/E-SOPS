"""Record opening gifts and derive capacity from the complete grant ledger."""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "mysql_platform_0005"
down_revision = "mysql_platform_0004"
branch_labels = None
depends_on = None


def _valid_trigger(name: str, event: str) -> None:
    op.execute(f"""CREATE TRIGGER {name} BEFORE {event} ON esopstoragegrant
        FOR EACH ROW BEGIN
            IF NEW.source NOT IN ('opening_gift','expansion')
                OR (NEW.source = 'opening_gift' AND (NEW.capacity_bytes < 0 OR NEW.expires_at IS NOT NULL))
                OR (NEW.source = 'expansion' AND (NEW.capacity_bytes <= 0 OR NEW.expires_at IS NULL OR NEW.expires_at <= NEW.starts_at)) THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Invalid ESOP storage grant';
            END IF;
        END""")


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS esopstoragegrant_valid_bi")
    op.add_column("esopstoragegrant", sa.Column("source", sa.String(32), nullable=False, server_default="expansion"))
    op.alter_column("esopstoragegrant", "expires_at", existing_type=mysql.DATETIME(fsp=6), nullable=True)
    _valid_trigger("esopstoragegrant_valid_bi", "INSERT")
    _valid_trigger("esopstoragegrant_valid_bu", "UPDATE")
    account = sa.table("esoptenantstorage", sa.column("tenant_id", sa.Uuid()), sa.column("base_bytes", sa.BigInteger()))
    grant = sa.table("esopstoragegrant", sa.column("id", sa.Uuid()), sa.column("tenant_id", sa.Uuid()),
        sa.column("capacity_bytes", sa.BigInteger()), sa.column("source", sa.String()),
        sa.column("starts_at", sa.DateTime()), sa.column("expires_at", sa.DateTime()),
        sa.column("created_at", sa.DateTime()), sa.column("note", sa.String()))
    connection = op.get_bind()
    now = datetime.now(UTC).replace(tzinfo=None)
    for tenant_id, capacity in connection.execute(sa.select(account.c.tenant_id, account.c.base_bytes)):
        connection.execute(grant.insert().values(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"esop-storage-opening:{tenant_id}"), tenant_id=tenant_id,
            capacity_bytes=capacity, source="opening_gift", starts_at=now,
            expires_at=None, created_at=now, note="开户赠送（历史基础容量补记）",
        ))


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS esopstoragegrant_valid_bi")
    op.execute("DROP TRIGGER IF EXISTS esopstoragegrant_valid_bu")
    grant = sa.table("esopstoragegrant", sa.column("source", sa.String()))
    op.get_bind().execute(grant.delete().where(grant.c.source == "opening_gift"))
    op.alter_column("esopstoragegrant", "expires_at", existing_type=mysql.DATETIME(fsp=6), nullable=False)
    op.drop_column("esopstoragegrant", "source")
    op.execute("""CREATE TRIGGER esopstoragegrant_valid_bi BEFORE INSERT ON esopstoragegrant
        FOR EACH ROW BEGIN
            IF NEW.capacity_bytes <= 0 OR NEW.expires_at <= NEW.starts_at THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Invalid ESOP storage grant';
            END IF;
        END""")
