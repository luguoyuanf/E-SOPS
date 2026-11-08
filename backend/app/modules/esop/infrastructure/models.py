"""Tenant-owned operation, route and controlled SOP versions."""

import secrets
import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.core.database_types import UTCDateTime as DateTime
from app.platform.public_api.codes import generate_entity_code

MYSQL = settings.DATABASE_TYPE == "mysql"
SCHEMA = None if MYSQL else "esop"
JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def table_name(name: str) -> str:
    return f"esop_{name}" if MYSQL else name


class Operation(SQLModel, table=True):
    __tablename__ = table_name("operation")
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_esop_operation_tenant_code"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    code: str = Field(max_length=50)
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    product_id: uuid.UUID | None = Field(default=None, index=True)
    sort_order: int = Field(default=0, nullable=False, sa_column_kwargs={"server_default": "0"})
    is_deleted: bool = Field(default=False, nullable=False, sa_column_kwargs={"server_default": "0"})
    attachments: list[dict[str, object]] = Field(default_factory=list, sa_type=JSON_TYPE)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class ProcessRoute(SQLModel, table=True):
    __tablename__ = table_name("process_route")
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_esop_route_tenant_code"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    code: str = Field(max_length=50)
    name: str = Field(max_length=100)
    operation_ids: list[str] = Field(default_factory=list, sa_type=JSON_TYPE)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class SopDocument(SQLModel, table=True):
    __tablename__ = table_name("sop_document")
    __table_args__ = (
        UniqueConstraint("tenant_id", "family_id", "version", name="uq_esop_sop_family_version"),
        UniqueConstraint("tenant_id", "product_id", "operation_id", "version", name="uq_esop_sop_product_operation_version"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    family_id: uuid.UUID = Field(index=True, nullable=False)
    product_id: uuid.UUID = Field(index=True, nullable=False)
    operation_id: uuid.UUID = Field(index=True, nullable=False)
    version: int = Field(default=1, ge=1)
    status: str = Field(default="draft", sa_type=String(16))
    title: str = Field(max_length=200)
    pages: list[dict[str, object]] = Field(default_factory=list, sa_type=JSON_TYPE)
    created_by: uuid.UUID = Field(nullable=False)
    reviewed_by: uuid.UUID | None = Field(default=None)
    review_note: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class ProductSopLock(SQLModel, table=True):
    __tablename__ = table_name("product_sop_lock")
    __table_args__ = {"schema": SCHEMA}

    tenant_id: uuid.UUID = Field(primary_key=True)
    product_id: uuid.UUID = Field(primary_key=True)


class ProductSopVersion(SQLModel, table=True):
    __tablename__ = table_name("product_sop_version")
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "version", name="uq_esop_product_sop_version"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    product_id: uuid.UUID = Field(index=True, nullable=False)
    product_name: str = Field(max_length=200)
    version: int = Field(ge=1)
    status: str = Field(default="pending", max_length=16)
    operations: list[dict[str, object]] = Field(default_factory=list, sa_type=JSON_TYPE)
    base_version_id: uuid.UUID | None = Field(default=None)
    created_by: uuid.UUID
    submitted_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))
    reviewed_by: uuid.UUID | None = Field(default=None)
    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    review_note: str | None = Field(default=None, max_length=500)


class OperationFileRendition(SQLModel, table=True):
    __tablename__ = table_name("operation_file_rendition")
    __table_args__ = (
        UniqueConstraint("tenant_id", "original_file_id", name="uq_esop_operation_file_rendition"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    original_file_id: uuid.UUID = Field(index=True, nullable=False)
    display_file_id: uuid.UUID
    page_file_ids: list[str] = Field(default_factory=list, sa_type=JSON_TYPE)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))


class OperationMediaJob(SQLModel, table=True):
    __tablename__ = table_name("operation_media_job")
    __table_args__ = (
        UniqueConstraint("tenant_id", "original_file_id", name="uq_esop_operation_media_job_file"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    original_file_id: uuid.UUID = Field(index=True, nullable=False)
    uploader_id: uuid.UUID = Field(nullable=False)
    status: str = Field(default="queued", max_length=16)
    attempts: int = Field(default=0, nullable=False)
    error_message: str | None = Field(default=None, max_length=255)
    started_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))


class Workshop(SQLModel, table=True):
    __tablename__ = table_name("workshop")
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_esop_workshop_tenant_code"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    code: str = Field(max_length=50)
    name: str = Field(max_length=100)
    created_at: datetime | None = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), nullable=True)


class ProductionLine(SQLModel, table=True):
    __tablename__ = table_name("production_line")
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_esop_line_tenant_code"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    workshop_id: uuid.UUID = Field(index=True, nullable=False)
    code: str = Field(max_length=50)
    name: str = Field(max_length=100)
    layout: str = Field(default="single", sa_type=String(16))
    station_count: int = Field(default=1, ge=1)
    numbering_mode: str = Field(default="odd_even", sa_type=String(16))
    created_at: datetime | None = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), nullable=True)


class Station(SQLModel, table=True):
    __tablename__ = table_name("station")
    __table_args__ = (
        UniqueConstraint("tenant_id", "line_id", "position", name="uq_esop_station_line_position"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    line_id: uuid.UUID = Field(index=True, nullable=False)
    position: int = Field(ge=1)
    name: str = Field(default="", max_length=100)
    row: int = Field(ge=1, le=2)
    column: int = Field(ge=1)
    current_release_id: uuid.UUID | None = Field(default=None, nullable=True)
    selected_release_id: uuid.UUID | None = Field(default=None, nullable=True)
    selected_by: uuid.UUID | None = Field(default=None, nullable=True)
    selected_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class ProductionOrder(SQLModel, table=True):
    __tablename__ = table_name("production_order")
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_esop_order_tenant_code"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    code: str = Field(max_length=60)
    product_id: uuid.UUID = Field(index=True, nullable=False)
    product_sop_version_id: uuid.UUID | None = Field(default=None, index=True)
    operation_ids: list[str] | None = Field(default=None, sa_type=JSON_TYPE)
    quantity: int = Field(ge=1)
    due_date: date
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class ProductionPlan(SQLModel, table=True):
    __tablename__ = table_name("production_plan")
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_esop_production_plan_tenant_code"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(default_factory=lambda: generate_entity_code("PLAN"), max_length=50)
    product_sop_version_id: uuid.UUID | None = Field(default=None, index=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    order_id: uuid.UUID = Field(index=True, nullable=False)
    quantity: int = Field(ge=1)
    line_id: uuid.UUID = Field(index=True, nullable=False)
    route_id: uuid.UUID | None = Field(default=None, index=True)
    status: str = Field(default="draft", sa_type=String(16))
    created_by: uuid.UUID | None = Field(default=None)
    group_id: uuid.UUID | None = Field(default=None, index=True)
    group_position: int | None = Field(default=None)
    start_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    end_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    assignments: list[dict[str, object]] = Field(default_factory=list, sa_type=JSON_TYPE)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class ProductionOrderSupplement(SQLModel, table=True):
    __tablename__ = table_name("production_order_supplement")
    __table_args__ = (Index("ix_esop_order_supplement_tenant_order", "tenant_id", "order_id"), {"schema": SCHEMA})

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(nullable=False)
    order_id: uuid.UUID = Field(nullable=False)
    quantity: int = Field(ge=1)
    reason: str = Field(max_length=500)
    status: str = Field(default="pending", sa_type=String(16))
    requested_by: uuid.UUID = Field(nullable=False)
    reviewed_by: uuid.UUID | None = Field(default=None)
    review_note: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class ProductionPlanGroup(SQLModel, table=True):
    __tablename__ = table_name("production_plan_group")
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    name: str = Field(max_length=100)
    created_by: uuid.UUID = Field(nullable=False)
    is_paused: bool = Field(default=False, nullable=False, sa_column_kwargs={"server_default": "0"})
    switch_mode: str = Field(default="together", max_length=16, sa_column_kwargs={"server_default": "together"})
    start_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class WorkRelease(SQLModel, table=True):
    __tablename__ = table_name("work_release")
    __table_args__ = (
        UniqueConstraint("tenant_id", "plan_id", "version", name="uq_esop_release_plan_version"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    product_sop_version_id: uuid.UUID | None = Field(default=None, index=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    plan_id: uuid.UUID = Field(index=True, nullable=False)
    version: int = Field(default=1, ge=1)
    order_id: uuid.UUID = Field(index=True, nullable=False)
    line_id: uuid.UUID = Field(index=True, nullable=False)
    product_id: uuid.UUID = Field(index=True, nullable=False)
    quantity: int = Field(ge=1)
    due_date: date
    assignments: list[dict[str, object]] = Field(default_factory=list, sa_type=JSON_TYPE)
    published_by: uuid.UUID = Field(nullable=False)
    published_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    is_active: bool = True


class WorkReleaseAssignment(SQLModel, table=True):
    __tablename__ = table_name("work_release_assignment")
    __table_args__ = {"schema": SCHEMA}

    release_id: uuid.UUID = Field(primary_key=True)
    ordinal: int = Field(primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    station_id: uuid.UUID = Field(index=True, nullable=False)
    operation_id: uuid.UUID = Field(index=True, nullable=False)
    operation_name: str = Field(default="", max_length=100)


# These two lookup tables resolve an opaque device credential before tenant scope
# exists. They are deliberately outside OWNED_MODELS and have no public CRUD.
class ActivationKey(SQLModel, table=True):
    __tablename__ = table_name("activation_key")
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID | None = Field(default=None, index=True)
    key_hash: str = Field(unique=True, max_length=64)
    key_ciphertext: str | None = Field(default=None, max_length=300)
    grant_type: str = Field(default="paid", max_length=8)
    channel_id: uuid.UUID | None = Field(default=None)
    hardware_model_id: uuid.UUID | None = Field(default=None)
    batch_id: uuid.UUID | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    used_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    used_terminal_id: uuid.UUID | None = Field(default=None)


class ActivationUnbindLog(SQLModel, table=True):
    __tablename__ = table_name("activation_unbind_log")
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    key_id: uuid.UUID = Field(index=True)
    tenant_id: uuid.UUID
    terminal_id: uuid.UUID
    device_code: str = Field(max_length=120)
    activated_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    unbound_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    actor_id: uuid.UUID
    reason: str = Field(max_length=500)


class TerminalInstallation(SQLModel, table=True):
    """Global pre-tenant installation identity; grants no device authorization."""

    __tablename__ = table_name("terminal_installation")
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    installation_hash: str = Field(unique=True, max_length=64)
    device_code: str = Field(unique=True, max_length=10)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))


class DeviceCredential(SQLModel, table=True):
    __tablename__ = table_name("device_credential")
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    device_code: str = Field(unique=True, max_length=120)
    token_hash: str = Field(unique=True, max_length=64)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    terminal_id: uuid.UUID = Field(unique=True, nullable=False)


class Terminal(SQLModel, table=True):
    __tablename__ = table_name("terminal")
    __table_args__ = (
        UniqueConstraint("tenant_id", "device_code", name="uq_esop_terminal_tenant_device"),
        UniqueConstraint("serial_number", name="uq_esop_terminal_serial_number"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    device_code: str = Field(max_length=120)
    serial_number: str = Field(default_factory=lambda: f"SN{secrets.randbelow(100_000_000):08d}", max_length=10)
    device_name: str | None = Field(default=None, max_length=100)
    channel_id: uuid.UUID | None = Field(default=None)
    hardware_model_id: uuid.UUID | None = Field(default=None)
    station_id: uuid.UUID | None = Field(default=None, index=True)
    is_active: bool = True
    app_version: str | None = Field(default=None, max_length=80)
    last_seen_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    last_ip: str | None = Field(default=None, max_length=45)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class ProductionReport(SQLModel, table=True):
    __tablename__ = table_name("production_report")
    __table_args__ = (
        UniqueConstraint("tenant_id", "terminal_id", "request_id", name="uq_esop_report_device_request"),
        UniqueConstraint("tenant_id", "submitted_by", "request_id", name="uq_esop_report_web_request"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    terminal_id: uuid.UUID | None = Field(default=None, index=True, nullable=True)
    submitted_by: uuid.UUID | None = Field(default=None, nullable=True)
    revision: int = Field(default=0, ge=0)
    is_deleted: bool = Field(default=False, nullable=False, sa_column_kwargs={"server_default": "0"})
    request_id: str = Field(max_length=100)
    request_hash: str = Field(max_length=64)
    staff_user_id: uuid.UUID = Field(index=True, nullable=False)
    staff_name: str = Field(max_length=200)
    release_id: uuid.UUID = Field(index=True, nullable=False)
    order_id: uuid.UUID = Field(index=True, nullable=False)
    order_code: str = Field(max_length=60)
    station_id: uuid.UUID = Field(index=True, nullable=False)
    station_position: int = Field(ge=1)
    operation_id: uuid.UUID = Field(index=True, nullable=False)
    sop_id: uuid.UUID = Field(index=True, nullable=False)
    sop_version: int = Field(ge=1)
    sop_title: str = Field(max_length=200)
    input_qty: int = Field(default=0, ge=0)
    good_qty: int = Field(default=0, ge=0)
    defect_qty: int = Field(default=0, ge=0)
    occurred_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class SipInspection(SQLModel, table=True):
    __tablename__ = table_name("sip_inspection")
    __table_args__ = (
        UniqueConstraint("tenant_id", "terminal_id", "request_id", name="uq_esop_sip_terminal_request"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    release_id: uuid.UUID = Field(index=True, nullable=False)
    operation_id: uuid.UUID = Field(index=True, nullable=False)
    station_id: uuid.UUID = Field(index=True, nullable=False)
    terminal_id: uuid.UUID = Field(index=True, nullable=False)
    staff_user_id: uuid.UUID = Field(nullable=False)
    request_id: str = Field(max_length=100)
    quantity: int = Field(ge=1)
    report_allocations: list[dict[str, object]] = Field(default_factory=list, sa_type=JSON_TYPE)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class ProductionReportRevision(SQLModel, table=True):
    __tablename__ = table_name("production_report_revision")
    __table_args__ = (
        UniqueConstraint("tenant_id", "report_id", "revision", name="uq_esop_report_revision"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    report_id: uuid.UUID = Field(index=True, nullable=False)
    revision: int = Field(ge=1)
    reason: str = Field(max_length=500)
    changed_by: uuid.UUID
    changed_by_name: str = Field(max_length=255)
    changed_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    before: dict = Field(sa_type=JSON_TYPE)
    after: dict = Field(sa_type=JSON_TYPE)


class ProductionReportChange(SQLModel, table=True):
    __tablename__ = table_name("production_report_change")
    __table_args__ = (
        UniqueConstraint("tenant_id", "report_id", "request_id", name="uq_esop_report_change_request"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    report_id: uuid.UUID = Field(index=True, nullable=False)
    request_id: uuid.UUID
    kind: str = Field(default="edit", max_length=16, sa_column_kwargs={"server_default": "edit"})
    expected_revision: int
    requested_by: uuid.UUID
    requested_by_name: str = Field(max_length=255)
    reason: str = Field(max_length=500)
    before: dict = Field(sa_type=JSON_TYPE)
    after: dict = Field(sa_type=JSON_TYPE)
    status: str = Field(default="pending", max_length=16)
    requested_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    reviewed_by: uuid.UUID | None = None
    reviewed_by_name: str | None = Field(default=None, max_length=255)
    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    review_note: str | None = Field(default=None, max_length=500)


class AlarmEvent(SQLModel, table=True):
    __tablename__ = table_name("alarm_event")
    __table_args__ = (
        UniqueConstraint("tenant_id", "terminal_id", "request_id", name="uq_esop_alarm_device_request"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    terminal_id: uuid.UUID = Field(index=True, nullable=False)
    station_id: uuid.UUID = Field(index=True, nullable=False)
    staff_user_id: uuid.UUID | None = Field(default=None, index=True)
    request_id: str = Field(max_length=100)
    request_hash: str = Field(max_length=64)
    release_id: uuid.UUID | None = Field(default=None, index=True)
    level: str = Field(max_length=12)
    reason: str = Field(max_length=500)
    type_code: str | None = Field(default=None, max_length=100)
    type_name: str | None = Field(default=None, max_length=100)
    resolved_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    resolved_by: uuid.UUID | None = Field(default=None)
    occurred_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class AlarmTypePreference(SQLModel, table=True):
    __tablename__ = table_name("alarm_type_preference")
    __table_args__ = (
        UniqueConstraint("tenant_id", "type_code", name="uq_esop_alarm_type_preference"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    type_code: str = Field(max_length=100)
    enabled: bool = Field(default=True, nullable=False)
    sort: int = Field(default=0, nullable=False)


class Channel(SQLModel, table=True):
    __tablename__ = table_name("channel")
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, max_length=50)
    name: str = Field(max_length=100)
    created_at: datetime | None = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), nullable=True)


class HardwareModel(SQLModel, table=True):
    __tablename__ = table_name("hardware_model")
    __table_args__ = (
        UniqueConstraint("channel_id", "code", name="uq_esop_hardware_channel_code"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_id: uuid.UUID = Field(index=True, nullable=False)
    code: str = Field(max_length=50)
    name: str = Field(max_length=100)
    abi: str = Field(max_length=30)
    created_at: datetime | None = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), nullable=True)


class OtaPackage(SQLModel, table=True):
    __tablename__ = table_name("ota_package")
    __table_args__ = (
        UniqueConstraint("hardware_model_id", "version", name="uq_esop_ota_model_version"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_id: uuid.UUID = Field(index=True, nullable=False)
    hardware_model_id: uuid.UUID = Field(index=True, nullable=False)
    file_owner_tenant_id: uuid.UUID = Field(nullable=False)
    file_id: uuid.UUID = Field(nullable=False)
    file_size: int = Field(ge=0)
    version: str = Field(max_length=80)
    version_code: int = Field(default=0, ge=0)
    package_name: str = Field(default="", max_length=200)
    release_notes: str = Field(default="", max_length=4000)
    checksum_sha256: str = Field(max_length=64)
    status: str = Field(default="draft", max_length=16)
    published_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class ChannelAdmin(SQLModel, table=True):
    __tablename__ = table_name("channel_admin")
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_id: uuid.UUID = Field(index=True, nullable=False)
    user_id: uuid.UUID = Field(unique=True, nullable=False)


class ChannelCustomerTenant(SQLModel, table=True):
    __tablename__ = table_name("channel_customer_tenant")
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_id: uuid.UUID = Field(index=True, nullable=False)
    tenant_id: uuid.UUID = Field(unique=True, nullable=False)
    created_by: uuid.UUID = Field(nullable=False)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class Broadcast(SQLModel, table=True):
    __tablename__ = table_name("broadcast")
    __table_args__ = (
        UniqueConstraint("tenant_id", "position", name="uq_esop_broadcast_tenant_position"),
        {"schema": SCHEMA},
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    position: str = Field(max_length=8)
    content: str = Field(max_length=500)
    font_size: int = Field(ge=12, le=72)
    background_color: str = Field(max_length=7)
    font_color: str = Field(max_length=7)
    is_active: bool = True
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


class BroadcastRecord(SQLModel, table=True):
    __tablename__ = table_name("broadcast_record")
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    position: str = Field(max_length=8)
    content: str = Field(max_length=500)
    font_size: int = Field(ge=12, le=72)
    background_color: str = Field(max_length=7)
    font_color: str = Field(max_length=7)
    is_active: bool = True
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))


class Advertisement(SQLModel, table=True):
    __tablename__ = table_name("advertisement")
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    title: str = Field(max_length=100)
    layout: str = Field(max_length=16)
    playback: str = Field(max_length=16)
    interval_minutes: int = 30
    starts_at: datetime = Field(sa_type=DateTime(timezone=True))
    ends_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    daily_start: str | None = Field(default=None, max_length=5)
    daily_end: str | None = Field(default=None, max_length=5)
    media: list[dict] = Field(default_factory=list, sa_type=JSON_TYPE)
    is_active: bool = False
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))


class PurchaseContent(SQLModel, table=True):
    __tablename__ = table_name("purchase_content")
    __table_args__ = {"schema": SCHEMA}

    id: int = Field(default=1, primary_key=True)
    content: dict = Field(sa_type=JSON_TYPE)
    updated_by: uuid.UUID
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))  # type: ignore


OWNED_MODELS = (
    Operation, ProcessRoute, SopDocument, ProductSopLock, ProductSopVersion, OperationFileRendition, OperationMediaJob, Workshop, ProductionLine, Station, SipInspection,
    ProductionOrder, ProductionPlan, ProductionOrderSupplement, ProductionPlanGroup, WorkRelease, WorkReleaseAssignment, Terminal, ProductionReport, ProductionReportRevision, ProductionReportChange,
    AlarmEvent, AlarmTypePreference, Broadcast, BroadcastRecord, Advertisement,
)

ALL_MODELS = (
    *OWNED_MODELS, ActivationKey, ActivationUnbindLog, DeviceCredential, TerminalInstallation, Channel, HardwareModel,
    OtaPackage, ChannelAdmin, ChannelCustomerTenant, PurchaseContent,
)
