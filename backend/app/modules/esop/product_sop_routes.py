"""Review, history and rollback for a complete product's operation instructions."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import Operation, ProductSopVersion
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUowDep
from app.modules.esop.product_sop import (
    approve_version,
    comparable_snapshot,
    current_operations,
    ensure_product_editable,
    lock_product,
    operation_states,
    product_versions,
    restore_version,
    snapshot_operations,
    validate_submission,
    version_by_id,
)
from app.modules.esop.public_api.dto import (
    OperationPublic,
    ProductSopSummaries,
    ProductSopSummary,
    ProductSopVersionDetail,
    ProductSopVersionPublic,
    ProductSopVersions,
    ProductSopWorkspace,
    SopReject,
)
from app.modules.product_directory import ProductDirectoryDep
from app.platform.public_api.files import FileDirectRead
from app.platform.web_api import (
    CurrentPrincipal,
    FileAssetDirectoryDep,
    UserDirectoryDep,
    normalize_pagination,
    preview_authorized_file,
    require_any_module_access,
    require_module_access,
)

router = APIRouter(prefix="/esop", tags=["esop-product-sop"])


def _save(uow: EsopTenantUowDep) -> None:
    try:
        uow.session.commit()
    except IntegrityError as exc:
        uow.session.rollback()
        raise HTTPException(status_code=409, detail="版本已发生变化，请刷新后重试") from exc


def _workspace(uow: EsopTenantUowDep, product_id: uuid.UUID, product_name: str) -> ProductSopWorkspace:
    versions = product_versions(uow, product_id)
    approved = next((v for v in versions if v.status == "approved"), None)
    pending = next((v for v in versions if v.status == "pending"), None)
    operations = current_operations(uow, product_id)
    dirty = bool(operations) if approved is None else comparable_snapshot(snapshot_operations(operations)) != comparable_snapshot(approved.operations)
    state = "pending" if pending else ("draft" if dirty else ("approved" if approved else "empty"))
    if (dirty and versions and versions[0].status == "rejected"
            and comparable_snapshot(snapshot_operations(operations)) == comparable_snapshot(versions[0].operations)):
        state = "rejected"
    return ProductSopWorkspace(
        product_id=product_id, product_name=product_name, status=state, dirty=dirty,
        current_operations=[OperationPublic.model_validate(o) for o in operations],
        operation_states=operation_states(snapshot_operations(operations), approved.operations if approved else [], pending=pending is not None),
        approved_version=ProductSopVersionPublic.model_validate(approved) if approved else None,
        pending_version=ProductSopVersionPublic.model_validate(pending) if pending else None,
    )


@router.get("/product-sops/statuses", response_model=ProductSopSummaries,
            dependencies=[Depends(require_module_access("esop", "esop:operation:list"))])
def product_sop_statuses(uow: EsopTenantUowDep, products: ProductDirectoryDep) -> ProductSopSummaries:
    """Read visible product state in batches instead of loading every workspace."""
    product_ids = [product.id for product in products.list()]
    if not product_ids:
        return ProductSopSummaries(items=[], total=0)
    operations = uow.session.exec(select(Operation).where(
        Operation.tenant_id == uow.tenant_id, col(Operation.product_id).in_(product_ids),
        Operation.is_deleted == False,  # noqa: E712
    ).order_by(Operation.sort_order, Operation.code, Operation.id)).all()
    latest = select(
        ProductSopVersion.product_id, ProductSopVersion.status,
        func.max(ProductSopVersion.version).label("version"),
    ).where(
        ProductSopVersion.tenant_id == uow.tenant_id, col(ProductSopVersion.product_id).in_(product_ids),
        col(ProductSopVersion.status).in_(("approved", "pending")),
    ).group_by(ProductSopVersion.product_id, ProductSopVersion.status).subquery()
    versions = uow.session.exec(select(ProductSopVersion).join(latest, and_(
        ProductSopVersion.product_id == latest.c.product_id,
        ProductSopVersion.status == latest.c.status,
        ProductSopVersion.version == latest.c.version,
    )).where(ProductSopVersion.tenant_id == uow.tenant_id)).all()
    operations_by_product = {}
    versions_by_product = {}
    for operation in operations:
        operations_by_product.setdefault(operation.product_id, []).append(operation)
    for version in versions:
        versions_by_product.setdefault(version.product_id, []).append(version)
    items = []
    for product_id in product_ids:
        current = operations_by_product.get(product_id, [])
        history = versions_by_product.get(product_id, [])
        if not current and not history:
            continue
        approved = next((version for version in history if version.status == "approved"), None)
        pending = next((version for version in history if version.status == "pending"), None)
        dirty = bool(current) if approved is None else comparable_snapshot(snapshot_operations(current)) != comparable_snapshot(approved.operations)
        items.append(ProductSopSummary(
            product_id=product_id, status="pending" if pending else ("draft" if dirty else "approved"),
            dirty=dirty, operation_count=len(current),
        ))
    return ProductSopSummaries(items=items, total=len(items))


@router.get("/product-sops/{product_id}/workspace", response_model=ProductSopWorkspace,
            dependencies=[Depends(require_module_access("esop", "esop:operation:list"))])
def product_sop_workspace(uow: EsopTenantUowDep, products: ProductDirectoryDep, product_id: uuid.UUID) -> ProductSopWorkspace:
    product = products.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return _workspace(uow, product_id, product.name)


@router.get("/product-sops/{product_id}/versions", response_model=ProductSopVersions,
            dependencies=[Depends(require_module_access("esop", "esop:sop:list"))])
def list_product_sop_versions(uow: EsopTenantUowDep, products: ProductDirectoryDep,
                              product_id: uuid.UUID) -> ProductSopVersions:
    if not products.exists(product_id):
        raise HTTPException(status_code=404, detail="产品不存在")
    versions = product_versions(uow, product_id)
    return ProductSopVersions(items=[ProductSopVersionPublic.model_validate(v) for v in versions], total=len(versions))


@router.post("/product-sops/{product_id}/submit", response_model=ProductSopVersionPublic,
             dependencies=[Depends(require_module_access("esop", "esop:sop:submit"))])
def submit_product_sop(uow: EsopTenantUowDep, products: ProductDirectoryDep, files: FileAssetDirectoryDep,
                       principal: CurrentPrincipal, product_id: uuid.UUID) -> ProductSopVersionPublic:
    product = products.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    ensure_product_editable(uow, product_id)
    versions = product_versions(uow, product_id, lock=True)
    approved = next((v for v in versions if v.status == "approved"), None)
    operations = current_operations(uow, product_id)
    snapshot = validate_submission(uow, operations, files)
    if approved and comparable_snapshot(snapshot) == comparable_snapshot(approved.operations):
        raise HTTPException(status_code=409, detail="当前产品没有待提交的修改")
    # Persist trusted conversion metadata once all file checks have succeeded.
    for operation, content in zip(operations, snapshot, strict=True):
        operation.attachments = content["attachments"]
        uow.session.add(operation)
    version = ProductSopVersion(
        tenant_id=uow.tenant_id, product_id=product_id, product_name=product.name,
        version=(versions[0].version + 1) if versions else 1, operations=snapshot,
        base_version_id=approved.id if approved else None, created_by=principal.id,
    )
    uow.session.add(version)
    _save(uow)
    return ProductSopVersionPublic.model_validate(version)


@router.post("/product-sops/{product_id}/discard-draft", response_model=ProductSopWorkspace,
             dependencies=[Depends(require_module_access("esop", "esop:operation:update"))])
def discard_product_sop_draft(uow: EsopTenantUowDep, products: ProductDirectoryDep,
                              product_id: uuid.UUID) -> ProductSopWorkspace:
    product = products.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    ensure_product_editable(uow, product_id)
    approved = next((version for version in product_versions(uow, product_id, lock=True)
                     if version.status == "approved"), None)
    operations = current_operations(uow, product_id)
    if approved is None:
        if not operations:
            raise HTTPException(status_code=409, detail="当前产品没有可取消的草稿")
        for operation in operations:
            operation.is_deleted = True
            operation.updated_at = get_datetime_utc()
            uow.session.add(operation)
    else:
        if comparable_snapshot(snapshot_operations(operations)) == comparable_snapshot(approved.operations):
            raise HTTPException(status_code=409, detail="当前产品没有可取消的草稿")
        restore_version(uow, approved)
    _save(uow)
    return _workspace(uow, product_id, product.name)


@router.get("/product-sop-versions", response_model=ProductSopVersions,
            dependencies=[Depends(require_module_access("esop", "esop:sop:review"))])
def list_sop_review_versions(uow: EsopTenantUowDep, users: UserDirectoryDep, status: str | None = "pending",
                             page: int = 1, page_size: int = 20, keyword: str | None = None,
                             submitted_from: datetime | None = None, submitted_to: datetime | None = None) -> ProductSopVersions:
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    if status not in {None, "pending", "approved", "rejected", "reviewed"}:
        raise HTTPException(status_code=422, detail="版本状态不正确")
    statement = select(ProductSopVersion)
    if status == "reviewed":
        statement = statement.where(col(ProductSopVersion.status).in_(("approved", "rejected")))
    elif status:
        statement = statement.where(ProductSopVersion.status == status)
    if keyword and keyword.strip():
        statement = statement.where(col(ProductSopVersion.product_name).contains(keyword.strip(), autoescape=True))
    if submitted_from is not None:
        statement = statement.where(ProductSopVersion.submitted_at >= submitted_from)
    if submitted_to is not None:
        statement = statement.where(ProductSopVersion.submitted_at <= submitted_to)
    sort_column = ProductSopVersion.reviewed_at if status in {"reviewed", "approved", "rejected"} else ProductSopVersion.submitted_at
    versions = uow.session.exec(statement.order_by(col(sort_column).desc(), col(ProductSopVersion.id).desc())).all()
    visible = versions[(page - 1) * page_size:page * page_size]
    reviewers = {user.id: user.full_name or user.email or "未命名用户"
                 for user in users.get_users({v.reviewed_by for v in visible if v.reviewed_by})}
    return ProductSopVersions(
        items=[ProductSopVersionPublic.model_validate(v).model_copy(update={
            "reviewer_name": reviewers.get(v.reviewed_by),
        }) for v in visible],
        total=len(versions),
    )


@router.get("/product-sop-versions/{id}", response_model=ProductSopVersionDetail,
            dependencies=[Depends(require_any_module_access("esop", ("esop:sop:list", "esop:sop:review")))])
def product_sop_version_detail(uow: EsopTenantUowDep, id: uuid.UUID) -> ProductSopVersionDetail:
    version = version_by_id(uow, id)
    base = version_by_id(uow, version.base_version_id) if version.base_version_id else None
    return ProductSopVersionDetail(
        version=ProductSopVersionPublic.model_validate(version),
        base_version=ProductSopVersionPublic.model_validate(base) if base else None,
    )


def _pending_for_review(uow: EsopTenantUowDep, id: uuid.UUID) -> ProductSopVersion:
    version = version_by_id(uow, id)
    lock_product(uow, version.product_id)
    version = uow.session.get(ProductSopVersion, id, with_for_update=True, populate_existing=True)
    if version.status != "pending":
        raise HTTPException(status_code=409, detail="只有待审核版本可以进行审核")
    return version


@router.post("/product-sop-versions/{id}/approve", response_model=ProductSopVersionPublic,
             dependencies=[Depends(require_module_access("esop", "esop:sop:review"))])
def approve_product_sop(uow: EsopTenantUowDep, files: FileAssetDirectoryDep,
                        principal: CurrentPrincipal, id: uuid.UUID) -> ProductSopVersionPublic:
    version = _pending_for_review(uow, id)
    for operation in version.operations:
        for attachment in operation["attachments"]:
            ids = [attachment["file_id"], attachment.get("display_file_id"), *attachment.get("display_pages", [])]
            for file_id in ids:
                if file_id and files.get_accessible_file(tenant_id=uow.tenant_id, file_id=uuid.UUID(file_id)) is None:
                    raise HTTPException(status_code=422, detail="版本引用的指导书文件已不可访问，请驳回后重新上传")
    approve_version(uow, version, principal.id)
    _save(uow)
    return ProductSopVersionPublic.model_validate(version)


@router.post("/product-sop-versions/{id}/reject", response_model=ProductSopVersionPublic,
             dependencies=[Depends(require_module_access("esop", "esop:sop:review"))])
def reject_product_sop(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                       id: uuid.UUID, body: SopReject) -> ProductSopVersionPublic:
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="请填写驳回原因")
    version = _pending_for_review(uow, id)
    base = version_by_id(uow, version.base_version_id) if version.base_version_id else None
    if base is not None and (base.product_id != version.product_id or base.status != "approved"):
        raise HTTPException(status_code=409, detail="上一已审核版本已变化，请刷新后重试")
    if base is not None:
        restore_version(uow, base)
    version.status = "rejected"
    version.reviewed_by = principal.id
    version.reviewed_at = get_datetime_utc()
    version.review_note = reason
    uow.session.add(version)
    _save(uow)
    return ProductSopVersionPublic.model_validate(version)


@router.post("/product-sop-versions/{id}/rollback", response_model=ProductSopWorkspace,
             dependencies=[Depends(require_module_access("esop", "esop:sop:update"))])
def rollback_product_sop(uow: EsopTenantUowDep, products: ProductDirectoryDep, id: uuid.UUID) -> ProductSopWorkspace:
    version = version_by_id(uow, id)
    product = products.get(version.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在，不能恢复草稿")
    if version.status != "approved":
        raise HTTPException(status_code=409, detail="只能从已审核通过的历史版本恢复草稿")
    ensure_product_editable(uow, version.product_id)
    restore_version(uow, version)
    _save(uow)
    return _workspace(uow, version.product_id, product.name)


@router.get("/product-sop-versions/{id}/files/{file_id}/preview", response_model=None,
            dependencies=[Depends(require_any_module_access("esop", ("esop:sop:list", "esop:sop:review")))])
def preview_product_sop_file(uow: EsopTenantUowDep, id: uuid.UUID, file_id: uuid.UUID):
    version = version_by_id(uow, id)
    accessible = {
        str(value) for operation in version.operations for attachment in operation["attachments"]
        for value in [attachment["file_id"], attachment.get("display_file_id"), *attachment.get("display_pages", [])]
        if value
    }
    if str(file_id) not in accessible:
        raise HTTPException(status_code=404, detail="该版本不包含此文件")
    return preview_authorized_file(session=uow.session, tenant_id=uow.tenant_id, file_id=file_id)


def _authorize_instruction_file(uow, product_id, file_id, version_id):
    if version_id:
        version = version_by_id(uow, version_id)
        if version.product_id != product_id:
            raise HTTPException(status_code=404, detail="该产品不包含此版本")
        operations = version.operations
    else:
        operations = snapshot_operations(current_operations(uow, product_id))
    accessible = {
        str(value) for operation in operations for attachment in operation["attachments"]
        for value in [attachment["file_id"], attachment.get("display_file_id"), *attachment.get("display_pages", [])]
        if value
    }
    if str(file_id) not in accessible:
        raise HTTPException(status_code=404, detail="该产品指导书不包含此文件")


@router.get("/product-sops/{product_id}/files/{file_id}/preview", response_model=None,
            dependencies=[Depends(require_any_module_access("esop", ("esop:operation:list", "esop:sop:list", "esop:sop:review")))])
def preview_product_instruction(uow: EsopTenantUowDep, product_id: uuid.UUID,
                                file_id: uuid.UUID, version_id: uuid.UUID | None = None):
    _authorize_instruction_file(uow, product_id, file_id, version_id)
    return preview_authorized_file(session=uow.session, tenant_id=uow.tenant_id, file_id=file_id)


@router.get("/product-sops/{product_id}/files/{file_id}/access", response_model=FileDirectRead,
            dependencies=[Depends(require_any_module_access("esop", ("esop:operation:list", "esop:sop:list", "esop:sop:review")))])
def product_instruction_direct_access(uow: EsopTenantUowDep, files: FileAssetDirectoryDep,
                                      product_id: uuid.UUID, file_id: uuid.UUID,
                                      version_id: uuid.UUID | None = None) -> FileDirectRead:
    _authorize_instruction_file(uow, product_id, file_id, version_id)
    return files.direct_read_url(tenant_id=uow.tenant_id, file_id=file_id)


@router.post("/product-sops/{product_id}/prepare-media", response_model=ProductSopWorkspace,
             dependencies=[Depends(require_any_module_access("esop", ("esop:operation:update", "esop:sop:update")))])
def prepare_product_instruction_media(uow: EsopTenantUowDep, products: ProductDirectoryDep,
                                      files: FileAssetDirectoryDep, principal: CurrentPrincipal,
                                      product_id: uuid.UUID) -> ProductSopWorkspace:
    from app.modules.esop.operation_media import prepare_existing_operation_media

    product = products.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    ensure_product_editable(uow, product_id)
    prepare_existing_operation_media(uow, principal, files, product_id)
    _save(uow)
    return _workspace(uow, product_id, product.name)
