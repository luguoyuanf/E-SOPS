"""Default direct tenants to the official channel."""
from alembic import op

from app.modules.esop.migrations.official_channel_20261026 import (
    downgrade as revert_defaults,
)
from app.modules.esop.migrations.official_channel_20261026 import (
    upgrade as apply_defaults,
)

revision = "mysql_esop_0010"
down_revision = "mysql_esop_0009"
branch_labels = None
depends_on = None


def upgrade():
    apply_defaults(op.get_bind())


def downgrade():
    revert_defaults(op.get_bind())
