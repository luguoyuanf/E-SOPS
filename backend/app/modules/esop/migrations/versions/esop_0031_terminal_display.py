"""Give existing terminals short visible numbers and editable names."""

import hashlib
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "esop_0031_terminal_display"
down_revision = "esop_0030_alarm_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("terminal", sa.Column("serial_number", sa.String(10), nullable=True), schema="esop")
    op.add_column("terminal", sa.Column("device_name", sa.String(100), nullable=True), schema="esop")
    terminal = sa.table("terminal", sa.column("id", sa.Uuid()), sa.column("device_code", sa.String(120)), sa.column("serial_number", sa.String(10)), schema="esop")
    installation = sa.table("terminal_installation", sa.column("id", sa.Uuid()), sa.column("installation_hash", sa.String(64)), sa.column("device_code", sa.String(10)), sa.column("created_at", sa.DateTime(timezone=True)), schema="esop")
    credential = sa.table("device_credential", sa.column("device_code", sa.String(120)), schema="esop")
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
    op.alter_column("terminal", "serial_number", existing_type=sa.String(10), nullable=False, schema="esop")
    op.create_unique_constraint("uq_esop_terminal_serial_number", "terminal", ["serial_number"], schema="esop")


def downgrade() -> None:
    connection = op.get_bind()
    terminal = sa.table("terminal", sa.column("id", sa.Uuid()), sa.column("device_code", sa.String(120)), sa.column("serial_number", sa.String(10)), schema="esop")
    installation = sa.table("terminal_installation", sa.column("installation_hash", sa.String(64)), schema="esop")
    for terminal_id, old_code, serial in connection.execute(sa.select(terminal.c.id, terminal.c.device_code, terminal.c.serial_number)):
        if serial != old_code:
            connection.execute(installation.delete().where(installation.c.installation_hash == hashlib.sha256(f"reserved:{terminal_id}".encode()).hexdigest()))
    op.drop_constraint("uq_esop_terminal_serial_number", "terminal", type_="unique", schema="esop")
    op.drop_column("terminal", "device_name", schema="esop")
    op.drop_column("terminal", "serial_number", schema="esop")
