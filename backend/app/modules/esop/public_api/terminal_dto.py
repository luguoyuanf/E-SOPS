"""Device, offline report and alarm request contracts."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .dto import OperationAttachment


class InstallationInput(BaseModel):
    installationId: str = Field(min_length=16, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class InstallationPublic(BaseModel):
    deviceCode: str = Field(pattern=r"^SN[0-9]{8}$")


class ActivateInput(BaseModel):
    tenantCode: str = Field(min_length=3, max_length=100)
    key: str = Field(min_length=8, max_length=8)
    deviceCode: str = Field(min_length=8, max_length=120)


class DeviceIdentityPublic(BaseModel):
    deviceToken: str
    tenantId: uuid.UUID
    deviceId: uuid.UUID


class WebTerminalBootstrapPublic(DeviceIdentityPublic):
    profile: dict[str, Any]


class StaffLoginInput(BaseModel):
    username: str | None = Field(default=None, max_length=320)
    empNo: str | None = Field(default=None, max_length=320)
    password: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_identity(self) -> StaffLoginInput:
        if not (self.username or self.empNo):
            raise ValueError("username or empNo is required")
        return self


class StationBindInput(BaseModel):
    station_id: uuid.UUID | None


class TerminalNameInput(BaseModel):
    device_name: str = Field(min_length=1, max_length=100)


class ActivationUnbindInput(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ActivationIssueInput(BaseModel):
    tenant_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None
    hardware_model_id: uuid.UUID | None = None


class ReportInput(BaseModel):
    requestId: str = Field(min_length=1, max_length=100)
    releaseId: uuid.UUID
    orderId: uuid.UUID
    sopId: uuid.UUID
    inputQty: int = Field(default=0, ge=0)
    goodQty: int = Field(default=0, ge=0)
    defectQty: int = Field(default=0, ge=0)
    occurredAt: datetime | None = None


class AlarmInput(BaseModel):
    requestId: str = Field(min_length=1, max_length=100)
    releaseId: uuid.UUID | None = None
    typeCode: str | None = Field(default=None, min_length=1, max_length=100)
    level: Literal["red", "yellow", "green"] = "red"
    reason: str | None = Field(default=None, max_length=500)
    occurredAt: datetime | None = None


class TerminalPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    device_code: str
    serial_number: str
    device_name: str | None
    channel_id: uuid.UUID | None
    hardware_model_id: uuid.UUID | None
    station_id: uuid.UUID | None
    app_version: str | None
    last_seen_at: datetime | None
    last_ip: str | None
    is_active: bool
    is_online: bool = False


class ActivationKeyPublic(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    key: str | None = None
    device_code: str | None = None
    used_terminal_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None
    hardware_model_id: uuid.UUID | None
    created_at: datetime
    used_at: datetime | None
    is_used: bool


class IssuedActivationKey(ActivationKeyPublic):
    key: str


class ReportPublic(BaseModel):
    is_deleted: bool = False
    change_kind: str | None = None
    change_status: str | None = None
    change_id: uuid.UUID | None = None
    change_reason: str | None = None
    revision: int = 0
    terminal_id: uuid.UUID | None = None
    submitted_by: uuid.UUID | None = None
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    release_id: uuid.UUID
    order_id: uuid.UUID
    order_code: str
    station_id: uuid.UUID
    station_position: int
    sop_id: uuid.UUID
    sop_version: int
    sop_title: str
    staff_user_id: uuid.UUID
    staff_name: str
    input_qty: int
    good_qty: int
    defect_qty: int
    occurred_at: datetime
    created_at: datetime


class TerminalReportPublic(ReportPublic):
    product_name: str = ""
    product_model: str | None = None


class ListTerminalReports(BaseModel):
    items: list[TerminalReportPublic]
    total: int


class ReportSopPreview(BaseModel):
    product_id: uuid.UUID
    operation_id: uuid.UUID
    title: str
    version: int
    attachments: list[OperationAttachment]


class AlarmPublic(BaseModel):
    release_id: uuid.UUID | None = None
    plan_id: uuid.UUID | None = None
    plan_code: str | None = None
    order_id: uuid.UUID | None = None
    order_code: str | None = None
    staff_name: str | None = None
    terminal_name: str | None = None
    station_name: str | None = None
    staff_user_id: uuid.UUID | None = None
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    terminal_id: uuid.UUID
    station_id: uuid.UUID
    level: str
    reason: str
    type_code: str | None = None
    type_name: str | None = None
    resolved_at: datetime | None = None
    resolved_by: uuid.UUID | None = None
    occurred_at: datetime
    created_at: datetime


class ListTerminals(BaseModel):
    items: list[TerminalPublic]
    total: int


class ListActivationKeys(BaseModel):
    items: list[ActivationKeyPublic]
    total: int


class ListReports(BaseModel):
    items: list[ReportPublic]
    total: int


class ListAlarms(BaseModel):
    items: list[AlarmPublic]
    total: int


class OrderOperationProgress(BaseModel):
    operation_id: uuid.UUID
    operation_name: str
    completed_total: int
    bad_total: int
    completion_rate: float


class OrderProgress(BaseModel):
    order_id: uuid.UUID
    quantity: int
    input_total: int
    good_total: int
    bad_total: int
    completion_rate: float = 0.0
    operations: list[OrderOperationProgress] = Field(default_factory=list)


class ListOrderProgress(BaseModel):
    items: list[OrderProgress]
    total: int


class ReportFilterOption(BaseModel):
    value: uuid.UUID
    label: str


class ReportStationOption(ReportFilterOption):
    line_id: uuid.UUID


class ReportFilterOptions(BaseModel):
    orders: list[ReportFilterOption]
    lines: list[ReportFilterOption]
    stations: list[ReportStationOption]
    staff: list[ReportFilterOption]


class WebReportInput(BaseModel):
    request_id: uuid.UUID
    release_id: uuid.UUID
    station_id: uuid.UUID
    operation_id: uuid.UUID
    sop_id: uuid.UUID
    staff_user_id: uuid.UUID | None = None
    input_qty: int = Field(default=0, ge=0)
    good_qty: int = Field(default=0, ge=0)
    defect_qty: int = Field(default=0, ge=0)


class WebReportTask(BaseModel):
    release_id: uuid.UUID
    order_code: str
    plan_code: str
    line_name: str
    station_id: uuid.UUID
    station_name: str
    operation_id: uuid.UUID
    operation_name: str
    sop_id: uuid.UUID
    sop_title: str
    sop_version: int


class WebReportOptions(BaseModel):
    can_select_staff: bool
    current_user_id: uuid.UUID
    staff: list[ReportFilterOption]
    tasks: list[WebReportTask]


class ReportCorrectionOptions(BaseModel):
    can_edit: bool
    staff: list[ReportFilterOption]


class ReportCorrectionInput(BaseModel):
    expected_revision: int = Field(ge=0)
    staff_user_id: uuid.UUID
    input_qty: int = Field(ge=0)
    good_qty: int = Field(ge=0)
    defect_qty: int = Field(ge=0)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ReportRevisionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    report_id: uuid.UUID
    revision: int
    reason: str
    changed_by: uuid.UUID
    changed_by_name: str
    changed_at: datetime
    before: dict
    after: dict


class ReportRevisionList(BaseModel):
    items: list[ReportRevisionPublic]
    total: int


class ReportDeleteInput(BaseModel):
    request_id: uuid.UUID
    expected_revision: int = Field(ge=0)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ReportChangeInput(BaseModel):
    request_id: uuid.UUID
    expected_revision: int = Field(ge=0)
    input_qty: int = Field(ge=0)
    good_qty: int = Field(ge=0)
    defect_qty: int = Field(ge=0)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ReportChangePublic(BaseModel):
    kind: str = "edit"
    order_code: str = ""
    sop_title: str = ""
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    report_id: uuid.UUID
    request_id: uuid.UUID
    expected_revision: int
    requested_by: uuid.UUID
    requested_by_name: str
    requested_at: datetime
    reason: str
    before: dict
    after: dict
    status: str
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    review_note: str | None


class ListReportChanges(BaseModel):
    items: list[ReportChangePublic]
    total: int


class ReportChangeReview(BaseModel):
    approve: bool
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
