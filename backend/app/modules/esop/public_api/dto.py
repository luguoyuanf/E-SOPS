"""HTTP and cross-module value contracts for the first ESOP workflow."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntityCodeInput(BaseModel):
    @field_validator("code", mode="before", check_fields=False)
    @classmethod
    def normalize_optional_code(cls, value: object) -> object:
        return (value.strip() or None) if isinstance(value, str) else value


class OperationAttachment(BaseModel):
    file_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    original_name: str | None = None
    kind: str
    content_type: str | None = None
    size: int = Field(ge=0)
    display_file_id: uuid.UUID | None = None
    display_content_type: str | None = None
    display_pages: list[uuid.UUID] = Field(default_factory=list)
    sheet_index: int | None = Field(default=None, ge=0)


class OperationMediaStatus(BaseModel):
    status: Literal["queued", "running", "ready", "failed"]
    error_message: str | None = None
    attachment: OperationAttachment


class SopImportSheet(BaseModel):
    index: int
    name: str
    selected: bool


class SopImportAnalysis(BaseModel):
    sheets: list[SopImportSheet]


class SopImportRequest(BaseModel):
    file_id: uuid.UUID
    sheet_indexes: list[int] = Field(min_length=1, max_length=100)
    mode: Literal["append", "replace"] = "append"


class OperationProduct(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    category_id: uuid.UUID | None = None


class OperationCategory(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None


class OperationProductTree(BaseModel):
    categories: list[OperationCategory]
    products: list[OperationProduct]


class OperationInput(EntityCodeInput):
    code: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    product_id: uuid.UUID | None = None
    attachments: list[OperationAttachment] = Field(default_factory=list, max_length=100)


class OperationPublic(OperationInput):
    sort_order: int = 0
    code: str
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class OperationMove(BaseModel):
    target_id: uuid.UUID
    position: Literal["before", "after"] = "before"


class RouteInput(EntityCodeInput):
    code: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    operation_ids: list[uuid.UUID] = Field(min_length=1)


class RoutePublic(RouteInput):
    code: str
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class SopPage(BaseModel):
    file_id: uuid.UUID
    sort: int = Field(ge=0)
    caption: str | None = Field(default=None, max_length=200)


class SopCreate(BaseModel):
    product_id: uuid.UUID
    operation_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    pages: list[SopPage] = Field(default_factory=list)


class SopUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    pages: list[SopPage] = Field(default_factory=list)


class SopReject(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class SopPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    family_id: uuid.UUID
    product_id: uuid.UUID
    operation_id: uuid.UUID
    title: str
    version: int
    status: str
    pages: list[SopPage]
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None
    review_note: str | None = None


class ListOperations(BaseModel):
    items: list[OperationPublic]
    total: int


class ListRoutes(BaseModel):
    items: list[RoutePublic]
    total: int


class ListSops(BaseModel):
    items: list[SopPublic]
    total: int


class ProductSopVersionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    version: int
    status: str
    operations: list[dict[str, object]]
    base_version_id: uuid.UUID | None
    created_by: uuid.UUID
    submitted_at: datetime
    reviewed_by: uuid.UUID | None = None
    reviewer_name: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None


class ProductSopOperationState(BaseModel):
    operation: OperationPublic
    status: Literal["approved", "draft", "pending", "pending_delete"]
    has_approved_version: bool
    is_deleted: bool = False


class ProductSopSummary(BaseModel):
    product_id: uuid.UUID
    status: Literal["draft", "pending", "approved"]
    dirty: bool
    operation_count: int


class ProductSopSummaries(BaseModel):
    items: list[ProductSopSummary]
    total: int


class ProductSopWorkspace(BaseModel):
    product_id: uuid.UUID
    product_name: str
    status: str
    dirty: bool
    current_operations: list[OperationPublic]
    operation_states: list[ProductSopOperationState] = Field(default_factory=list)
    approved_version: ProductSopVersionPublic | None = None
    pending_version: ProductSopVersionPublic | None = None


class ProductSopVersions(BaseModel):
    items: list[ProductSopVersionPublic]
    total: int


class ProductSopVersionDetail(BaseModel):
    version: ProductSopVersionPublic
    base_version: ProductSopVersionPublic | None = None
