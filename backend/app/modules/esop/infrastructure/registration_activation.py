"""Issue the registration gift key within the caller's transaction."""

import uuid

from sqlmodel import Session, select

from app.modules.esop.infrastructure.device_auth import issue_key
from app.modules.esop.infrastructure.models import (
    Channel,
    ChannelCustomerTenant,
    HardwareModel,
)

DIRECT_CHANNEL_ID = uuid.UUID("7d78561a-ae5e-4ea8-a283-b9b01af49101")
DIRECT_A133_ID = uuid.UUID("7d78561a-ae5e-4ea8-a283-b9b01af49102")


def bind_official_tenant(session: Session, tenant_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Bind explicit direct provisioning only; preserve existing channel ownership."""
    if session.get(Channel, DIRECT_CHANNEL_ID) is None:
        session.add(Channel(id=DIRECT_CHANNEL_ID, code="DIRECT", name="官方渠道"))
    existing = session.exec(select(ChannelCustomerTenant).where(
        ChannelCustomerTenant.tenant_id == tenant_id,
    )).first()
    if existing is None:
        session.add(ChannelCustomerTenant(
            channel_id=DIRECT_CHANNEL_ID, tenant_id=tenant_id, created_by=actor_id,
        ))
    session.flush()


def issue_free_key(session: Session, tenant_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    """Reserve one DIRECT A133 key; the registration transaction commits it."""
    if session.get(Channel, DIRECT_CHANNEL_ID) is None:
        session.add(Channel(id=DIRECT_CHANNEL_ID, code="DIRECT", name="官方渠道"))
    if session.get(HardwareModel, DIRECT_A133_ID) is None:
        session.add(HardwareModel(
            id=DIRECT_A133_ID, channel_id=DIRECT_CHANNEL_ID,
            code="A133", name="A133", abi="armeabi-v7a",
        ))
    session.flush()
    row, plaintext = issue_key(
        session, tenant_id, grant_type="free",
        channel_id=DIRECT_CHANNEL_ID, hardware_model_id=DIRECT_A133_ID,
    )
    return row.id, plaintext
