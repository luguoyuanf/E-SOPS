"""Normalize published release assignments for set-based list queries."""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "esop_0038_release_assignments"
down_revision = "esop_0037_sip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_release_assignment",
        sa.Column("release_id", sa.Uuid(), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("operation_name", sa.String(100), nullable=False),
        schema="esop",
    )
    for column in ("tenant_id", "station_id", "operation_id"):
        op.create_index(f"ix_esop_work_release_assignment_{column}",
                        "work_release_assignment", [column], schema="esop")
    releases = sa.table("work_release", sa.column("id", sa.Uuid()),
                        sa.column("tenant_id", sa.Uuid()), sa.column("assignments", JSONB()), schema="esop")
    assignments = sa.table("work_release_assignment",
                           sa.column("release_id", sa.Uuid()), sa.column("ordinal", sa.Integer()),
                           sa.column("tenant_id", sa.Uuid()), sa.column("station_id", sa.Uuid()),
                           sa.column("operation_id", sa.Uuid()), sa.column("operation_name", sa.String(100)),
                           schema="esop")
    connection = op.get_bind()
    batch = []
    for release_id, tenant_id, snapshot in connection.execute(sa.select(
        releases.c.id, releases.c.tenant_id, releases.c.assignments,
    )):
        for ordinal, item in enumerate(snapshot or []):
            batch.append({
                "release_id": release_id, "ordinal": ordinal, "tenant_id": tenant_id,
                "station_id": uuid.UUID(str(item["station_id"])),
                "operation_id": uuid.UUID(str(item["operation_id"])),
                "operation_name": str(item.get("operation_name") or "")[:100],
            })
        if len(batch) >= 500:
            connection.execute(assignments.insert(), batch)
            batch.clear()
    if batch:
        connection.execute(assignments.insert(), batch)
    op.execute("ALTER TABLE esop.work_release_assignment ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE esop.work_release_assignment FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY esop_work_release_assignment_tenant ON esop.work_release_assignment "
               "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN "
               "GRANT SELECT, INSERT ON esop.work_release_assignment TO app_runtime; END IF; END $$")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS esop_work_release_assignment_tenant ON esop.work_release_assignment")
    op.drop_table("work_release_assignment", schema="esop")
