"""Terminal-owned change requests and manager review, separate from effective totals."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import func, select

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import (
    ProductionOrder,
    ProductionReport,
    ProductionReportChange,
    ProductionReportRevision,
)
from app.modules.esop.infrastructure.tenant_uow import (
    EsopTenantUnitOfWork,
    EsopTenantUowDep,
)
from app.modules.esop.public_api.terminal_dto import (
    ListReportChanges,
    ListTerminalReports,
    ReportChangeInput,
    ReportChangePublic,
    ReportChangeReview,
    ReportCorrectionInput,
    ReportDeleteInput,
    TerminalReportPublic,
)
from app.modules.esop.report_routes import (
    _can_correct_reports,
    _correction_snapshot,
    _lock_release_for_report_write,
    _lock_report_release,
    _terminal,
    _validate_report_quantities,
    correct_report,
)
from app.modules.esop.terminal_routes import DeviceDep
from app.modules.product_directory import product_directory_for_tenant
from app.platform.web_api import (
    CurrentPrincipal,
    CurrentTenant,
    SessionDep,
    UserDirectoryDep,
    normalize_pagination,
    require_module_access,
)

router = APIRouter(prefix="/esop", tags=["esop-report"])


def _staff_device(session, device, principal, tenant, users):
    if tenant.tenant_id != device.tenant_id:
        raise HTTPException(status_code=403, detail="员工和设备不属于同一租户")
    staff = users.get_users([principal.id])
    if not staff or not staff[0].is_active:
        raise HTTPException(status_code=403, detail="员工账号已停用")
    return _terminal(session, device)


def _public_report(session, row):
    result = TerminalReportPublic.model_validate(row)
    order = session.get(ProductionOrder, row.order_id)
    product = product_directory_for_tenant(session, row.tenant_id).get(order.product_id) if order else None
    if product:
        result.product_name = product.name
        result.product_model = product.model
    latest = session.exec(select(ProductionReportChange).where(
        ProductionReportChange.report_id == row.id,
    ).order_by(ProductionReportChange.requested_at.desc(), ProductionReportChange.id.desc())).first()
    if latest:
        result.change_kind = latest.kind
        result.change_status = latest.status
        result.change_id = latest.id
        result.change_reason = latest.review_note
    return result


def _public_change(session, change):
    result = ReportChangePublic.model_validate(change)
    row = session.get(ProductionReport, change.report_id)
    if row:
        result.order_code = row.order_code
        result.sop_title = row.sop_title
    return result


@router.get("/terminal/reports", response_model=ListTerminalReports)
def terminal_reports(session: SessionDep, device: DeviceDep, principal: CurrentPrincipal,
                     tenant: CurrentTenant, users: UserDirectoryDep,
                     page: int = 1, page_size: int = 20) -> ListTerminalReports:
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _staff_device(session, device, principal, tenant, users)
        filters = (ProductionReport.staff_user_id == principal.id,
                   ProductionReport.station_id == terminal.station_id, ProductionReport.is_deleted == False)  # noqa: E712
        total = session.exec(select(func.count()).select_from(ProductionReport).where(*filters)).one()
        rows = session.exec(select(ProductionReport).where(*filters).order_by(
            ProductionReport.occurred_at.desc(), ProductionReport.id.desc(),
        ).offset((page - 1) * page_size).limit(page_size)).all()
        return ListTerminalReports(items=[_public_report(session, row) for row in rows], total=total)


@router.post("/terminal/reports/{report_id}/changes", response_model=ReportChangePublic)
def request_report_change(report_id: uuid.UUID, body: ReportChangeInput,
                          session: SessionDep, device: DeviceDep, principal: CurrentPrincipal,
                          tenant: CurrentTenant, users: UserDirectoryDep) -> ReportChangePublic:
    return _request_report_change(report_id, body, session, device, principal, tenant, users)


@router.post("/terminal/reports/{report_id}/deletion", response_model=ReportChangePublic)
def request_report_deletion(report_id: uuid.UUID, body: ReportDeleteInput,
                            session: SessionDep, device: DeviceDep, principal: CurrentPrincipal,
                            tenant: CurrentTenant, users: UserDirectoryDep) -> ReportChangePublic:
    return _request_report_change(report_id, body, session, device, principal, tenant, users, kind="delete")


def _request_report_change(report_id: uuid.UUID, body: ReportChangeInput | ReportDeleteInput,
                          session: SessionDep, device: DeviceDep, principal: CurrentPrincipal,
                          tenant: CurrentTenant, users: UserDirectoryDep, *, kind: str = "edit") -> ReportChangePublic:
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = _staff_device(session, device, principal, tenant, users)
        row = session.exec(select(ProductionReport).where(
            ProductionReport.id == report_id,
            ProductionReport.staff_user_id == principal.id,
            ProductionReport.station_id == terminal.station_id,
        ).with_for_update().execution_options(populate_existing=True)).first()
        if row is None:
            raise HTTPException(status_code=404, detail="报工记录不存在或不属于当前员工和工位")
        # A locking read sees the latest committed request even under MySQL REPEATABLE READ.
        changes = session.exec(select(ProductionReportChange).where(
            ProductionReportChange.report_id == row.id,
        ).with_for_update().execution_options(populate_existing=True)).all()
        before = _correction_snapshot(row)
        after = {**before, "is_deleted": True} if kind == "delete" else {
            **before, "input_qty": body.input_qty, "good_qty": body.good_qty, "defect_qty": body.defect_qty,
        }
        for change in changes:
            if change.request_id == body.request_id:
                same = (change.kind == kind and change.expected_revision == body.expected_revision
                        and change.reason == body.reason and change.requested_by == principal.id)
                if kind == "edit":
                    same = same and all(change.after[key] == after[key] for key in ("input_qty", "good_qty", "defect_qty"))
                if not same:
                    raise HTTPException(status_code=409, detail="请求编号已用于其他内容")
                return _public_change(session, change)
        if row.is_deleted:
            raise HTTPException(status_code=409, detail="报工已删除，不能再提交申请")
        if row.revision != body.expected_revision:
            raise HTTPException(status_code=409, detail="报工已更新，请刷新后重新修改")
        if any(change.status == "pending" for change in changes):
            raise HTTPException(status_code=409, detail="该报工已有待审核申请，请等待审核")
        if kind == "edit":
            _validate_report_quantities(body.input_qty, body.good_qty, body.defect_qty)
        if after == _correction_snapshot(row):
            raise HTTPException(status_code=422, detail="未修改报工内容")
        change = ProductionReportChange(
            tenant_id=device.tenant_id, report_id=row.id, request_id=body.request_id,
            kind=kind, expected_revision=row.revision, requested_by=principal.id, requested_by_name=row.staff_name,
            reason=body.reason, before=_correction_snapshot(row), after=after,
        )
        session.add(change)
        session.commit()
        return _public_change(session, change)


@router.get("/report-changes", response_model=ListReportChanges,
            dependencies=[Depends(require_module_access("esop", "esop:report:list"))])
def report_changes(uow: EsopTenantUowDep, principal: CurrentPrincipal, users: UserDirectoryDep,
                   page: int = 1, page_size: int = 20, status: str = "pending") -> ListReportChanges:
    if not _can_correct_reports(principal, uow, users):
        raise HTTPException(status_code=403, detail="仅经理及以上岗位或租户管理员可审核报工修改或删除")
    if status not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=422, detail="审核状态无效")
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    statement = select(ProductionReportChange).where(ProductionReportChange.status == status)
    total = uow.session.exec(select(func.count()).select_from(ProductionReportChange).where(ProductionReportChange.status == status)).one()
    rows = uow.session.exec(statement.order_by(ProductionReportChange.requested_at.desc(), ProductionReportChange.id.desc())
                            .offset((page - 1) * page_size).limit(page_size)).all()
    return ListReportChanges(items=[_public_change(uow.session, row) for row in rows], total=total)


@router.post("/report-changes/{change_id}/review", response_model=ReportChangePublic,
             dependencies=[Depends(require_module_access("esop", "esop:report:list"))])
def review_report_change(change_id: uuid.UUID, body: ReportChangeReview,
                         uow: EsopTenantUowDep, principal: CurrentPrincipal,
                         users: UserDirectoryDep) -> ReportChangePublic:
    if not _can_correct_reports(principal, uow, users):
        raise HTTPException(status_code=403, detail="仅经理及以上岗位或租户管理员可审核报工修改或删除")
    # Lock in the same order as request intake: effective report, then request.
    change = uow.session.get(ProductionReportChange, change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="审核申请不存在")
    _lock_report_release(uow.session, change.report_id)
    row = uow.session.exec(select(ProductionReport).where(ProductionReport.id == change.report_id).with_for_update().execution_options(populate_existing=True)).first()
    change = uow.session.exec(select(ProductionReportChange).where(ProductionReportChange.id == change_id)
                              .with_for_update().execution_options(populate_existing=True)).one()
    if row is None:
        raise HTTPException(status_code=404, detail="报工记录不存在")
    if change.status != "pending":
        raise HTTPException(status_code=409, detail="此申请已审核，请刷新")
    if body.approve and row.revision != change.expected_revision:
        raise HTTPException(status_code=409, detail="报工已更新，请退回此申请后重新提交")
    if not body.approve and not body.note:
        raise HTTPException(status_code=422, detail="请填写退回原因")
    if body.approve and change.kind == "edit":
        _validate_report_quantities(change.after["input_qty"], change.after["good_qty"], change.after["defect_qty"])
        _lock_release_for_report_write(uow.session, row.release_id)
    actor = users.get_users([principal.id])
    change.reviewed_by = principal.id
    change.reviewed_by_name = (actor[0].full_name or actor[0].email or str(principal.id)) if actor else str(principal.id)
    change.reviewed_at = get_datetime_utc()
    change.review_note = body.note or None
    change.status = "approved" if body.approve else "rejected"
    if body.approve and change.kind == "delete":
        if row.is_deleted:
            raise HTTPException(status_code=409, detail="报工已经删除")
        from app.modules.esop.sip_routes import ensure_report_inspection_balance
        ensure_report_inspection_balance(uow.session, row, 0)
        before = _correction_snapshot(row)
        row.is_deleted = True
        row.revision += 1
        uow.session.add(ProductionReportRevision(
            tenant_id=uow.tenant_id, report_id=row.id, revision=row.revision,
            reason=change.reason, changed_by=principal.id, changed_by_name=change.reviewed_by_name,
            before=before, after=_correction_snapshot(row),
        ))
        uow.session.commit()
    elif body.approve:
        # correct_report writes the revision history and commits this request in the same transaction.
        correct_report(row.id, ReportCorrectionInput(
            expected_revision=change.expected_revision, reason=change.reason,
            staff_user_id=uuid.UUID(change.after["staff_user_id"]),
            input_qty=change.after["input_qty"], good_qty=change.after["good_qty"], defect_qty=change.after["defect_qty"],
        ), uow, principal, users)
    else:
        uow.session.commit()
    return _public_change(uow.session, change)
