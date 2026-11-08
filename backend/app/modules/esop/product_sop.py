"""Product-wide review snapshots; working operations remain an isolated draft."""

import copy
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import (
    Operation,
    ProductSopLock,
    ProductSopVersion,
    SopDocument,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.dto import (
    OperationAttachment,
    OperationPublic,
    ProductSopOperationState,
)
from app.platform.public_api.files import FileAssetDirectory


def lock_product(uow: EsopTenantUnitOfWork, product_id: uuid.UUID) -> None:
    """One durable mutex per product, including a product with no operations yet."""
    key = (uow.tenant_id, product_id)
    if uow.session.get(ProductSopLock, key) is None:
        try:
            with uow.session.begin_nested():
                uow.session.add(ProductSopLock(tenant_id=uow.tenant_id, product_id=product_id))
                uow.session.flush()
        except IntegrityError:
            # Another transaction created the mutex; the locking read sees its committed row.
            pass
    uow.session.exec(
        select(ProductSopLock).where(
            ProductSopLock.tenant_id == uow.tenant_id,
            ProductSopLock.product_id == product_id,
        ).with_for_update()
    ).one()


def product_versions(uow: EsopTenantUnitOfWork, product_id: uuid.UUID, *, lock: bool = False) -> list[ProductSopVersion]:
    statement = select(ProductSopVersion).where(ProductSopVersion.product_id == product_id).order_by(col(ProductSopVersion.version).desc())
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return list(uow.session.exec(statement).all())


def ensure_product_editable(uow: EsopTenantUnitOfWork, product_id: uuid.UUID | None) -> None:
    if product_id is None:
        return
    lock_product(uow, product_id)
    pending = uow.session.exec(select(ProductSopVersion.id).where(
        ProductSopVersion.product_id == product_id, ProductSopVersion.status == "pending",
    ).with_for_update()).first()
    if pending is not None:
        raise HTTPException(status_code=409, detail="该产品已有待审核版本，审核完成后才能修改工序")


def current_operations(uow: EsopTenantUnitOfWork, product_id: uuid.UUID) -> list[Operation]:
    return list(uow.session.exec(select(Operation).where(
        Operation.product_id == product_id, Operation.is_deleted == False,  # noqa: E712
    ).order_by(Operation.sort_order, Operation.code, Operation.id)).all())


def snapshot_operations(operations: list[Operation]) -> list[dict[str, object]]:
    return [OperationPublic.model_validate(operation).model_dump(mode="json") for operation in operations]


def comparable_snapshot(operations: list[dict[str, object]]) -> list[dict[str, object]]:
    """Only authored content, not timestamps or compatibility projection IDs, defines dirty."""
    keys = ("id", "product_id", "code", "name", "description", "attachments")
    result = []
    for operation in operations:
        content = {key: operation.get(key) for key in keys}
        content["attachments"] = [
            OperationAttachment.model_validate(attachment).model_dump(mode="json", exclude_none=True)
            for attachment in operation.get("attachments", [])
        ]
        result.append(content)
    return result


def operation_states(
    current: list[dict[str, object]], approved: list[dict[str, object]], *, pending: bool,
) -> list[ProductSopOperationState]:
    """Derive draft state without changing immutable snapshots or persisted operations."""
    previous = {str(operation["id"]): operation for operation in approved}
    active_ids = {str(operation["id"]) for operation in current}
    # Inserting/removing another step does not itself edit an unchanged retained step.
    prior_order = {str(operation["id"]): index for index, operation in enumerate(
        operation for operation in approved if str(operation["id"]) in active_ids
    )}
    current_order = {str(operation["id"]): index for index, operation in enumerate(
        operation for operation in current if str(operation["id"]) in previous
    )}
    states = []
    for operation in current:
        prior = previous.get(str(operation["id"]))
        unchanged = (prior is not None and prior_order[str(operation["id"])] == current_order[str(operation["id"])]
                     and comparable_snapshot([operation]) == comparable_snapshot([prior]))
        states.append(ProductSopOperationState(
            operation=OperationPublic.model_validate(operation),
            status="approved" if unchanged else ("pending" if pending else "draft"),
            has_approved_version=prior is not None,
        ))
    for operation in approved:
        if str(operation["id"]) not in active_ids:
            states.append(ProductSopOperationState(
                operation=OperationPublic.model_validate(operation), status="pending_delete",
                has_approved_version=True, is_deleted=True,
            ))
    return states


def validate_submission(
    uow: EsopTenantUnitOfWork, operations: list[Operation], files: FileAssetDirectory,
) -> list[dict[str, object]]:
    from app.modules.esop.operation_media import resolve_operation_attachment

    if not operations:
        raise HTTPException(status_code=422, detail="请先添加产品工序")
    snapshot = snapshot_operations(operations)
    for operation in snapshot:
        attachments = operation["attachments"]
        if not attachments:
            raise HTTPException(status_code=422, detail=f"工序“{operation['name']}”尚未上传作业指导书")
        canonical = []
        for attachment in attachments:
            asset = files.get_accessible_file(tenant_id=uow.tenant_id, file_id=uuid.UUID(attachment["file_id"]))
            if asset is None:
                raise HTTPException(status_code=422, detail="作业指导书原文件不存在或不可访问")
            item = resolve_operation_attachment(uow, files, asset, sheet_index=attachment.get("sheet_index"))
            if item.kind in {"word", "excel", "ppt", "pdf"} and not item.display_pages:
                raise HTTPException(status_code=422, detail=f"附件“{item.name}”尚未完成终端预览转换，请等待后台转换或在编辑页重新转换")
            for file_id in [item.display_file_id, *item.display_pages]:
                if file_id is not None and files.get_accessible_file(tenant_id=uow.tenant_id, file_id=file_id) is None:
                    raise HTTPException(status_code=422, detail="作业指导书预览文件不可访问，请重新上传")
            canonical.append(item.model_dump(mode="json"))
        if all(attachment["kind"] == "model_resource" for attachment in canonical):
            raise HTTPException(status_code=422, detail=f"工序“{operation['name']}”仅包含模型配套文件，请上传对应的 CAD / 3D 主模型")
        operation["attachments"] = canonical
    return snapshot


def version_by_id(uow: EsopTenantUnitOfWork, version_id: uuid.UUID) -> ProductSopVersion:
    version = uow.session.get(ProductSopVersion, version_id)
    if version is None or version.tenant_id != uow.tenant_id:
        raise HTTPException(status_code=404, detail="产品 SOP 版本不存在")
    return version


def approved_product_version(
    uow: EsopTenantUnitOfWork, version_id: uuid.UUID, product_id: uuid.UUID | None = None,
) -> ProductSopVersion:
    version = version_by_id(uow, version_id)
    if version.status != "approved" or (product_id is not None and version.product_id != product_id):
        raise HTTPException(status_code=422, detail="请选择该产品已审核通过的 SOP 版本")
    return version


def submission_pages(attachments: list[dict[str, object]]) -> list[dict[str, object]]:
    pages = []
    for raw in attachments:
        attachment = OperationAttachment.model_validate(raw)
        if attachment.kind in {"cad", "model3d", "model_resource"}:
            continue
        file_ids = attachment.display_pages or [attachment.display_file_id or attachment.file_id]
        for file_id in file_ids:
            pages.append({"file_id": str(file_id), "sort": len(pages), "caption": attachment.name[:200]})
    return pages


def approve_version(uow: EsopTenantUnitOfWork, version: ProductSopVersion, reviewer_id: uuid.UUID) -> None:
    now = get_datetime_utc()
    snapshot = copy.deepcopy(version.operations)
    for operation in snapshot:
        operation_id = uuid.UUID(operation["id"])
        prior = list(uow.session.exec(select(SopDocument).where(
            SopDocument.product_id == version.product_id, SopDocument.operation_id == operation_id,
        ).order_by(col(SopDocument.version).desc()).with_for_update().execution_options(populate_existing=True)).all())
        document = SopDocument(
            tenant_id=uow.tenant_id, family_id=prior[0].family_id if prior else uuid.uuid4(),
            product_id=version.product_id, operation_id=operation_id,
            title=operation["name"], version=(prior[0].version + 1) if prior else 1,
            status="approved", pages=submission_pages(operation["attachments"]),
            created_by=version.created_by, reviewed_by=reviewer_id, reviewed_at=now,
        )
        uow.session.add(document)
        operation["sop_id"] = str(document.id)
    version.operations = snapshot
    version.status = "approved"
    version.reviewed_by = reviewer_id
    version.reviewed_at = now
    version.review_note = None
    uow.session.add(version)


def restore_version(uow: EsopTenantUnitOfWork, version: ProductSopVersion) -> None:
    """Restore draft rows by stable ID; historical documents/releases remain immutable."""
    existing = list(uow.session.exec(select(Operation).where(Operation.product_id == version.product_id)).all())
    restored_ids = {uuid.UUID(operation["id"]) for operation in version.operations}
    for operation in existing:
        if operation.id not in restored_ids:
            operation.is_deleted = True
            operation.updated_at = get_datetime_utc()
            uow.session.add(operation)
    for index, snapshot in enumerate(version.operations):
        operation_id = uuid.UUID(snapshot["id"])
        operation = uow.session.get(Operation, operation_id)
        if operation is not None and (operation.tenant_id != uow.tenant_id or operation.product_id != version.product_id):
            raise HTTPException(status_code=409, detail="历史工序归属不一致，无法恢复")
        if operation is None:
            operation = Operation(id=operation_id, tenant_id=uow.tenant_id, product_id=version.product_id,
                                  code=snapshot["code"], name=snapshot["name"])
        operation.code = snapshot["code"]
        operation.name = snapshot["name"]
        operation.description = snapshot.get("description")
        operation.attachments = copy.deepcopy(snapshot["attachments"])
        operation.sort_order = index
        operation.is_deleted = False
        operation.updated_at = get_datetime_utc()
        uow.session.add(operation)
