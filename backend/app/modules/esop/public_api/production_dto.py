"""Production setup and immutable release contracts."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.esop.public_api.dto import EntityCodeInput


class WorkshopInput(EntityCodeInput):
    code: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=100)


class WorkshopPublic(WorkshopInput):
    code: str
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime | None = None


class StationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    line_id: uuid.UUID
    position: int
    name: str = ""
    row: int
    column: int
    terminal_code: str | None = None
    terminal_active: bool = False


class LineFields(EntityCodeInput):
    workshop_id: uuid.UUID
    code: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    layout: Literal["single", "double"]
    station_count: int = Field(ge=1, le=200)
    numbering_mode: Literal["sequential", "odd_even"] | None = None


class LineInput(LineFields):
    station_names: dict[Annotated[int, Field(ge=1, le=200)], Annotated[str, Field(max_length=100)]] | None = None

    @model_validator(mode="after")
    def validate_station_names(self):
        if self.station_names and any(position > self.station_count for position in self.station_names):
            raise ValueError("工位名称对应的编号超出工位总数")
        return self


class LinePublic(LineFields):
    numbering_mode: Literal["sequential", "odd_even"] = "odd_even"
    code: str
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime | None = None
    stations: list[StationPublic]


class OrderInput(EntityCodeInput):
    code: str | None = Field(default=None, max_length=60)
    product_id: uuid.UUID
    quantity: int = Field(ge=1)
    due_date: date
    product_sop_version_id: uuid.UUID | None = None
    operation_ids: list[uuid.UUID] | None = None


class OrderPublic(OrderInput):
    code: str
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    is_published: bool = False
    production_status: Literal["unplanned", "waiting", "in_progress", "completed"] = "unplanned"


class OrderOperationsInput(BaseModel):
    product_sop_version_id: uuid.UUID
    operation_ids: list[uuid.UUID] = Field(min_length=1)


class OrderExportInput(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    keyword: str | None = None
    product_id: uuid.UUID | None = None
    is_published: bool | None = None
    created_at_from: date | None = None
    created_at_to: date | None = None
    due_date_from: date | None = None
    due_date_to: date | None = None


class Assignment(BaseModel):
    operation_id: uuid.UUID
    station_id: uuid.UUID
    sop_id: uuid.UUID


class PlanInput(EntityCodeInput):
    code: str | None = Field(default=None, max_length=50)
    order_id: uuid.UUID
    quantity: int | None = Field(default=None, ge=1)
    line_id: uuid.UUID
    route_id: uuid.UUID | None = None
    product_sop_version_id: uuid.UUID | None = None
    assignments: list[Assignment] = Field(default_factory=list)
    start_at: datetime | None = None
    end_at: datetime | None = None


class PlanPublic(PlanInput):
    quantity: int
    input_total: int = 0
    good_total: int = 0
    bad_total: int = 0
    completion_rate: float = 0.0
    code: str
    product_sop_version: int | None = None
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: Literal["draft", "published", "paused", "expired", "completed", "cancelled"]
    group_id: uuid.UUID | None = None
    group_position: int | None = None
    created_at: datetime
    updated_at: datetime


class SupplementInput(BaseModel):
    order_id: uuid.UUID
    quantity: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class SupplementReview(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=500)


class SupplementPublic(SupplementInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: Literal["pending", "approved", "rejected"]
    requested_by: uuid.UUID
    reviewed_by: uuid.UUID | None = None
    review_note: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None


class ListSupplements(BaseModel):
    items: list[SupplementPublic]
    total: int


class OrderAllocationPublic(BaseModel):
    order_quantity: int
    allocated_quantity: int
    approved_supplement_quantity: int
    remaining_quantity: int
    operations: list[dict] = Field(default_factory=list)


class ReleaseAssignment(Assignment):
    operation_name: str
    station_position: int
    station_row: int
    station_column: int
    sop_title: str
    sop_version: int


class ReleasePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    plan_id: uuid.UUID
    version: int
    order_id: uuid.UUID
    line_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    due_date: date
    product_sop_version_id: uuid.UUID | None = None
    product_sop_version: int | None = None
    assignments: list[ReleaseAssignment]
    published_at: datetime


class PlanStationProgress(BaseModel):
    station_id: uuid.UUID
    station_name: str
    station_position: int
    terminal_code: str | None = None
    terminal_active: bool = False
    is_assigned: bool
    input_total: int
    good_total: int
    bad_total: int
    last_report_at: datetime | None = None


class PlanOperationProgress(BaseModel):
    operation_id: uuid.UUID
    operation_name: str
    is_assigned: bool
    input_total: int
    good_total: int
    bad_total: int
    completed_total: int
    remaining_qty: int
    completion_rate: float
    stations: list[PlanStationProgress]


class PlanTaskDetail(BaseModel):
    plan: PlanPublic
    release: ReleasePublic
    operations: list[PlanOperationProgress]


class ListWorkshops(BaseModel):
    items: list[WorkshopPublic]
    total: int


class ListLines(BaseModel):
    items: list[LinePublic]
    total: int


class ListOrders(BaseModel):
    items: list[OrderPublic]
    total: int


class ListPlans(BaseModel):
    items: list[PlanPublic]
    total: int


class PlanGroupInput(BaseModel):
    switch_mode: Literal["together", "independent"] = "together"
    name: str = Field(min_length=1, max_length=100)
    start_at: datetime | None = None
    plan_ids: list[uuid.UUID] = Field(default_factory=list)


class PlanGroupPublic(PlanGroupInput):
    id: uuid.UUID
    created_at: datetime
    is_paused: bool


class ListPlanGroups(BaseModel):
    items: list[PlanGroupPublic]
    total: int


class ListReleases(BaseModel):
    items: list[ReleasePublic]
    total: int


class ApprovedProductOperation(BaseModel):
    operation_id: uuid.UUID
    code: str
    name: str
    sop_id: uuid.UUID
    sop_title: str
    sop_version: int


class ApprovedProductOperations(BaseModel):
    product_id: uuid.UUID
    product_sop_version_id: uuid.UUID
    version: int
    operations: list[ApprovedProductOperation]


class ApprovedProductVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: int
    reviewed_at: datetime | None = None


class ApprovedProductVersions(BaseModel):
    items: list[ApprovedProductVersionSummary]
    total: int
