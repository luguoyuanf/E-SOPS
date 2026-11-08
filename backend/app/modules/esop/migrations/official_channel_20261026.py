"""Versioned data migration for the built-in official channel."""
import uuid

import sqlalchemy as sa

from app.core.clock import get_datetime_utc

CHANNEL_ID = uuid.UUID("7d78561a-ae5e-4ea8-a283-b9b01af49101")
SYSTEM_ACTOR = uuid.UUID(int=0)


def _tables(schema):
    prefix = "" if schema else "esop_"
    channel = sa.table(prefix + "channel", sa.column("id", sa.Uuid()), sa.column("code", sa.String()), sa.column("name", sa.String()), schema=schema)
    mapping = sa.table(prefix + "channel_customer_tenant", sa.column("id", sa.Uuid()), sa.column("channel_id", sa.Uuid()), sa.column("tenant_id", sa.Uuid()), sa.column("created_by", sa.Uuid()), sa.column("created_at", sa.DateTime(timezone=True)), schema=schema)
    tenant = sa.table("tenant", sa.column("id", sa.Uuid()), schema="public" if schema else None)
    return channel, mapping, tenant


def _mapping_id(tenant_id):
    return uuid.uuid5(CHANNEL_ID, "official-default-20261026:" + str(tenant_id))


def upgrade(connection, schema=None):
    channel, mapping, tenant = _tables(schema)
    if connection.scalar(sa.select(channel.c.id).where(channel.c.id == CHANNEL_ID)) is None:
        connection.execute(sa.insert(channel).values(id=CHANNEL_ID, code="DIRECT", name="官方渠道"))
    else:
        connection.execute(sa.update(channel).where(channel.c.id == CHANNEL_ID).values(name="官方渠道"))
    missing = connection.execute(sa.select(tenant.c.id).where(~sa.exists(sa.select(mapping.c.id).where(mapping.c.tenant_id == tenant.c.id)))).scalars().all()
    for tenant_id in missing:
        connection.execute(sa.insert(mapping).values(
            id=_mapping_id(tenant_id), channel_id=CHANNEL_ID, tenant_id=tenant_id,
            created_by=SYSTEM_ACTOR, created_at=get_datetime_utc(),
        ))


def downgrade(connection, schema=None):
    channel, mapping, _ = _tables(schema)
    rows = connection.execute(sa.select(mapping.c.id, mapping.c.tenant_id).where(mapping.c.channel_id == CHANNEL_ID)).all()
    for row_id, tenant_id in rows:
        if row_id == _mapping_id(tenant_id):
            connection.execute(sa.delete(mapping).where(mapping.c.id == row_id))
    connection.execute(sa.update(channel).where(channel.c.id == CHANNEL_ID, channel.c.name == "官方渠道").values(name="直客"))
