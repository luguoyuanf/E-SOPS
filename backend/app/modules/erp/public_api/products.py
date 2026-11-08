"""Read-only product contract for dependent business modules."""

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProductSummary:
    id: uuid.UUID
    code: str
    name: str
    category_id: uuid.UUID | None = None
    category_name: str = ""
    model: str | None = None


@dataclass(frozen=True)
class ProductCategorySummary:
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None


class ProductDirectory(Protocol):
    def get(self, product_id: uuid.UUID) -> ProductSummary | None: ...

    def exists(self, product_id: uuid.UUID) -> bool: ...

    def list(self, keyword: str | None = None) -> list[ProductSummary]: ...

    def tree(self) -> tuple[list[ProductCategorySummary], list[ProductSummary]]: ...
