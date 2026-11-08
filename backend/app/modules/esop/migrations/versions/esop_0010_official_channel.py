"""Default direct tenants to the official channel."""
from alembic import op

from app.modules.esop.migrations.official_channel_20261026 import (
    downgrade as revert_defaults,
)
from app.modules.esop.migrations.official_channel_20261026 import (
    upgrade as apply_defaults,
)

revision = "esop_0010_official_channel"
down_revision = "esop_0009_ota_notes"
branch_labels = None
depends_on = None


def upgrade():
    apply_defaults(op.get_bind(), schema="esop")


def downgrade():
    revert_defaults(op.get_bind(), schema="esop")
