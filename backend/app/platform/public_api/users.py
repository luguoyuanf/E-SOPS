import uuid
from collections.abc import Collection
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class UserSummary(BaseModel):
    """A read-only user projection that does not expose the platform ORM model."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    full_name: str | None = None
    email: str | None = None
    is_active: bool


class UserOption(BaseModel):
    id: uuid.UUID
    label: str


class UserDirectory(Protocol):
    def can_correct_production_reports(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> bool: ...

    def is_tenant_administrator(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> bool: ...

    def list_tenant_options(self, tenant_id: uuid.UUID) -> list[UserOption]: ...

    def get_users(self, user_ids: Collection[uuid.UUID]) -> list[UserSummary]: ...

    def validate_active_users(self, user_ids: Collection[uuid.UUID]) -> None: ...
