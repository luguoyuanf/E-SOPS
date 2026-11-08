"""Encrypt new activation keys for authorized repeated retrieval on MySQL 5.7."""

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0007"
down_revision = "mysql_esop_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("esop_activation_key", sa.Column("key_ciphertext", sa.String(300)))


def downgrade():
    op.drop_column("esop_activation_key", "key_ciphertext")
