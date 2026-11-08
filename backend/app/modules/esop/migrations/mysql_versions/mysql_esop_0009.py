"""Installation instructions for channel recovery packages."""
import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0009"
down_revision = "mysql_esop_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("esop_ota_package", sa.Column("release_notes", sa.String(4000), nullable=False, server_default=""))
    op.alter_column("esop_ota_package", "release_notes", existing_type=sa.String(4000), server_default=None)


def downgrade():
    op.drop_column("esop_ota_package", "release_notes")
