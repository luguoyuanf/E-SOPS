"""Normalize published release assignments for set-based list queries."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "mysql_esop_0038"
down_revision = "mysql_esop_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "esop_work_release_assignment",
        sa.Column("release_id", sa.Uuid(), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("operation_name", sa.String(100), nullable=False),
        mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci", mysql_engine="InnoDB",
    )
    op.create_index("ix_esop_work_release_assignment_tenant_id", "esop_work_release_assignment", ["tenant_id"])
    op.create_index("ix_esop_work_release_assignment_station_id", "esop_work_release_assignment", ["station_id"])
    op.create_index("ix_esop_work_release_assignment_operation_id", "esop_work_release_assignment", ["operation_id"])
    _backfill("esop_work_release", "esop_work_release_assignment")


def _backfill(releases_name: str, assignments_name: str) -> None:
    releases = sa.table(releases_name,
                        sa.column("id", sa.Uuid()), sa.column("tenant_id", sa.Uuid()),
                        sa.column("assignments", sa.JSON()))
    assignments = sa.table(assignments_name,
                           sa.column("release_id", sa.Uuid()), sa.column("ordinal", sa.Integer()),
                           sa.column("tenant_id", sa.Uuid()), sa.column("station_id", sa.Uuid()),
                           sa.column("operation_id", sa.Uuid()), sa.column("operation_name", sa.String(100)))
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


def downgrade() -> None:
    op.drop_table("esop_work_release_assignment")
