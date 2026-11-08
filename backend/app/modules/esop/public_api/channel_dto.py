"""Manual channel inventory and customer tenant contracts."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.esop.public_api.dto import EntityCodeInput


class ChannelAdminInput(BaseModel):
    user_id: uuid.UUID


class ChannelAdminPublic(ChannelAdminInput):
    channel_id: uuid.UUID


class BatchIssueInput(BaseModel):
    quantity: int = Field(ge=100, le=1000)
    hardware_model_id: uuid.UUID | None = None


class IssuedKey(BaseModel):
    id: uuid.UUID
    key: str


class IssuedBatch(BaseModel):
    batch_id: uuid.UUID
    keys: list[IssuedKey]


class ChannelWorkspace(BaseModel):
    channel_id: uuid.UUID
    channel_code: str
    channel_name: str


class ChannelInventoryItem(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID | None
    key: str | None
    recoverable: bool
    tenant_id: uuid.UUID | None
    hardware_model_id: uuid.UUID | None
    created_at: datetime
    used_at: datetime | None
    used_terminal_id: uuid.UUID | None
    is_assigned: bool
    is_used: bool
    status: str


class ListChannelInventory(BaseModel):
    items: list[ChannelInventoryItem]
    total: int


class BatchSummary(BaseModel):
    batch_id: uuid.UUID
    quantity: int
    assigned_count: int
    activated_count: int
    created_at: datetime


class ListBatchSummaries(BaseModel):
    items: list[BatchSummary]
    total: int


class KeyExportInput(BaseModel):
    batch_id: uuid.UUID | None = None
    key_ids: list[uuid.UUID] | None = Field(default=None, max_length=1000)


class CustomerInput(EntityCodeInput):
    code: str | None = Field(default=None, min_length=3, max_length=32)
    name: str = Field(min_length=2, max_length=100)


class CustomerPublic(BaseModel):
    tenant_id: uuid.UUID
    tenant_code: str
    tenant_name: str
    created_at: datetime


class ListChannelCustomers(BaseModel):
    items: list[CustomerPublic]
    total: int


class KeyAssignInput(BaseModel):
    tenant_id: uuid.UUID
    key_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


class KeyAssignResult(BaseModel):
    assigned_count: int
