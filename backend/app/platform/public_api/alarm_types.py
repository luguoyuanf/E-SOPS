"""Stable projections for ESOP alarm categories stored in Platform dictionaries."""

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AlarmDictionaryEntry:
    code: str
    name: str
    sort: int
    active: bool


class AlarmTypeDirectory(Protocol):
    def list_global(self) -> list[AlarmDictionaryEntry]: ...

    def list_tenant(self, tenant_id: uuid.UUID) -> list[AlarmDictionaryEntry]: ...

    def create_global(self, name: str) -> AlarmDictionaryEntry: ...

    def create_tenant(self, tenant_id: uuid.UUID, name: str) -> AlarmDictionaryEntry: ...

    def rename_global(self, code: str, name: str) -> AlarmDictionaryEntry: ...

    def rename_tenant(self, tenant_id: uuid.UUID, code: str, name: str) -> AlarmDictionaryEntry: ...
