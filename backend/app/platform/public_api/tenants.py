"""Narrow tenant enumeration for authorized module administration."""

import uuid
from typing import Protocol


class TenantDirectory(Protocol):
    def list_tenant_ids(self) -> tuple[uuid.UUID, ...]: ...
