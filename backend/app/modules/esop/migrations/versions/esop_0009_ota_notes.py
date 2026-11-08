"""Installation instructions for channel recovery packages."""
import sqlalchemy as sa
from alembic import op

revision = "esop_0009_ota_notes"
down_revision = "esop_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ota_package", sa.Column("release_notes", sa.String(4000), nullable=False, server_default=""), schema="esop")
    op.alter_column("ota_package", "release_notes", existing_type=sa.String(4000), server_default=None, schema="esop")


def downgrade():
    op.drop_column("ota_package", "release_notes", schema="esop")
