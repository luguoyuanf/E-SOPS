"""Read-only ESOP dashboard, scoped by tenant, production line and local day."""
import uuid
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import func, or_
from sqlmodel import select

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import (
    AlarmEvent,
    Operation,
    ProductionLine,
    ProductionOrder,
    ProductionPlan,
    ProductionReport,
    ProductSopVersion,
    Station,
    Terminal,
    WorkRelease,
    Workshop,
)
from app.modules.esop.infrastructure.tenant_uow import (
    EsopTenantUnitOfWork,
    EsopTenantUowDep,
)
from app.modules.esop.public_api.dashboard_dto import (
    DashboardCount,
    DashboardLine,
    DashboardMonth,
    DashboardOption,
    DashboardReport,
    DataScreenDashboard,
    DataScreenLink,
    EsopDashboard,
)
from app.platform.web_api import (
    CurrentPrincipal,
    CurrentTenant,
    SessionDep,
    issue_view_key,
    require_module_access,
    resolve_view_key,
)

router = APIRouter(prefix="/esop", tags=["esop-dashboard"])
PLAN_LABELS = {"completed": "已完成", "published": "进行中", "draft": "待开始",
               "paused": "已暂停", "expired": "已逾期", "cancelled": "已作废"}
LINE_LABELS = {"published": "运行中", "paused": "已暂停", "expired": "异常", "waiting": "待产"}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _counts(labels: dict[str, str], values: Counter) -> list[DashboardCount]:
    return [DashboardCount(key=key, label=label, count=values[key]) for key, label in labels.items()]


def _line_status(plans: list[ProductionPlan]) -> str:
    statuses = {plan.status for plan in plans}
    return next((key for key in ("expired", "published", "paused") if key in statuses), "waiting")


@router.get("/dashboard", response_model=EsopDashboard,
            dependencies=[Depends(require_module_access("esop", "dashboard:view"))])
def read_esop_dashboard(
    uow: EsopTenantUowDep, day: date | None = None,
    workshop_id: uuid.UUID | None = None, line_id: uuid.UUID | None = None,
    timezone: str = "Asia/Taipei",
) -> EsopDashboard:
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=422, detail="无效的统计时区") from None
    now = get_datetime_utc()
    day = day or now.astimezone(zone).date()
    if day > now.astimezone(zone).date():
        raise HTTPException(status_code=422, detail="统计日期不能晚于今天")
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    cutoff = min(end, now)
    session = uow.session
    workshops = session.exec(select(Workshop).order_by(Workshop.code)).all()
    all_lines = session.exec(select(ProductionLine).order_by(ProductionLine.code)).all()
    if workshop_id and workshop_id not in {row.id for row in workshops}:
        raise HTTPException(status_code=404, detail="车间不存在")
    if line_id and not any(row.id == line_id and (not workshop_id or row.workshop_id == workshop_id) for row in all_lines):
        raise HTTPException(status_code=404, detail="产线不属于当前车间")
    lines = [row for row in all_lines if (not workshop_id or row.workshop_id == workshop_id) and (not line_id or row.id == line_id)]
    line_ids = [row.id for row in lines]
    scoped = bool(workshop_id or line_id)
    stations = session.exec(select(Station).where(Station.line_id.in_(line_ids))).all()
    station_lines = {row.id: row.line_id for row in stations}
    terminals = session.exec(select(Terminal).where(Terminal.station_id.in_(station_lines)) if scoped else select(Terminal)).all()
    online = {row.id for row in terminals if row.is_active and row.last_seen_at is not None
              and now - timedelta(seconds=120) <= _utc(row.last_seen_at) <= now}
    # Undated drafts belong to creation day; started tasks span calendar days.
    plans = session.exec(select(ProductionPlan).where(
        ProductionPlan.line_id.in_(line_ids),
        func.coalesce(ProductionPlan.start_at, ProductionPlan.created_at) < end,
        or_(ProductionPlan.end_at >= start,
            (ProductionPlan.end_at.is_(None) & (ProductionPlan.start_at.is_not(None))),
            (ProductionPlan.start_at.is_(None) & (ProductionPlan.created_at >= start))),
    )).all()
    plans_by_line = {id: [] for id in line_ids}
    for plan in plans:
        plans_by_line[plan.line_id].append(plan)
    terminals_by_line = {id: [] for id in line_ids}
    for terminal in terminals:
        if (id := station_lines.get(terminal.station_id)) is not None:
            terminals_by_line[id].append(terminal)
    active_releases = session.exec(select(WorkRelease).where(
        WorkRelease.line_id.in_(line_ids), WorkRelease.is_active == True,  # noqa: E712
    ).order_by(WorkRelease.published_at.desc())).all()
    versions = session.exec(select(ProductSopVersion).where(
        ProductSopVersion.status == "approved", ProductSopVersion.reviewed_at < cutoff,
    ).order_by(ProductSopVersion.version.desc())).all()
    product_scope = None
    if scoped:
        product_scope = set(session.exec(select(ProductionOrder.product_id).join(
            ProductionPlan, ProductionPlan.order_id == ProductionOrder.id,
        ).where(ProductionPlan.line_id.in_(line_ids))).all())
        versions = [row for row in versions if row.product_id in product_scope]
    latest = {}
    for version in versions:
        latest.setdefault(version.product_id, version)
    first_approved = {}
    for version in versions:
        if version.operations:
            approved_at = _utc(version.reviewed_at)
            first_approved[version.product_id] = min(
                first_approved.get(version.product_id, approved_at), approved_at,
            )
    months = []
    month_index = day.year * 12 + day.month - 1
    for offset in range(5, -1, -1):
        year, month = divmod(month_index - offset, 12)
        next_year, next_month = divmod(month_index - offset + 1, 12)
        boundary = datetime(next_year, next_month + 1, 1, tzinfo=zone).astimezone(UTC)
        months.append(DashboardMonth(month=f"{year:04d}-{month + 1:02d}",
                                     count=sum(moment < min(boundary, cutoff) for moment in first_approved.values())))
    version_names = {row.id: f"{row.product_name} / V{row.version}" for row in versions}
    report_rows = session.exec(select(
        WorkRelease.line_id, ProductionReport.operation_id, func.sum(ProductionReport.input_qty),
        func.sum(ProductionReport.good_qty), func.sum(ProductionReport.defect_qty), func.count(ProductionReport.id),
    ).join(WorkRelease, WorkRelease.id == ProductionReport.release_id).where(
        WorkRelease.line_id.in_(line_ids), ProductionReport.is_deleted == False,  # noqa: E712
        ProductionReport.occurred_at >= start, ProductionReport.occurred_at < end,
    ).group_by(WorkRelease.line_id, ProductionReport.operation_id)).all()
    operation_names = dict(session.exec(select(Operation.id, Operation.name)).all())
    alarms = session.exec(select(AlarmEvent).where(
        AlarmEvent.station_id.in_(station_lines), AlarmEvent.resolved_at.is_(None),
    )).all()
    alarm_lines = Counter(station_lines[row.station_id] for row in alarms)
    # Count only the last assigned operation; summing all steps inflates output.
    output_rows = session.exec(select(ProductionReport, WorkRelease).join(
        WorkRelease, WorkRelease.id == ProductionReport.release_id,
    ).where(WorkRelease.line_id.in_(line_ids),
            ProductionReport.is_deleted == False,  # noqa: E712
            ProductionReport.occurred_at >= start, ProductionReport.occurred_at < end)).all()
    finished = Counter()
    for report, release in output_rows:
        operations = list(dict.fromkeys(str(item["operation_id"]) for item in release.assignments))
        if operations and str(report.operation_id) == operations[-1]:
            finished[release.line_id] += report.good_qty
    result_lines = []
    for line in lines:
        devices = terminals_by_line[line.id]
        line_plans = plans_by_line[line.id]
        current_sop = list(dict.fromkeys(version_names.get(release.product_sop_version_id, "历史 SOP")
                                        for release in active_releases if release.line_id == line.id))
        result_lines.append(DashboardLine(
            id=line.id, code=line.code, name=line.name, workshop_id=line.workshop_id,
            terminal_total=len(devices), terminal_online=sum(row.id in online for row in devices),
            planned_qty=sum(row.quantity for row in line_plans if row.status != "cancelled"),
            finished_qty=finished[line.id], unresolved_alarms=alarm_lines[line.id],
            plan_total=len(line_plans), plan_counts=dict(Counter(row.status for row in line_plans)),
            status=_line_status(line_plans), current_sop=current_sop,
        ))
    return EsopDashboard(
        updated_at=now, day=day, timezone=timezone,
        effective_sop=sum(bool(version.operations) for version in latest.values()),
        effective_operations=sum(len(version.operations) for version in latest.values()),
        cumulative_sop=len(first_approved), sop_trend=months,
        workshops=[DashboardOption(id=row.id, name=row.name) for row in workshops],
        line_options=[DashboardOption(id=row.id, name=row.name, workshop_id=row.workshop_id) for row in all_lines],
        lines=result_lines, line_counts=_counts(LINE_LABELS, Counter(row.status for row in result_lines)),
        terminal_total=len(terminals), terminal_online=len(online),
        terminal_unbound=sum(row.station_id is None for row in terminals),
        plan_counts=_counts(PLAN_LABELS, Counter(row.status for row in plans)),
        reports=[DashboardReport(line_id=row[0], operation_id=row[1], operation_name=operation_names.get(row[1], "历史工序"),
                                 input_qty=int(row[2]), good_qty=int(row[3]), defect_qty=int(row[4]), count=int(row[5]))
                 for row in report_rows],
    )


@router.post("/data-screen/link", response_model=DataScreenLink,
             dependencies=[Depends(require_module_access("esop", "dashboard:view"))])
def create_data_screen_link(session: SessionDep, principal: CurrentPrincipal,
                            tenant: CurrentTenant, response: Response) -> DataScreenLink:
    key, expires_at = issue_view_key(session=session, user_id=principal.id,
        tenant_id=tenant.tenant_id, audience="esop:data-screen", module="esop", permission="dashboard:view")
    response.headers["Cache-Control"] = "no-store"
    return DataScreenLink(path=f"/data-screen/#key={key}", expires_at=expires_at)


@router.get("/data-screen/data", response_model=DataScreenDashboard)
def read_data_screen(session: SessionDep, response: Response,
                     key: str = Header(alias="X-Data-Screen-Key", max_length=2048),
                     workshop_id: uuid.UUID | None = None, line_id: uuid.UUID | None = None,
                     timezone: str = "Asia/Taipei") -> DataScreenDashboard:
    from app.modules.esop.data_screen import build_data_screen

    tenant_id = resolve_view_key(session=session, key=key, audience="esop:data-screen",
                                 module="esop", permission="dashboard:view")
    response.headers["Cache-Control"] = "no-store"
    with EsopTenantUnitOfWork(session, tenant_id) as uow:
        dashboard = read_esop_dashboard(uow, workshop_id=workshop_id, line_id=line_id, timezone=timezone)
        return build_data_screen(uow, dashboard, scoped=bool(workshop_id or line_id))
