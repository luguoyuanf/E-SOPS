"""Workshop, production order and immutable work-release APIs."""

import csv
import io
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.core.clock import get_datetime_utc
from app.core.export_datetime import (
    ExportTimezoneHeader,
    export_datetime,
    export_timezone,
)
from app.modules.esop.infrastructure.models import (
    AlarmEvent,
    ProductionLine,
    ProductionOrder,
    ProductionOrderSupplement,
    ProductionPlan,
    ProductionPlanGroup,
    ProductionReport,
    ProductSopVersion,
    SopDocument,
    Station,
    Terminal,
    WorkRelease,
    Workshop,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUowDep
from app.modules.esop.product_sop import lock_product
from app.modules.esop.public_api.production_dto import (
    ApprovedProductOperation,
    ApprovedProductOperations,
    ApprovedProductVersions,
    ApprovedProductVersionSummary,
    LineInput,
    LinePublic,
    ListLines,
    ListOrders,
    ListPlanGroups,
    ListPlans,
    ListReleases,
    ListSupplements,
    ListWorkshops,
    OrderAllocationPublic,
    OrderExportInput,
    OrderInput,
    OrderOperationsInput,
    OrderPublic,
    PlanGroupInput,
    PlanGroupPublic,
    PlanInput,
    PlanOperationProgress,
    PlanPublic,
    PlanStationProgress,
    PlanTaskDetail,
    ReleasePublic,
    StationPublic,
    SupplementInput,
    SupplementPublic,
    SupplementReview,
    WorkshopInput,
    WorkshopPublic,
)
from app.modules.product_directory import ProductDirectoryDep
from app.platform.public_api.codes import generate_entity_code
from app.platform.web_api import (
    CurrentPrincipal,
    UserDirectoryDep,
    normalize_pagination,
    require_any_module_access,
    require_module_access,
)

router = APIRouter(prefix="/esop", tags=["esop-production"])


def _owned[T: Workshop | ProductionLine | Station | ProductionOrder | ProductionPlan | ProductionPlanGroup | SopDocument | ProductSopVersion](
    uow: EsopTenantUowDep, model: type[T], id: uuid.UUID
) -> T:
    # Serialize deletion with line edits, plan assignments and terminal binding.
    entity = (
        uow.session.exec(select(model).where(model.id == id).with_for_update()).first()
        if model in (Workshop, ProductionLine) else uow.session.get(model, id)
    )
    if entity is None or entity.tenant_id != uow.tenant_id:
        raise HTTPException(status_code=404, detail="资料不存在或不属于当前租户")
    return entity


def _commit(uow: EsopTenantUowDep) -> None:
    try:
        uow.session.commit()
    except IntegrityError as exc:
        uow.session.rollback()
        raise HTTPException(status_code=409, detail="编码或发布记录已存在") from exc


def _stations(uow: EsopTenantUowDep, line_id: uuid.UUID) -> list[Station]:
    return list(uow.session.exec(select(Station).where(Station.line_id == line_id).order_by(Station.position)).all())


def _line_public(uow: EsopTenantUowDep, line: ProductionLine) -> LinePublic:
    stations = _stations(uow, line.id)
    terminals = {terminal.station_id: terminal for terminal in uow.session.exec(
        select(Terminal).where(
            Terminal.station_id.in_([station.id for station in stations]),
        )
    ).all()} if stations else {}
    return LinePublic(
        id=line.id, workshop_id=line.workshop_id, code=line.code, name=line.name,
        created_at=line.created_at,
        layout=line.layout, station_count=line.station_count, numbering_mode=line.numbering_mode,
        stations=[
            StationPublic.model_validate(station).model_copy(update={
                "terminal_code": terminals[station.id].serial_number if station.id in terminals else None,
                "terminal_active": terminals[station.id].is_active if station.id in terminals else False,
            })
            for station in stations
        ],
    )


def _station_position(layout: str, position: int, count: int = 0, numbering_mode: str = "odd_even") -> tuple[int, int]:
    if layout == "single":
        return 1, position
    if numbering_mode == "sequential":
        width = (count + 1) // 2
        return (1, position) if position <= width else (2, position - width)
    return (1 if position % 2 else 2), (position + 1) // 2


def _apply_stations(uow: EsopTenantUowDep, line: ProductionLine, names: dict[int, str] | None = None) -> None:
    stations = {station.position: station for station in _stations(uow, line.id)}
    for position, station in stations.items():
        if position > line.station_count:
            uow.session.delete(station)
    for position in range(1, line.station_count + 1):
        row, column = _station_position(line.layout, position, line.station_count, line.numbering_mode)
        station = stations.get(position)
        if station is None:
            uow.session.add(Station(
                tenant_id=uow.tenant_id, line_id=line.id, position=position,
                row=row, column=column, name=(names or {}).get(position, "").strip(),
            ))
        else:
            station.row, station.column = row, column
            if names is not None and position in names:
                station.name = names[position].strip()
            uow.session.add(station)


@router.get(
    "/workshops", dependencies=[Depends(require_module_access("esop", "esop:workshop:list"))],
    response_model=ListWorkshops,
)
def list_workshops(uow: EsopTenantUowDep) -> ListWorkshops:
    rows = uow.session.exec(select(Workshop).order_by(Workshop.code)).all()
    return ListWorkshops(items=[WorkshopPublic.model_validate(row) for row in rows], total=len(rows))


@router.post(
    "/workshops", dependencies=[Depends(require_module_access("esop", "esop:workshop:create"))],
    response_model=WorkshopPublic,
)
def create_workshop(uow: EsopTenantUowDep, body: WorkshopInput) -> WorkshopPublic:
    body.code = body.code or generate_entity_code("WS")
    row = Workshop(tenant_id=uow.tenant_id, **body.model_dump())
    uow.session.add(row)
    _commit(uow)
    return WorkshopPublic.model_validate(row)


@router.put(
    "/workshops/{id}", dependencies=[Depends(require_module_access("esop", "esop:workshop:update"))],
    response_model=WorkshopPublic,
)
def update_workshop(uow: EsopTenantUowDep, id: uuid.UUID, body: WorkshopInput) -> WorkshopPublic:
    row = _owned(uow, Workshop, id)
    row.code, row.name = body.code or row.code, body.name
    uow.session.add(row)
    _commit(uow)
    return WorkshopPublic.model_validate(row)


@router.delete(
    "/workshops/{id}", status_code=204,
    dependencies=[Depends(require_module_access("esop", "esop:workshop:delete"))],
)
def delete_workshop(uow: EsopTenantUowDep, id: uuid.UUID) -> None:
    row = _owned(uow, Workshop, id)
    if uow.session.exec(
        select(ProductionLine.id).where(ProductionLine.workshop_id == row.id).limit(1).with_for_update()
    ).first() is not None:
        raise HTTPException(status_code=409, detail="该车间下已有产线，请先迁移产线后再删除")
    uow.session.delete(row)
    _commit(uow)


@router.get(
    "/lines", dependencies=[Depends(require_module_access("esop", "esop:line:list"))],
    response_model=ListLines,
)
def list_lines(uow: EsopTenantUowDep, workshop_id: uuid.UUID | None = None) -> ListLines:
    statement = select(ProductionLine)
    if workshop_id:
        statement = statement.where(ProductionLine.workshop_id == workshop_id)
    rows = uow.session.exec(statement.order_by(ProductionLine.code)).all()
    return ListLines(items=[_line_public(uow, row) for row in rows], total=len(rows))


@router.post(
    "/lines", dependencies=[Depends(require_module_access("esop", "esop:line:create"))],
    response_model=LinePublic,
)
def create_line(uow: EsopTenantUowDep, body: LineInput) -> LinePublic:
    _owned(uow, Workshop, body.workshop_id)
    body.code = body.code or generate_entity_code("LINE")
    row = ProductionLine(tenant_id=uow.tenant_id, **body.model_dump(exclude={"station_names", "numbering_mode"}),
                         numbering_mode=body.numbering_mode or "odd_even")
    uow.session.add(row)
    _apply_stations(uow, row, body.station_names)
    _commit(uow)
    return _line_public(uow, row)


@router.put(
    "/lines/{id}", dependencies=[Depends(require_module_access("esop", "esop:line:update"))],
    response_model=LinePublic,
)
def update_line(uow: EsopTenantUowDep, id: uuid.UUID, body: LineInput) -> LinePublic:
    _owned(uow, Workshop, body.workshop_id)
    row = _owned(uow, ProductionLine, id)
    numbering_mode = body.numbering_mode or row.numbering_mode
    geometry_changed = (body.layout != row.layout or body.station_count != row.station_count
                        or numbering_mode != row.numbering_mode)
    if body.layout != row.layout or body.station_count != row.station_count:
        station_ids = {str(station.id) for station in _stations(uow, row.id)}
        if any(plan.line_id == row.id or any(
            str(item.get("station_id")) in station_ids for item in plan.assignments
        ) for plan in uow.session.exec(select(ProductionPlan)).all()):
            raise HTTPException(status_code=409, detail="该产线工位已用于排产，无法修改布局或工位总数；仍可修改工位名称")
    row.workshop_id, row.code, row.name = body.workshop_id, body.code or row.code, body.name
    row.layout, row.station_count, row.numbering_mode = body.layout, body.station_count, numbering_mode
    uow.session.add(row)
    if geometry_changed or body.station_names is not None:
        _apply_stations(uow, row, body.station_names)
    _commit(uow)
    return _line_public(uow, row)


@router.delete(
    "/lines/{id}", status_code=204,
    dependencies=[Depends(require_module_access("esop", "esop:line:delete"))],
)
def delete_line(uow: EsopTenantUowDep, id: uuid.UUID) -> None:
    line = _owned(uow, ProductionLine, id)
    stations = list(uow.session.exec(
        select(Station).where(Station.line_id == line.id).with_for_update()
    ).all())
    station_ids = {str(station.id) for station in stations}
    # JSON assignments can reference stations on a different primary line.
    for model, reason in (
        (ProductionPlan, "该产线或其工位仍被排产任务引用，删除会影响排产及历史记录，无法删除"),
        (WorkRelease, "该产线或其工位仍被发布记录引用，删除会影响发布及历史记录，无法删除"),
    ):
        for parent_id, assignments in uow.session.exec(
            select(model.line_id, model.assignments).with_for_update()
        ).all():
            if parent_id == line.id or any(
                str(item.get("station_id")) in station_ids or str(item.get("line_id")) == str(line.id)
                for item in assignments
            ):
                raise HTTPException(status_code=409, detail=reason)
    if station_ids:
        ids = [station.id for station in stations]
        for model, reason in (
            (Terminal, "该产线工位仍绑定终端，请先解绑终端后再删除"),
            (ProductionReport, "该产线工位仍有报工记录，删除会影响报工查询与追溯，无法删除"),
            (AlarmEvent, "该产线工位仍有报警记录，删除会影响历史追溯，无法删除"),
        ):
            if uow.session.exec(
                select(model.id).where(model.station_id.in_(ids)).limit(1).with_for_update()
            ).first() is not None:
                raise HTTPException(status_code=409, detail=reason)
    for station in stations:
        uow.session.delete(station)
    uow.session.delete(line)
    _commit(uow)


@router.get(
    "/orders", dependencies=[Depends(require_module_access("esop", "esop:order:list"))],
    response_model=ListOrders,
)
def list_orders(
    uow: EsopTenantUowDep, products: ProductDirectoryDep,
    keyword: str | None = None, product_id: uuid.UUID | None = None,
    is_published: bool | None = None, created_at_from: date | None = None,
    created_at_to: date | None = None, due_date_from: date | None = None,
    due_date_to: date | None = None, page: int | None = None, page_size: int = 20,
) -> ListOrders:
    filters = _order_filters(
        uow=uow, products=products, keyword=keyword, product_id=product_id,
        is_published=is_published, created_at_from=created_at_from,
        created_at_to=created_at_to, due_date_from=due_date_from,
        due_date_to=due_date_to,
    )
    total = uow.session.exec(select(func.count(ProductionOrder.id)).where(*filters)).one()
    statement = select(ProductionOrder).where(*filters).order_by(
        ProductionOrder.created_at.desc(), ProductionOrder.id.desc(),
    )
    if page is not None:
        page, page_size = normalize_pagination(page=page, page_size=page_size)
        statement = statement.offset((page - 1) * page_size).limit(page_size)
    rows = uow.session.exec(statement).all()
    published_ids = _published_order_ids(uow, [row.id for row in rows])
    return ListOrders(items=[_order_public(uow, row, published_ids) for row in rows], total=total)


def _order_filters(
    *, uow: EsopTenantUowDep, products: ProductDirectoryDep,
    keyword: str | None, product_id: uuid.UUID | None, is_published: bool | None,
    created_at_from: date | None, created_at_to: date | None,
    due_date_from: date | None, due_date_to: date | None,
) -> list:
    if created_at_from and created_at_to and created_at_to < created_at_from:
        raise HTTPException(status_code=422, detail="创建日期结束时间不能早于开始时间")
    if due_date_from and due_date_to and due_date_to < due_date_from:
        raise HTTPException(status_code=422, detail="交期结束日期不能早于开始日期")
    filters = [ProductionOrder.tenant_id == uow.tenant_id]
    if keyword and keyword.strip():
        term = keyword.strip().lower()
        pattern = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        matching_products = [item.id for item in products.tree()[1] if term in item.name.lower()]
        filters.append(or_(col(ProductionOrder.code).ilike(pattern, escape="\\"),
                           ProductionOrder.product_id.in_(matching_products)))
    if product_id:
        filters.append(ProductionOrder.product_id == product_id)
    if is_published is not None:
        published = select(ProductionPlan.id).where(
            ProductionPlan.tenant_id == uow.tenant_id,
            ProductionPlan.order_id == ProductionOrder.id,
            ProductionPlan.status.notin_(["draft", "cancelled"]),
        ).exists()
        filters.append(published if is_published else ~published)
    timezone = ZoneInfo("Asia/Shanghai")
    if created_at_from:
        start = datetime.combine(created_at_from, time.min, tzinfo=timezone).astimezone(UTC)
        filters.append(ProductionOrder.created_at >= start)
    if created_at_to:
        end = datetime.combine(created_at_to + timedelta(days=1), time.min, tzinfo=timezone).astimezone(UTC)
        filters.append(ProductionOrder.created_at < end)
    if due_date_from:
        filters.append(ProductionOrder.due_date >= due_date_from)
    if due_date_to:
        filters.append(ProductionOrder.due_date <= due_date_to)
    return filters


def _csv_value(value: object) -> object:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return f"'{value}"
    return value


@router.post(
    "/orders/export", dependencies=[Depends(require_module_access("esop", "esop:order:list"))],
    response_model=None,
)
def export_orders(
    uow: EsopTenantUowDep, products: ProductDirectoryDep, body: OrderExportInput,
    x_export_timezone: ExportTimezoneHeader = None,
) -> StreamingResponse:
    timezone = export_timezone(x_export_timezone)
    if len(set(body.ids)) != len(body.ids):
        raise HTTPException(status_code=422, detail="选中的订单不能重复")
    filters = _order_filters(
        uow=uow, products=products, keyword=body.keyword, product_id=body.product_id,
        is_published=body.is_published, created_at_from=body.created_at_from,
        created_at_to=body.created_at_to, due_date_from=body.due_date_from,
        due_date_to=body.due_date_to,
    )
    rows = uow.session.exec(select(ProductionOrder).where(
        *filters, ProductionOrder.id.in_(body.ids),
    )).all()
    if len(rows) != len(body.ids):
        raise HTTPException(status_code=422, detail="选中订单已变更或不属于当前筛选结果，请刷新后重新选择")
    by_id = {row.id: row for row in rows}
    names = {item.id: item.name for item in products.tree()[1]}
    for row in rows:
        if row.product_id not in names and (product := products.get(row.product_id)) is not None:
            names[row.product_id] = product.name
    published_ids = _published_order_ids(uow, [row.id for row in rows])
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["订单编号", "产品名称", "生产数量", "交期", "创建时间", "发布状态", "生产状态"])
    for id in body.ids:
        row = by_id[id]
        production_status = {
            "completed": "已完成", "in_progress": "生产中",
            "waiting": "待开工", "unplanned": "未排产",
        }[_order_production_status(uow, row, row.id in published_ids)]
        writer.writerow([
            _csv_value(row.code), _csv_value(names.get(row.product_id, "")),
            row.quantity, row.due_date.isoformat(),
            export_datetime(row.created_at, timezone),
            "已发布" if row.id in published_ids else "待发布",
            production_status,
        ])
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('生产订单.csv')}"},
    )


def _published_order_ids(uow: EsopTenantUowDep, order_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not order_ids:
        return set()
    return set(uow.session.exec(select(ProductionPlan.order_id).where(
        ProductionPlan.tenant_id == uow.tenant_id,
        ProductionPlan.order_id.in_(order_ids), ProductionPlan.status.notin_(["draft", "cancelled"]),
    )).all())


def _order_public(
    uow: EsopTenantUowDep, row: ProductionOrder,
    published_ids: set[uuid.UUID] | None = None,
) -> OrderPublic:
    result = OrderPublic.model_validate(row)
    if published_ids is not None:
        result.is_published = row.id in published_ids
    else:
        result.is_published = uow.session.exec(
            select(ProductionPlan.id).where(
                ProductionPlan.order_id == row.id, ProductionPlan.status.notin_(["draft", "cancelled"])
            )
        ).first() is not None
    result.production_status = _order_production_status(uow, row, result.is_published)
    return result


def _order_production_status(uow: EsopTenantUowDep, order: ProductionOrder, published: bool) -> str:
    from app.modules.esop.report_routes import _progress

    current = _progress(uow.session, order)
    reported = current.input_total + current.good_total + current.bad_total > 0
    if current.good_total >= order.quantity:
        if order.operation_ids is None:
            return "completed"
        totals = _order_operation_completed(uow, order)
        if all(totals.get(operation_id, 0) >= order.quantity for operation_id in order.operation_ids):
            return "completed"
    return "in_progress" if reported else "waiting" if published else "unplanned"


def _order_operation_completed(uow: EsopTenantUowDep, order: ProductionOrder) -> dict[str, int]:
    totals: dict[str, int] = {}
    plans = uow.session.exec(select(ProductionPlan).where(
        ProductionPlan.order_id == order.id, ProductionPlan.status != "cancelled",
    )).all()
    for plan in plans:
        release = uow.session.exec(select(WorkRelease).where(
            WorkRelease.plan_id == plan.id,
        ).order_by(WorkRelease.version.desc())).first()
        if release is None:
            continue
        reports = uow.session.exec(select(ProductionReport).where(
            ProductionReport.release_id == release.id, ProductionReport.is_deleted == False,  # noqa: E712
        )).all()
        for report in reports:
            operation_id = str(report.operation_id)
            totals[operation_id] = totals.get(operation_id, 0) + report.good_qty + report.defect_qty
    return totals


def _selected_order_operations(uow: EsopTenantUowDep, product_id: uuid.UUID,
                               version_id: uuid.UUID | None, operation_ids: list[uuid.UUID] | None
                               ) -> tuple[uuid.UUID, list[str]]:
    if version_id is None or not operation_ids:
        raise HTTPException(status_code=422, detail="请选择产品审核通过的工序")
    version = _owned(uow, ProductSopVersion, version_id)
    if version.product_id != product_id or version.status != "approved":
        raise HTTPException(status_code=422, detail="工序版本不属于该产品或尚未审核通过")
    approved = [operation.operation_id for operation in _version_operations(uow, version)]
    if len(set(operation_ids)) != len(operation_ids) or not set(operation_ids) <= set(approved):
        raise HTTPException(status_code=422, detail="所选工序不属于该产品审核版本")
    return version.id, [str(operation_id) for operation_id in approved if operation_id in operation_ids]


@router.post(
    "/orders", dependencies=[Depends(require_module_access("esop", "esop:order:create"))],
    response_model=OrderPublic,
)
def create_order(uow: EsopTenantUowDep, products: ProductDirectoryDep, body: OrderInput) -> OrderPublic:
    if not products.exists(body.product_id):
        raise HTTPException(status_code=422, detail="Product not found")
    body.code = body.code or generate_entity_code("MO")
    version_id, operation_ids = _selected_order_operations(
        uow, body.product_id, body.product_sop_version_id, body.operation_ids)
    row = ProductionOrder(tenant_id=uow.tenant_id, **body.model_dump(exclude={"operation_ids", "product_sop_version_id"}),
                          product_sop_version_id=version_id, operation_ids=operation_ids)
    uow.session.add(row)
    _commit(uow)
    return _order_public(uow, row)


@router.put(
    "/orders/{id}", dependencies=[Depends(require_module_access("esop", "esop:order:update"))],
    response_model=OrderPublic,
)
def update_order(
    uow: EsopTenantUowDep, products: ProductDirectoryDep, id: uuid.UUID, body: OrderInput
) -> OrderPublic:
    row = _owned(uow, ProductionOrder, id)
    if uow.session.exec(
        select(ProductionPlan.id).where(
            ProductionPlan.order_id == id, ProductionPlan.status != "draft"
        )
    ).first() is not None:
        raise HTTPException(status_code=409, detail="Published order cannot be edited")
    if not products.exists(body.product_id):
        raise HTTPException(status_code=422, detail="Product not found")
    if row.operation_ids is None and body.operation_ids is None and body.product_sop_version_id is None:
        version_id, operation_ids = None, None
    else:
        version_id, operation_ids = _selected_order_operations(
            uow, body.product_id, body.product_sop_version_id, body.operation_ids)
    for key, value in body.model_dump(exclude={"operation_ids", "product_sop_version_id"}).items():
        if key != "code" or value is not None:
            setattr(row, key, value)
    row.product_sop_version_id, row.operation_ids = version_id, operation_ids
    uow.session.add(row)
    _commit(uow)
    return _order_public(uow, row)


@router.post(
    "/orders/{id}/confirm-operations",
    dependencies=[Depends(require_module_access("esop", "esop:order:update"))], response_model=OrderPublic,
)
def confirm_order_operations(uow: EsopTenantUowDep, id: uuid.UUID, body: OrderOperationsInput) -> OrderPublic:
    row = _owned(uow, ProductionOrder, id)
    if row.operation_ids is not None:
        raise HTTPException(status_code=409, detail="该订单已确认工序")
    version_id, operation_ids = _selected_order_operations(
        uow, row.product_id, body.product_sop_version_id, body.operation_ids)
    plans = uow.session.exec(select(ProductionPlan).where(
        ProductionPlan.order_id == id, ProductionPlan.status.notin_(["draft", "cancelled"]),
    )).all()
    if any({str(item["operation_id"]) for item in plan.assignments} != set(operation_ids)
           for plan in plans):
        raise HTTPException(status_code=409, detail="有效排产工序与所选工序不一致，请逐单核对后再切换")
    row.product_sop_version_id, row.operation_ids = version_id, operation_ids
    uow.session.add(row)
    _commit(uow)
    return _order_public(uow, row)


@router.delete("/orders/{id}", dependencies=[Depends(require_module_access("esop", "esop:order:update"))])
def delete_order(uow: EsopTenantUowDep, id: uuid.UUID) -> dict[str, bool]:
    row = _owned(uow, ProductionOrder, id)
    for model in (ProductionPlan, WorkRelease, ProductionReport):
        if uow.session.exec(select(model.id).where(model.order_id == id)).first() is not None:
            raise HTTPException(status_code=409, detail="订单已有排产、发布或报工记录，不能删除")
    uow.session.delete(row)
    _commit(uow)
    return {"deleted": True}


def _approved_version(
    uow: EsopTenantUowDep, product_id: uuid.UUID, version_id: uuid.UUID | None
) -> ProductSopVersion:
    if version_id is not None:
        supplied = _owned(uow, ProductSopVersion, version_id)
        if supplied.product_id != product_id or supplied.status != "approved":
            raise HTTPException(status_code=422, detail="当前排产只能使用该产品的生效版本，请刷新后重新保存")
    version = uow.session.exec(
        select(ProductSopVersion).where(
            ProductSopVersion.product_id == product_id,
            ProductSopVersion.status == "approved",
        ).order_by(ProductSopVersion.version.desc())
    ).first()
    if version is None:
        raise HTTPException(status_code=422, detail="该产品尚无生效的完整工序版本，请先提交并完成审核")
    if version_id is not None and version_id != version.id:
        raise HTTPException(status_code=422, detail="当前排产只能使用该产品的生效版本，请刷新后重新保存")
    if not version.operations:
        raise HTTPException(status_code=422, detail="生效版本没有工序，无法排产")
    return version


def _version_operations(
    uow: EsopTenantUowDep, version: ProductSopVersion
) -> list[ApprovedProductOperation]:
    result = []
    for operation in version.operations:
        if not operation.get("sop_id"):
            raise HTTPException(status_code=422, detail="所选产品版本缺少审核指导书，请重新提交审核")
        sop = _owned(uow, SopDocument, uuid.UUID(str(operation["sop_id"])))
        operation_id = uuid.UUID(str(operation["id"]))
        if sop.product_id != version.product_id or sop.operation_id != operation_id or sop.status != "approved":
            raise HTTPException(status_code=422, detail="产品版本的指导书关联不一致，无法发布")
        result.append(ApprovedProductOperation(
            operation_id=operation_id, code=str(operation["code"]), name=str(operation["name"]),
            sop_id=sop.id, sop_title=sop.title, sop_version=sop.version,
        ))
    return result


@router.get(
    "/products/{product_id}/approved-versions",
    dependencies=[Depends(require_any_module_access("esop", ("esop:plan:list", "esop:order:create", "esop:order:update")))],
    response_model=ApprovedProductVersions,
)
def approved_product_versions(uow: EsopTenantUowDep, product_id: uuid.UUID) -> ApprovedProductVersions:
    version = uow.session.exec(select(ProductSopVersion).where(
        ProductSopVersion.product_id == product_id, ProductSopVersion.status == "approved",
    ).order_by(ProductSopVersion.version.desc())).first()
    return ApprovedProductVersions(
        items=[ApprovedProductVersionSummary.model_validate(version)] if version else [], total=1 if version else 0,
    )


@router.get(
    "/products/{product_id}/approved-operations",
    dependencies=[Depends(require_any_module_access("esop", ("esop:plan:list", "esop:order:create", "esop:order:update")))],
    response_model=ApprovedProductOperations,
)
def approved_product_operations(
    uow: EsopTenantUowDep, product_id: uuid.UUID, version_id: uuid.UUID | None = None,
) -> ApprovedProductOperations:
    version = _approved_version(uow, product_id, version_id)
    return ApprovedProductOperations(
        product_id=product_id, product_sop_version_id=version.id, version=version.version,
        operations=_version_operations(uow, version),
    )


@router.get(
    "/orders/{id}/operations",
    dependencies=[Depends(require_any_module_access("esop", ("esop:plan:list", "esop:order:update")))],
    response_model=ApprovedProductOperations,
)
def order_operations(uow: EsopTenantUowDep, id: uuid.UUID) -> ApprovedProductOperations:
    order = _owned(uow, ProductionOrder, id)
    if order.product_sop_version_id is not None:
        version = _owned(uow, ProductSopVersion, order.product_sop_version_id)
    else:
        plan = uow.session.exec(select(ProductionPlan).where(
            ProductionPlan.order_id == id, ProductionPlan.status != "cancelled",
        ).order_by(ProductionPlan.created_at.desc())).first()
        version = (_owned(uow, ProductSopVersion, plan.product_sop_version_id)
                   if plan and plan.product_sop_version_id else _approved_version(uow, order.product_id, None))
    if version.product_id != order.product_id or version.status != "approved":
        raise HTTPException(status_code=422, detail="订单工序版本已失效，请联系管理员")
    operations = _version_operations(uow, version)
    if order.operation_ids is not None:
        operations = [operation for operation in operations if str(operation.operation_id) in order.operation_ids]
    return ApprovedProductOperations(
        product_id=order.product_id, product_sop_version_id=version.id,
        version=version.version, operations=operations,
    )


def _validate_assignments(
    uow: EsopTenantUowDep, body: PlanInput, *, complete: bool
) -> list[dict[str, object]]:
    order = _owned(uow, ProductionOrder, body.order_id)
    line_ids = {body.line_id}
    if body.assignments:
        line_ids.update(uow.session.exec(
            select(Station.line_id).where(Station.id.in_([item.station_id for item in body.assignments]))
        ).all())
    uow.session.exec(
        select(ProductionLine.id).where(ProductionLine.id.in_(line_ids))
        .order_by(ProductionLine.id).with_for_update()
    ).all()
    _owned(uow, ProductionLine, body.line_id)
    lock_product(uow, order.product_id)
    if order.product_sop_version_id is not None:
        version = _owned(uow, ProductSopVersion, order.product_sop_version_id)
        if body.product_sop_version_id not in (None, version.id):
            raise HTTPException(status_code=422, detail="排产必须使用订单固定的工序版本")
        if version.product_id != order.product_id or version.status != "approved":
            raise HTTPException(status_code=422, detail="订单固定的工序版本已失效")
    else:
        version = _approved_version(uow, order.product_id, body.product_sop_version_id)
    body.product_sop_version_id = version.id
    approved_operations = _version_operations(uow, version)
    operation_order = [operation.operation_id for operation in approved_operations]
    by_operation = {operation.operation_id: operation for operation in approved_operations}
    assigned_operations = [item.operation_id for item in body.assignments]
    if len({item.station_id for item in body.assignments}) != len(body.assignments):
        raise HTTPException(status_code=422, detail="一个工位只能分配一道工序")
    allowed_operations = set(order.operation_ids) if order.operation_ids is not None else {str(value) for value in operation_order}
    if not {str(value) for value in assigned_operations} <= allowed_operations:
        raise HTTPException(status_code=422, detail="排产包含不属于当前产品的工序")
    if complete and not assigned_operations:
        raise HTTPException(status_code=422, detail="请至少为一道工序分配工位")
    if complete:
        station_ids = [item.station_id for item in body.assignments]
        bound = set(uow.session.exec(select(Terminal.station_id).where(
            Terminal.station_id.in_(station_ids), Terminal.is_active == True,  # noqa: E712
        )).all())
        if any(station_id not in bound for station_id in station_ids):
            raise HTTPException(status_code=422, detail="有工位未绑定启用的终端，请先绑定终端或移除该工位工序")
    snapshot: list[dict[str, object]] = []
    for item in body.assignments:
        operation = by_operation[item.operation_id]
        if item.sop_id != operation.sop_id:
            old_sop = uow.session.get(SopDocument, item.sop_id)
            if old_sop is None or old_sop.tenant_id != uow.tenant_id:
                raise HTTPException(status_code=422, detail="指导书不属于所选产品工序")
            if old_sop.product_id != order.product_id or old_sop.operation_id != item.operation_id:
                raise HTTPException(status_code=422, detail="指导书不属于所选产品工序")
        station = _owned(uow, Station, item.station_id)
        _owned(uow, ProductionLine, station.line_id)
        snapshot.append({
            **item.model_dump(mode="json"), "sop_id": str(operation.sop_id),
            "line_id": str(station.line_id),
            "operation_name": operation.name,
            "station_position": station.position,
            "station_row": station.row,
            "station_column": station.column,
            "sop_title": operation.sop_title, "sop_version": operation.sop_version,
        })
    order_index = {operation_id: index for index, operation_id in enumerate(operation_order)}
    return sorted(snapshot, key=lambda item: order_index[uuid.UUID(str(item["operation_id"]))])


def _check_window(start_at: datetime | None, end_at: datetime | None) -> None:
    for value in (start_at, end_at):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise HTTPException(status_code=422, detail="排产时间必须包含时区")
    if start_at and end_at and start_at >= end_at:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")


def _require_order_capacity(
    uow: EsopTenantUowDep, order_id: uuid.UUID, quantity: int,
    *, operation_ids: set[str] | None = None, exclude_plan_id: uuid.UUID | None = None,
) -> ProductionOrder:
    order = uow.session.exec(select(ProductionOrder).where(
        ProductionOrder.id == order_id,
    ).with_for_update()).first()
    if order is None or order.tenant_id != uow.tenant_id:
        raise HTTPException(status_code=404, detail="生产订单不存在")
    allocations, approved = _order_operation_allocation(uow, order_id, exclude_plan_id=exclude_plan_id, for_update=True)
    selected = operation_ids if operation_ids is not None else set(order.operation_ids or allocations)
    remaining = min((max(0, order.quantity + approved - allocations.get(operation_id, 0))
                     for operation_id in selected), default=order.quantity + approved)
    if selected and quantity > remaining:
        raise HTTPException(
            status_code=409,
            detail=f"所选工序剩余可排数量为 {remaining}，不能重复排产",
        )
    return order


def _order_operation_allocation(
    uow: EsopTenantUowDep, order_id: uuid.UUID, *, exclude_plan_id: uuid.UUID | None = None,
    for_update: bool = False,
) -> tuple[dict[str, int], int]:
    plan_query = select(ProductionPlan).where(
        ProductionPlan.order_id == order_id, ProductionPlan.status != "cancelled",
    )
    plans = uow.session.exec(plan_query.with_for_update() if for_update else plan_query).all()
    allocated: dict[str, int] = {}
    for plan in plans:
        if plan.id == exclude_plan_id:
            continue
        operation_ids = {str(item["operation_id"]) for item in plan.assignments}
        if not operation_ids:
            continue
        reported_good: dict[str, int] = {}
        release_query = select(WorkRelease).where(
            WorkRelease.plan_id == plan.id,
        ).order_by(WorkRelease.version.desc())
        release = uow.session.exec(release_query.with_for_update() if for_update else release_query).first()
        if release:
            report_query = select(ProductionReport).where(
                ProductionReport.release_id == release.id,
                ProductionReport.is_deleted == False,  # noqa: E712
            )
            reports = uow.session.exec(report_query.with_for_update() if for_update else report_query).all()
            for report in reports:
                key = str(report.operation_id)
                reported_good[key] = reported_good.get(key, 0) + report.good_qty
        for operation_id in operation_ids:
            allocated[operation_id] = allocated.get(operation_id, 0) + max(
                plan.quantity, reported_good.get(operation_id, 0))
    supplement_query = select(ProductionOrderSupplement.quantity).where(
        ProductionOrderSupplement.order_id == order_id,
        ProductionOrderSupplement.status == "approved",
    )
    approved = sum(uow.session.exec(supplement_query.with_for_update() if for_update else supplement_query).all())
    return allocated, approved


@router.get(
    "/orders/{id}/allocation",
    dependencies=[Depends(require_module_access("esop", "esop:plan:list"))],
    response_model=OrderAllocationPublic,
)
def order_allocation(uow: EsopTenantUowDep, id: uuid.UUID) -> OrderAllocationPublic:
    order = _owned(uow, ProductionOrder, id)
    allocations, approved = _order_operation_allocation(uow, id)
    allocated = max(allocations.values(), default=0)
    plans = uow.session.exec(select(ProductionPlan).where(
        ProductionPlan.order_id == id, ProductionPlan.status != "cancelled",
    )).all()
    return OrderAllocationPublic(
        order_quantity=order.quantity, allocated_quantity=allocated,
        approved_supplement_quantity=approved,
        remaining_quantity=max(0, order.quantity + approved - allocated),
        operations=[{
            "operation_id": operation_id,
            "allocated_quantity": allocations.get(operation_id, 0),
            "remaining_quantity": max(0, order.quantity + approved - allocations.get(operation_id, 0)),
            "plan_codes": [plan.code for plan in plans if any(
                str(item["operation_id"]) == operation_id for item in plan.assignments)],
        } for operation_id in (order.operation_ids or allocations.keys())],
    )


def _supplement_remaining(uow: EsopTenantUowDep, order: ProductionOrder) -> int:
    plans = uow.session.exec(select(ProductionPlan).where(
        ProductionPlan.order_id == order.id, ProductionPlan.status != "cancelled",
    )).all()
    if not plans or any(plan.status != "completed" for plan in plans):
        raise HTTPException(status_code=409, detail="请等待该订单所有排产完成或作废后再申请补排")
    allocations, approved = _order_operation_allocation(uow, order.id, for_update=True)
    if any(allocations.get(operation_id, 0) < order.quantity for operation_id in (order.operation_ids or allocations)):
        raise HTTPException(status_code=409, detail="订单尚有普通可排数量，无需申请补排")
    from app.modules.esop.report_routes import _progress
    good = _progress(uow.session, order).good_total
    allocated = max(allocations.values(), default=0)
    unused_approved = max(0, order.quantity + approved - allocated)
    return max(0, order.quantity - good - unused_approved)


@router.get(
    "/order-supplements",
    dependencies=[Depends(require_module_access("esop", "esop:plan:list"))],
    response_model=ListSupplements,
)
def list_order_supplements(uow: EsopTenantUowDep, order_id: uuid.UUID) -> ListSupplements:
    _owned(uow, ProductionOrder, order_id)
    rows = uow.session.exec(select(ProductionOrderSupplement).where(
        ProductionOrderSupplement.order_id == order_id,
    ).order_by(ProductionOrderSupplement.created_at.desc())).all()
    return ListSupplements(items=[SupplementPublic.model_validate(row) for row in rows], total=len(rows))


@router.post(
    "/order-supplements",
    dependencies=[Depends(require_module_access("esop", "esop:plan:create"))],
    response_model=SupplementPublic,
)
def create_order_supplement(
    uow: EsopTenantUowDep, body: SupplementInput,
    current_principal: CurrentPrincipal, users: UserDirectoryDep,
) -> SupplementPublic:
    if not (current_principal.is_superuser or users.can_correct_production_reports(current_principal.id, uow.tenant_id)):
        raise HTTPException(status_code=403, detail="仅经理及以上岗位可申请补排")
    order = _require_order_capacity(uow, body.order_id, 0)
    pending = uow.session.exec(select(ProductionOrderSupplement.id).where(
        ProductionOrderSupplement.order_id == order.id,
        ProductionOrderSupplement.status == "pending",
    )).first()
    if pending:
        raise HTTPException(status_code=409, detail="该订单已有待审核补排申请")
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="请填写补排原因")
    remaining = _supplement_remaining(uow, order)
    if body.quantity > remaining:
        raise HTTPException(status_code=409, detail=f"最多可申请补排 {remaining}，请核对良品缺口")
    row = ProductionOrderSupplement(
        tenant_id=uow.tenant_id, order_id=order.id, quantity=body.quantity,
        reason=body.reason.strip(), requested_by=current_principal.id,
    )
    uow.session.add(row)
    _commit(uow)
    return SupplementPublic.model_validate(row)


@router.post(
    "/order-supplements/{id}/review",
    dependencies=[Depends(require_module_access("esop", "esop:plan:publish"))],
    response_model=SupplementPublic,
)
def review_order_supplement(
    uow: EsopTenantUowDep, id: uuid.UUID, body: SupplementReview,
    current_principal: CurrentPrincipal, users: UserDirectoryDep,
) -> SupplementPublic:
    if not (current_principal.is_superuser or users.is_tenant_administrator(current_principal.id, uow.tenant_id)):
        raise HTTPException(status_code=403, detail="仅租户管理员可审核补排申请")
    row = uow.session.exec(select(ProductionOrderSupplement).where(
        ProductionOrderSupplement.id == id,
    ).with_for_update()).first()
    if row is None or row.tenant_id != uow.tenant_id:
        raise HTTPException(status_code=404, detail="补排申请不存在")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="补排申请已审核")
    order = _require_order_capacity(uow, row.order_id, 0)
    if body.approve:
        remaining = _supplement_remaining(uow, order)
        if row.quantity > remaining:
            raise HTTPException(status_code=409, detail=f"良品缺口已变化，最多可批准 {remaining}")
    elif not body.note:
        raise HTTPException(status_code=422, detail="退回时请填写原因")
    row.status = "approved" if body.approve else "rejected"
    row.reviewed_by = current_principal.id
    row.reviewed_at = get_datetime_utc()
    row.review_note = body.note
    uow.session.add(row)
    _commit(uow)
    return SupplementPublic.model_validate(row)


def _plan_public(uow: EsopTenantUowDep, row: ProductionPlan) -> PlanPublic:
    public = PlanPublic.model_validate(row)
    if row.product_sop_version_id:
        public.product_sop_version = _owned(uow, ProductSopVersion, row.product_sop_version_id).version
    releases = uow.session.exec(select(WorkRelease).where(WorkRelease.plan_id == row.id)).all()
    if releases:
        release = max(releases, key=lambda item: item.version)
        reports = uow.session.exec(select(ProductionReport).where(
            ProductionReport.release_id == release.id, ProductionReport.is_deleted == False,  # noqa: E712
        )).all()
        public.input_total, public.good_total, public.bad_total, public.completion_rate = _plan_metrics(
            release.assignments, reports, release.quantity,
        )
    return public


def _plan_metrics(assignments: list, reports: list, quantity: int) -> tuple[int, int, int, float]:
    operations = list(dict.fromkeys(str(item["operation_id"]) for item in assignments))
    if not operations or quantity <= 0:
        return 0, 0, 0, 0.0
    totals = {operation: [0, 0, 0] for operation in operations}
    for report in reports:
        if getattr(report, "is_deleted", False):
            continue
        values = totals.get(str(report.operation_id))
        if values is not None:
            values[0] += report.input_qty
            values[1] += report.good_qty
            values[2] += report.defect_qty
    completion = min(100.0, min((values[1] + values[2]) / quantity * 100 for values in totals.values()))
    return totals[operations[0]][0], totals[operations[-1]][1], totals[operations[-1]][2], round(completion, 1)


def _group_public(uow: EsopTenantUowDep, row: ProductionPlanGroup) -> PlanGroupPublic:
    plans = uow.session.exec(select(ProductionPlan).where(
        ProductionPlan.group_id == row.id,
    ).order_by(ProductionPlan.group_position)).all()
    return PlanGroupPublic(
        id=row.id, name=row.name, start_at=row.start_at, is_paused=row.is_paused, switch_mode=row.switch_mode,
        created_at=row.created_at,
        plan_ids=[item.id for item in plans],
    )


@router.get("/plan-groups", dependencies=[Depends(require_module_access("esop", "esop:plan:list"))], response_model=ListPlanGroups)
def list_plan_groups(uow: EsopTenantUowDep) -> ListPlanGroups:
    rows = uow.session.exec(select(ProductionPlanGroup).order_by(ProductionPlanGroup.created_at.desc())).all()
    return ListPlanGroups(items=[_group_public(uow, row) for row in rows], total=len(rows))


def _save_group(uow: EsopTenantUowDep, row: ProductionPlanGroup, body: PlanGroupInput) -> PlanGroupPublic:
    _check_window(body.start_at, None)
    if len(body.plan_ids) != len(set(body.plan_ids)):
        raise HTTPException(status_code=422, detail="任务组不能重复加入同一排产")
    current = uow.session.exec(select(ProductionPlan).where(ProductionPlan.group_id == row.id).with_for_update()).all()
    selected = [_owned(uow, ProductionPlan, id) for id in body.plan_ids]
    if row.switch_mode == "independent" and body.switch_mode == "together" and any(item.status in {"published", "paused", "expired"} for item in current):
        raise HTTPException(status_code=409, detail="独立切换的任务仍在运行，完成后才能改为一起切换")
    if any(item.group_id not in (None, row.id) for item in selected):
        raise HTTPException(status_code=409, detail="排产已加入其他任务组")
    if any(item.status != "draft" and item.group_id != row.id for item in selected):
        raise HTTPException(status_code=409, detail="只能将未启动的排产加入任务组")
    # Running and completed positions are fixed. Only pending items may be reordered.
    fixed = [item.id for item in current if item.status != "draft" and item.id in body.plan_ids]
    if [id for id in body.plan_ids if id in fixed] != fixed or any(
        body.plan_ids.index(item.id) != item.group_position for item in current
        if item.id in fixed
    ):
        raise HTTPException(status_code=409, detail="已运行排产的顺序不能调整")
    removing_running = any(item.status == "published" and item.id not in body.plan_ids for item in current)
    if removing_running and row.switch_mode == "independent":
        raise HTTPException(status_code=409, detail="独立切换运行中的排产暂不能移出任务组")
    for item in current:
        if item.id not in body.plan_ids:
            item.group_id = item.group_position = None
            uow.session.add(item)
    for position, item in enumerate(selected):
        item.group_id, item.group_position = row.id, position
        uow.session.add(item)
    row.name = body.name.strip()
    row.switch_mode = body.switch_mode
    row.start_at = body.start_at
    if removing_running:
        row.is_paused = True
    uow.session.add(row)
    _commit(uow)
    return _group_public(uow, row)


@router.post("/plan-groups", dependencies=[Depends(require_module_access("esop", "esop:plan:create"))], response_model=PlanGroupPublic)
def create_plan_group(uow: EsopTenantUowDep, current_principal: CurrentPrincipal, body: PlanGroupInput) -> PlanGroupPublic:
    row = ProductionPlanGroup(
        tenant_id=uow.tenant_id, name=body.name.strip(), created_by=current_principal.id,
        is_paused=body.start_at is None,
    )
    return _save_group(uow, row, body)


@router.put("/plan-groups/{id}", dependencies=[Depends(require_module_access("esop", "esop:plan:update"))], response_model=PlanGroupPublic)
def update_plan_group(uow: EsopTenantUowDep, id: uuid.UUID, body: PlanGroupInput) -> PlanGroupPublic:
    return _save_group(uow, _owned(uow, ProductionPlanGroup, id), body)


@router.delete("/plan-groups/{id}", dependencies=[Depends(require_module_access("esop", "esop:plan:update"))])
def delete_plan_group(uow: EsopTenantUowDep, id: uuid.UUID) -> dict[str, bool]:
    row = _owned(uow, ProductionPlanGroup, id)
    if row.switch_mode == "independent" and uow.session.exec(select(ProductionPlan).where(
        ProductionPlan.group_id == id, ProductionPlan.status.in_(["published", "paused", "expired"]),
    )).first():
        raise HTTPException(status_code=409, detail="独立切换的任务仍在运行，完成后才能删除任务组")
    for plan in uow.session.exec(select(ProductionPlan).where(ProductionPlan.group_id == id)).all():
        plan.group_id = plan.group_position = None
        uow.session.add(plan)
    uow.session.delete(row)
    _commit(uow)
    return {"ok": True}


@router.post("/plan-groups/{id}/pause", dependencies=[Depends(require_module_access("esop", "esop:plan:update"))], response_model=PlanGroupPublic)
def pause_plan_group(uow: EsopTenantUowDep, id: uuid.UUID) -> PlanGroupPublic:
    row = _owned(uow, ProductionPlanGroup, id)
    if row.is_paused:
        raise HTTPException(status_code=409, detail="任务组已暂停")
    active = uow.session.exec(select(ProductionPlan.id).where(
        ProductionPlan.group_id == id, ProductionPlan.tenant_id == uow.tenant_id,
        ProductionPlan.status.in_(["draft", "published", "paused"]),
    )).first()
    if active is None:
        raise HTTPException(status_code=409, detail="任务组没有可暂停的排产")
    row.is_paused = True
    uow.session.add(row)
    _commit(uow)
    return _group_public(uow, row)


@router.post("/plan-groups/{id}/resume", dependencies=[Depends(require_module_access("esop", "esop:plan:update"))], response_model=PlanGroupPublic)
def resume_plan_group(uow: EsopTenantUowDep, id: uuid.UUID) -> PlanGroupPublic:
    row = _owned(uow, ProductionPlanGroup, id)
    row.is_paused = False
    uow.session.add(row)
    _commit(uow)
    return _group_public(uow, row)


@router.post("/plan-groups/{id}/start-now", dependencies=[Depends(require_module_access("esop", "esop:plan:publish"))], response_model=PlanGroupPublic)
def start_now_plan_group(uow: EsopTenantUowDep, id: uuid.UUID, current_principal: CurrentPrincipal) -> PlanGroupPublic:
    from app.modules.esop.plan_scheduler import start_plan

    group = _owned(uow, ProductionPlanGroup, id)
    queue = uow.session.exec(select(ProductionPlan).where(
        ProductionPlan.group_id == id,
    ).order_by(ProductionPlan.group_position).with_for_update()).all()
    if any(plan.status == "expired" for plan in queue):
        raise HTTPException(status_code=409, detail="任务组有到期未完成任务")
    running = next((plan for plan in queue if plan.status == "published"), None)
    paused = next((plan for plan in queue if plan.status == "paused"), None)
    if running and not group.is_paused:
        raise HTTPException(status_code=409, detail="任务组已有运行中的排产")
    next_plan = next((plan for plan in queue if plan.status == "draft"), None)
    if not running and not paused and next_plan is None:
        raise HTTPException(status_code=409, detail="任务组没有待启动排产")
    group.is_paused = False
    group.start_at = get_datetime_utc()
    uow.session.add(group)
    uow.session.flush()
    if paused:
        _resume_plan(uow, paused)
    elif not running and next_plan:
        start_plan(uow.session, next_plan, current_principal.id, uow=uow, ignore_start_time=True)
    _commit(uow)
    return _group_public(uow, group)


def _release_public(uow: EsopTenantUowDep, row: WorkRelease) -> ReleasePublic:
    public = ReleasePublic.model_validate(row)
    if row.product_sop_version_id:
        public.product_sop_version = _owned(uow, ProductSopVersion, row.product_sop_version_id).version
    return public


@router.get(
    "/plans", dependencies=[Depends(require_module_access("esop", "esop:plan:list"))],
    response_model=ListPlans,
)
def list_plans(
    uow: EsopTenantUowDep, order_id: uuid.UUID | None = None, page: int | None = None,
    page_size: int = 20, keyword: str | None = None,
    status: Literal["draft", "published", "paused", "expired", "completed", "cancelled"] | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> ListPlans:
    from app.modules.esop.plan_scheduler import advance_due_plans
    advance_due_plans(uow.session)
    filters = [ProductionPlan.tenant_id == uow.tenant_id]
    if order_id:
        filters.append(ProductionPlan.order_id == order_id)
    if status:
        filters.append(ProductionPlan.status == status)
    if created_from is not None:
        filters.append(ProductionPlan.created_at >= created_from)
    if created_to is not None:
        filters.append(ProductionPlan.created_at <= created_to)
    if keyword and keyword.strip():
        term = keyword.strip()
        matching_orders = select(ProductionOrder.id).where(
            ProductionOrder.tenant_id == uow.tenant_id,
            ProductionOrder.code.contains(term),
        )
        filters.append(or_(ProductionPlan.code.contains(term), ProductionPlan.order_id.in_(matching_orders)))
    total = uow.session.exec(select(func.count(ProductionPlan.id)).where(*filters)).one()
    statement = select(ProductionPlan).where(*filters).order_by(
        ProductionPlan.created_at.desc(), ProductionPlan.id.desc(),
    )
    if page is not None:
        page, page_size = normalize_pagination(page=page, page_size=page_size)
        statement = statement.offset((page - 1) * page_size).limit(page_size)
    rows = uow.session.exec(statement).all()
    return ListPlans(items=[_plan_public(uow, row) for row in rows], total=total)


@router.get(
    "/plans/{id}", dependencies=[Depends(require_module_access("esop", "esop:plan:list"))],
    response_model=PlanPublic,
)
def read_plan(uow: EsopTenantUowDep, id: uuid.UUID) -> PlanPublic:
    return _plan_public(uow, _owned(uow, ProductionPlan, id))


@router.get(
    "/plans/{id}/release", dependencies=[Depends(require_module_access("esop", "esop:plan:list"))],
    response_model=ReleasePublic,
)
def read_plan_release(uow: EsopTenantUowDep, id: uuid.UUID) -> ReleasePublic:
    _owned(uow, ProductionPlan, id)
    release = uow.session.exec(select(WorkRelease).where(WorkRelease.plan_id == id)).first()
    if release is None:
        raise HTTPException(status_code=404, detail="排产尚未发布")
    return _release_public(uow, release)


@router.get(
    "/plans/{id}/task", dependencies=[Depends(require_module_access("esop", "esop:plan:list"))],
    response_model=PlanTaskDetail,
)
def read_plan_task(uow: EsopTenantUowDep, id: uuid.UUID) -> PlanTaskDetail:
    plan = _owned(uow, ProductionPlan, id)
    release = uow.session.exec(select(WorkRelease).where(WorkRelease.plan_id == id)).first()
    if release is None:
        raise HTTPException(status_code=404, detail="排产尚未发布")
    reports = uow.session.exec(select(ProductionReport).where(
        ProductionReport.release_id == release.id, ProductionReport.is_deleted == False,  # noqa: E712
    )).all()
    assigned = {(str(item["operation_id"]), str(item["station_id"])): item for item in release.assignments}
    operation_ids = list(dict.fromkeys(
        [str(item["operation_id"]) for item in release.assignments]
        + [str(report.operation_id) for report in reports]
    ))
    station_ids = {uuid.UUID(station_id) for _, station_id in assigned}
    station_ids.update(report.station_id for report in reports)
    stations = {station.id: station for station in uow.session.exec(select(Station).where(Station.id.in_(station_ids))).all()}
    terminals = {terminal.station_id: terminal for terminal in uow.session.exec(select(Terminal).where(
        Terminal.station_id.in_(station_ids),
    ).order_by(Terminal.is_active)).all()}
    operations = []
    for operation_id in operation_ids:
        operation_assignments = [item for item in release.assignments if str(item["operation_id"]) == operation_id]
        operation_reports = [report for report in reports if str(report.operation_id) == operation_id]
        operation_station_ids = list(dict.fromkeys(
            [str(item["station_id"]) for item in operation_assignments]
            + [str(report.station_id) for report in operation_reports]
        ))
        station_progress = []
        for station_id in operation_station_ids:
            station_reports = [report for report in operation_reports if str(report.station_id) == station_id]
            station = stations.get(uuid.UUID(station_id))
            terminal = terminals.get(uuid.UUID(station_id))
            station_progress.append(PlanStationProgress(
                station_id=uuid.UUID(station_id),
                station_name=(station.name or f"{station.position} 号工位") if station else "历史工位",
                station_position=station.position if station else (station_reports[0].station_position if station_reports else 0),
                terminal_code=terminal.serial_number if terminal else None,
                terminal_active=terminal.is_active if terminal else False,
                is_assigned=(operation_id, station_id) in assigned,
                input_total=sum(report.input_qty for report in station_reports),
                good_total=sum(report.good_qty for report in station_reports),
                bad_total=sum(report.defect_qty for report in station_reports),
                last_report_at=max((report.occurred_at for report in station_reports), default=None),
            ))
        good = sum(report.good_qty for report in operation_reports)
        bad = sum(report.defect_qty for report in operation_reports)
        completed = good + bad
        operations.append(PlanOperationProgress(
            operation_id=uuid.UUID(operation_id),
            operation_name=str(operation_assignments[0].get("operation_name") or "工序") if operation_assignments else "已移除工序",
            is_assigned=bool(operation_assignments),
            input_total=sum(report.input_qty for report in operation_reports),
            good_total=good, bad_total=bad, completed_total=completed,
            remaining_qty=max(0, release.quantity - completed),
            completion_rate=round(min(100, completed / release.quantity * 100), 1),
            stations=station_progress,
        ))
    return PlanTaskDetail(plan=_plan_public(uow, plan), release=_release_public(uow, release), operations=operations)


@router.delete(
    "/plans/{id}/assignments/{station_id}",
    dependencies=[Depends(require_module_access("esop", "esop:plan:publish"))],
    response_model=PlanTaskDetail,
)
def remove_unbound_plan_station(uow: EsopTenantUowDep, id: uuid.UUID, station_id: uuid.UUID) -> PlanTaskDetail:
    plan = _owned(uow, ProductionPlan, id)
    if plan.status not in {"published", "paused"}:
        raise HTTPException(status_code=409, detail="仅运行中或已暂停的排产可调整工位")
    release = uow.session.exec(select(WorkRelease).where(WorkRelease.plan_id == id).with_for_update()).first()
    if release is None or not any(str(item["station_id"]) == str(station_id) for item in release.assignments):
        raise HTTPException(status_code=404, detail="排产没有该工位分配")
    station = _owned(uow, Station, station_id)
    uow.session.exec(select(ProductionLine.id).where(ProductionLine.id == station.line_id).with_for_update()).first()
    if uow.session.exec(select(Terminal.id).where(
        Terminal.station_id == station_id, Terminal.is_active == True,  # noqa: E712
    )).first() is not None:
        raise HTTPException(status_code=409, detail="该工位已绑定启用的终端，不属于无终端工位")
    order = _owned(uow, ProductionOrder, plan.order_id)
    remaining_assignments = [item for item in release.assignments if str(item["station_id"]) != str(station_id)]
    if order.operation_ids is not None and any(
        operation_id not in {str(item["operation_id"]) for item in remaining_assignments}
        for operation_id in order.operation_ids
    ):
        raise HTTPException(status_code=409, detail="不能移除订单选定工序的最后一个工位")
    release.assignments = remaining_assignments
    plan.assignments = [item for item in plan.assignments if str(item["station_id"]) != str(station_id)]
    plan.updated_at = get_datetime_utc()
    if station.current_release_id == release.id:
        station.current_release_id = None
        uow.session.add(station)
    if not release.assignments:
        release.is_active = False
        plan.status = "paused"
        if plan.group_id:
            group = _owned(uow, ProductionPlanGroup, plan.group_id)
            group.is_paused = True
            uow.session.add(group)
    uow.session.add_all([plan, release])
    _commit(uow)
    return read_plan_task(uow, id)


@router.post(
    "/plans", dependencies=[Depends(require_module_access("esop", "esop:plan:create"))],
    response_model=PlanPublic,
)
def create_plan(uow: EsopTenantUowDep, body: PlanInput, current_principal: CurrentPrincipal) -> PlanPublic:
    _check_window(body.start_at, body.end_at)
    order = _owned(uow, ProductionOrder, body.order_id)
    quantity = body.quantity or order.quantity
    _require_order_capacity(uow, body.order_id, quantity,
                            operation_ids={str(item.operation_id) for item in body.assignments})
    _validate_assignments(uow, body, complete=False)
    row = ProductionPlan(
        tenant_id=uow.tenant_id, created_by=current_principal.id,
        code=body.code or generate_entity_code("PLAN"),
        order_id=body.order_id, quantity=quantity, line_id=body.line_id,
        route_id=None, product_sop_version_id=body.product_sop_version_id,
        assignments=[item.model_dump(mode="json") for item in body.assignments],
        start_at=body.start_at, end_at=body.end_at,
    )
    uow.session.add(row)
    _commit(uow)
    return _plan_public(uow, row)


@router.put(
    "/plans/{id}", dependencies=[Depends(require_module_access("esop", "esop:plan:update"))],
    response_model=PlanPublic,
)
def update_plan(uow: EsopTenantUowDep, id: uuid.UUID, body: PlanInput) -> PlanPublic:
    row = _owned(uow, ProductionPlan, id)
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="已发布排产不能修改，请新建排产")
    _check_window(body.start_at, body.end_at)
    quantity = body.quantity or row.quantity
    _require_order_capacity(uow, body.order_id, quantity,
                            operation_ids={str(item.operation_id) for item in body.assignments},
                            exclude_plan_id=row.id)
    _validate_assignments(uow, body, complete=False)
    if body.code is not None:
        row.code = body.code
    row.order_id, row.quantity, row.line_id, row.route_id = body.order_id, quantity, body.line_id, None
    row.product_sop_version_id = body.product_sop_version_id
    row.assignments = [item.model_dump(mode="json") for item in body.assignments]
    row.start_at, row.end_at = body.start_at, body.end_at
    row.updated_at = get_datetime_utc()
    uow.session.add(row)
    _commit(uow)
    return _plan_public(uow, row)


@router.post(
    "/plans/{id}/publish", dependencies=[Depends(require_module_access("esop", "esop:plan:publish"))],
    response_model=ReleasePublic,
)
def publish_plan(
    uow: EsopTenantUowDep, current_principal: CurrentPrincipal, id: uuid.UUID
) -> ReleasePublic:
    from app.modules.esop.plan_scheduler import start_plan
    plan = _owned(uow, ProductionPlan, id)
    release = start_plan(uow.session, plan, current_principal.id, uow)
    _commit(uow)
    return _release_public(uow, release)


@router.post("/plans/{id}/pause", dependencies=[Depends(require_module_access("esop", "esop:plan:publish"))], response_model=PlanPublic)
def pause_plan(uow: EsopTenantUowDep, id: uuid.UUID) -> PlanPublic:
    plan = _owned(uow, ProductionPlan, id)
    if plan.status != "published":
        raise HTTPException(status_code=409, detail="只有运行中的排产可以暂停")
    release = uow.session.exec(select(WorkRelease).where(WorkRelease.plan_id == id, WorkRelease.is_active == True)).first()  # noqa: E712
    if release:
        release.is_active = False
        uow.session.add(release)
    plan.status = "paused"
    plan.updated_at = get_datetime_utc()
    uow.session.add(plan)
    _commit(uow)
    return _plan_public(uow, plan)


@router.post(
    "/plans/{id}/cancel",
    dependencies=[Depends(require_module_access("esop", "esop:plan:update"))],
    response_model=PlanPublic,
)
def cancel_plan(uow: EsopTenantUowDep, id: uuid.UUID) -> PlanPublic:
    plan = _owned(uow, ProductionPlan, id)
    if plan.status not in {"draft", "paused", "expired"}:
        raise HTTPException(status_code=409, detail="仅未启动、已暂停或到期且没有报工的排产可作废")
    releases = uow.session.exec(select(WorkRelease).where(
        WorkRelease.plan_id == id,
    ).with_for_update()).all()
    if releases and uow.session.exec(select(ProductionReport.id).where(
        ProductionReport.release_id.in_([release.id for release in releases]),
    )).first():
        raise HTTPException(status_code=409, detail="排产已有报工，不能作废")
    for release in releases:
        release.is_active = False
        stations = uow.session.exec(select(Station).where(
            Station.current_release_id == release.id,
        ).with_for_update()).all()
        for station in stations:
            station.current_release_id = None
            uow.session.add(station)
        uow.session.add(release)
    plan.status = "cancelled"
    plan.group_id = None
    plan.group_position = None
    plan.updated_at = get_datetime_utc()
    uow.session.add(plan)
    _commit(uow)
    return _plan_public(uow, plan)


@router.post("/plans/{id}/resume", dependencies=[Depends(require_module_access("esop", "esop:plan:publish"))], response_model=PlanPublic)
def resume_plan(uow: EsopTenantUowDep, id: uuid.UUID) -> PlanPublic:
    plan = _owned(uow, ProductionPlan, id)
    _resume_plan(uow, plan)
    _commit(uow)
    return _plan_public(uow, plan)


def _resume_plan(uow: EsopTenantUowDep, plan: ProductionPlan) -> None:
    if plan.status != "paused":
        raise HTTPException(status_code=409, detail="只有暂停的排产可以恢复")
    if plan.end_at and get_datetime_utc() >= plan.end_at:
        raise HTTPException(status_code=409, detail="排产结束时间已过")
    _require_order_capacity(uow, plan.order_id, plan.quantity,
                            operation_ids={str(item["operation_id"]) for item in plan.assignments},
                            exclude_plan_id=plan.id)
    release = uow.session.exec(select(WorkRelease).where(WorkRelease.plan_id == plan.id)).first()
    if release is None:
        raise HTTPException(status_code=409, detail="排产没有发布记录")
    release.is_active = True
    plan.status = "published"
    plan.updated_at = get_datetime_utc()
    uow.session.add_all([plan, release])


@router.get(
    "/releases", dependencies=[Depends(require_module_access("esop", "esop:plan:list"))],
    response_model=ListReleases,
)
def list_releases(uow: EsopTenantUowDep, order_id: uuid.UUID | None = None) -> ListReleases:
    statement = select(WorkRelease)
    if order_id:
        statement = statement.where(WorkRelease.order_id == order_id)
    rows = uow.session.exec(statement.order_by(WorkRelease.published_at.desc())).all()
    return ListReleases(items=[_release_public(uow, row) for row in rows], total=len(rows))
