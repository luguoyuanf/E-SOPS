"""Add the platform-managed common unit catalog and protected tenant copies."""

from app.modules.erp.migrations.platform_units_20261025 import downgrade as drop_units
from app.modules.erp.migrations.platform_units_20261025 import upgrade as add_units

revision = "erp_platform_units"
down_revision = "erp_trade_doc_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_units(is_mysql=False)


def downgrade() -> None:
    drop_units(is_mysql=False)
