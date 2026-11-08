"""Composition-root binding for ESOP registration activation keys."""

import uuid

from sqlmodel import Session

from app.modules.esop.infrastructure.registration_activation import (
    bind_official_tenant as _bind_official_tenant,
)
from app.modules.esop.infrastructure.registration_activation import (
    issue_free_key as _issue_free_key,
)


def issue_free_key(session: Session, tenant_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    return _issue_free_key(session, tenant_id)


def bind_official_tenant(session: Session, tenant_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    _bind_official_tenant(session, tenant_id, actor_id)
