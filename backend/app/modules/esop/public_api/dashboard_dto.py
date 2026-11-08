"""Tenant dashboard read models; device states are always live."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel


class DashboardOption(BaseModel):
    id: uuid.UUID
    name: str
    workshop_id: uuid.UUID | None = None


class DashboardCount(BaseModel):
    key: str
    label: str
    count: int


class DashboardLine(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    workshop_id: uuid.UUID
    terminal_total: int
    terminal_online: int
    plan_total: int
    planned_qty: int = 0
    finished_qty: int = 0
    unresolved_alarms: int = 0
    plan_counts: dict[str, int]
    status: str
    current_sop: list[str]


class DashboardReport(BaseModel):
    line_id: uuid.UUID
    operation_id: uuid.UUID
    operation_name: str
    input_qty: int
    good_qty: int
    defect_qty: int
    count: int


class DashboardMonth(BaseModel):
    month: str
    count: int


class EsopDashboard(BaseModel):
    updated_at: datetime
    day: date
    timezone: str
    effective_sop: int
    effective_operations: int
    cumulative_sop: int
    sop_trend: list[DashboardMonth]
    workshops: list[DashboardOption]
    line_options: list[DashboardOption]
    lines: list[DashboardLine]
    line_counts: list[DashboardCount]
    terminal_total: int
    terminal_online: int
    terminal_unbound: int
    plan_counts: list[DashboardCount]
    reports: list[DashboardReport]


class DataScreenLink(BaseModel):
    path: str
    expires_at: datetime


class ScreenLineProgress(BaseModel):
    line_id: uuid.UUID
    planned_qty: int
    good_qty: int


class ScreenRunningOrder(BaseModel):
    order_id: uuid.UUID
    order_code: str
    product_name: str
    line_name: str
    plan_code: str
    plan_quantity: int
    good_qty: int
    due_date: date


class DataScreenDashboard(EsopDashboard):
    order_total: int
    order_running: int
    order_completed: int
    order_overdue: int
    running_orders: list[ScreenRunningOrder]
    line_progress: list[ScreenLineProgress]
