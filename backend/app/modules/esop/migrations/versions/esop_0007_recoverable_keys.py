"""Encrypt new activation keys for authorized repeated retrieval."""

import sqlalchemy as sa
from alembic import op

revision = "esop_0007_recoverable_keys"
down_revision = "esop_0006_broadcast"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("activation_key", sa.Column("key_ciphertext", sa.String(300)), schema="esop")


def downgrade():
    op.drop_column("activation_key", "key_ciphertext", schema="esop")
