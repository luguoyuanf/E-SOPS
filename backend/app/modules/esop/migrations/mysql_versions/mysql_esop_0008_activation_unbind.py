"""Preserve activation and revocation history."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0008"
down_revision = "mysql_esop_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("esop_activation_unbind_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("terminal_id", sa.Uuid(), nullable=False),
        sa.Column("device_code", sa.String(120), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
    )
    op.create_index("ix_esop_activation_unbind_log_key_id", "esop_activation_unbind_log", ["key_id"])

    op.execute("""CREATE TRIGGER esop_activation_tenant_immutable BEFORE UPDATE ON esop_activation_key
        FOR EACH ROW BEGIN
        IF OLD.tenant_id IS NOT NULL AND NOT (OLD.tenant_id <=> NEW.tenant_id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Activation key tenant ownership is permanent';
        END IF;
        END""")


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS esop_activation_tenant_immutable")
    op.drop_table("esop_activation_unbind_log")
