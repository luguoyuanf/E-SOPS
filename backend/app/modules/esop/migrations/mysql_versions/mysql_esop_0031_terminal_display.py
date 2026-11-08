"""Give existing terminals short visible numbers and editable names."""

import hashlib
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0031"
down_revision = "mysql_esop_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "esop_terminal"
    op.add_column(table, sa.Column("serial_number", sa.String(10), nullable=True))
    op.add_column(table, sa.Column("device_name", sa.String(100), nullable=True))
    terminal = sa.table(table, sa.column("id", sa.Uuid()), sa.column("device_code", sa.String(120)), sa.column("serial_number", sa.String(10)))
    installation = sa.table("esop_terminal_installation", sa.column("id", sa.Uuid()), sa.column("installation_hash", sa.String(64)), sa.column("device_code", sa.String(10)), sa.column("created_at", sa.DateTime(timezone=True)))
    credential = sa.table("esop_device_credential", sa.column("device_code", sa.String(120)))
    connection = op.get_bind()
    rows = connection.execute(sa.select(terminal.c.id, terminal.c.device_code)).all()
    reserved = {code for (code,) in connection.execute(sa.select(installation.c.device_code))}
    reserved.update(code for (code,) in connection.execute(sa.select(credential.c.device_code)))
    reserved.update(code for _, code in rows)
    assigned: set[str] = set()
    for terminal_id, old_code in rows:
        if len(old_code) == 10 and old_code.startswith("SN") and old_code[2:].isdigit() and old_code not in assigned:
            serial = old_code
        else:
            number = int.from_bytes(hashlib.sha256(str(terminal_id).encode()).digest()[:8], "big") % 100_000_000
            for _ in range(100_000_000):
                serial = f"SN{number:08d}"
                if serial not in reserved and serial not in assigned:
                    break
                number = (number + 1) % 100_000_000
            else:
                raise RuntimeError("No terminal numbers available")
        connection.execute(terminal.update().where(terminal.c.id == terminal_id).values(serial_number=serial))
        if serial != old_code:
            connection.execute(installation.insert().values(
                id=uuid.uuid4(),
                installation_hash=hashlib.sha256(f"reserved:{terminal_id}".encode()).hexdigest(),
                device_code=serial,
                created_at=datetime.now(UTC),
            ))
        assigned.add(serial)
    op.alter_column(table, "serial_number", existing_type=sa.String(10), nullable=False)
    op.create_unique_constraint("uq_esop_terminal_serial_number", table, ["serial_number"])


def downgrade() -> None:
    connection = op.get_bind()
    terminal = sa.table("esop_terminal", sa.column("id", sa.Uuid()), sa.column("device_code", sa.String(120)), sa.column("serial_number", sa.String(10)))
    installation = sa.table("esop_terminal_installation", sa.column("installation_hash", sa.String(64)))
    for terminal_id, old_code, serial in connection.execute(sa.select(terminal.c.id, terminal.c.device_code, terminal.c.serial_number)):
        if serial != old_code:
            connection.execute(installation.delete().where(installation.c.installation_hash == hashlib.sha256(f"reserved:{terminal_id}".encode()).hexdigest()))
    op.drop_constraint("uq_esop_terminal_serial_number", "esop_terminal", type_="unique")
    op.drop_column("esop_terminal", "device_name")
    op.drop_column("esop_terminal", "serial_number")
