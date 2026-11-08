"""The controlled SOP path: process setup, draft, review and versioning."""

import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import (
    Operation,
    OperationMediaJob,
    ProcessRoute,
    ProductionPlan,
    ProductionReport,
    SopDocument,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUowDep
from app.modules.esop.product_sop import ensure_product_editable
from app.modules.esop.public_api.direct_files import DirectFileTicket
from app.modules.esop.public_api.dto import (
    ListOperations,
    ListRoutes,
    ListSops,
    OperationAttachment,
    OperationInput,
    OperationMediaStatus,
    OperationMove,
    OperationProductTree,
    OperationPublic,
    RouteInput,
    RoutePublic,
    SopCreate,
    SopImportAnalysis,
    SopImportRequest,
    SopPage,
    SopPublic,
    SopReject,
    SopUpdate,
)
from app.modules.product_directory import ProductDirectoryDep
from app.platform.public_api.codes import generate_entity_code
from app.platform.public_api.files import (
    FileDirectRead,
    FileDirectUpload,
    FileDirectUploadRequest,
)
from app.platform.web_api import (
    CurrentPrincipal,
    FileAssetDirectoryDep,
    download_authorized_file,
    normalize_pagination,
    preview_authorized_file,
    require_module_access,
    upload_authorized_file,
)

router = APIRouter(prefix="/esop", tags=["esop"])
SOP_MEDIA_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif"}


def _validate_operation(body: OperationInput, uow: EsopTenantUowDep,
                        products: ProductDirectoryDep, files: FileAssetDirectoryDep) -> None:
    if body.product_id is not None and not products.exists(body.product_id):
        raise HTTPException(status_code=422, detail="产品不存在")
    if len({a.file_id for a in body.attachments}) != len(body.attachments):
        raise HTTPException(status_code=422, detail="工序附件不能重复")
    from app.modules.esop.operation_media import resolve_operation_attachment

    attachments = []
    for attachment in body.attachments:
        asset = files.get_accessible_file(tenant_id=uow.tenant_id, file_id=attachment.file_id)
        if asset is None:
            raise HTTPException(status_code=422, detail="工序附件不可访问")
        display_name = attachment.name.strip()
        if not display_name or Path(display_name).suffix.lower() != Path(asset.original_name).suffix.lower():
            raise HTTPException(status_code=422, detail="附件名称不能为空，且扩展名必须与原文件一致")
        attachments.append(resolve_operation_attachment(uow, files, asset, sheet_index=attachment.sheet_index).model_copy(update={"name": display_name}))
    body.attachments = attachments


def _save(uow: EsopTenantUowDep) -> None:
    try:
        uow.session.commit()
    except IntegrityError as exc:
        uow.session.rollback()
        raise HTTPException(status_code=409, detail="编码或版本已存在，请刷新后重试") from exc


def _operation(uow: EsopTenantUowDep, id: uuid.UUID, *, lock: bool = False) -> Operation:
    entity = uow.session.get(Operation, id, with_for_update=True, populate_existing=True) if lock else uow.session.get(Operation, id)
    if entity is None or entity.tenant_id != uow.tenant_id or entity.is_deleted:
        raise HTTPException(status_code=404, detail="工序不存在")
    return entity


def _route(uow: EsopTenantUowDep, id: uuid.UUID) -> ProcessRoute:
    entity = uow.session.get(ProcessRoute, id)
    if entity is None or entity.tenant_id != uow.tenant_id:
        raise HTTPException(status_code=404, detail="Route not found")
    return entity


def _sop(uow: EsopTenantUowDep, id: uuid.UUID) -> SopDocument:
    entity = uow.session.get(SopDocument, id)
    if entity is None or entity.tenant_id != uow.tenant_id:
        raise HTTPException(status_code=404, detail="SOP not found")
    return entity


def _validate_steps(uow: EsopTenantUowDep, operation_ids: list[uuid.UUID]) -> None:
    if len(operation_ids) != len(set(operation_ids)):
        raise HTTPException(status_code=422, detail="Duplicate operations are not allowed")
    found = uow.session.exec(
        select(Operation.id).where(col(Operation.id).in_(operation_ids), col(Operation.is_deleted).is_(False)).with_for_update()
    ).all()
    if set(found) != set(operation_ids):
        raise HTTPException(status_code=422, detail="Unknown operation")


def _validate_pages(
    *, tenant_id: uuid.UUID, pages: list[SopPage], files: FileAssetDirectoryDep
) -> None:
    if len({page.file_id for page in pages}) != len(pages):
        raise HTTPException(status_code=422, detail="Duplicate SOP files are not allowed")
    if len({page.sort for page in pages}) != len(pages):
        raise HTTPException(status_code=422, detail="Duplicate page order is not allowed")
    for page in pages:
        asset = files.get_accessible_file(tenant_id=tenant_id, file_id=page.file_id)
        if asset is None:
            raise HTTPException(status_code=422, detail="SOP file is unavailable")
        content_type = (asset.content_type or "").lower()
        if content_type not in SOP_MEDIA_TYPES:
            raise HTTPException(status_code=422, detail="SOP supports PDF and images only")


def _pages_payload(pages: list[SopPage]) -> list[dict[str, object]]:
    return [page.model_dump(mode="json") for page in sorted(pages, key=lambda item: item.sort)]


@router.get(
    "/products",
    dependencies=[Depends(require_module_access("esop", "esop:sop:list"))],
)
def list_products(products: ProductDirectoryDep, keyword: str | None = None) -> dict[str, Any]:
    return {"items": products.list(keyword)}


@router.get(
    "/operations",
    dependencies=[Depends(require_module_access("esop", "esop:operation:list"))],
    response_model=ListOperations,
)
def list_operations(
    uow: EsopTenantUowDep, page: int = 1, page_size: int = 100, keyword: str | None = None,
    product_id: uuid.UUID | None = None, unassigned: bool = False,
    created_from: datetime | None = None, created_to: datetime | None = None,
) -> ListOperations:
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    statement = select(Operation).where(Operation.is_deleted == False)  # noqa: E712
    if product_id is not None:
        statement = statement.where(Operation.product_id == product_id)
    elif unassigned:
        statement = statement.where(Operation.product_id.is_(None))
    if keyword:
        statement = statement.where(
            col(Operation.name).ilike(f"%{keyword}%") | col(Operation.code).ilike(f"%{keyword}%")
        )
    if created_from is not None:
        statement = statement.where(Operation.created_at >= created_from)
    if created_to is not None:
        statement = statement.where(Operation.created_at <= created_to)
    entities = uow.session.exec(statement.order_by(Operation.sort_order, Operation.code, Operation.id)).all()
    return ListOperations(
        items=[OperationPublic.model_validate(entity) for entity in entities[(page - 1) * page_size:page * page_size]],
        total=len(entities),
    )


@router.post(
    "/operations",
    dependencies=[Depends(require_module_access("esop", "esop:operation:create"))],
    response_model=OperationPublic,
)
def create_operation(uow: EsopTenantUowDep, body: OperationInput,
                     products: ProductDirectoryDep, files: FileAssetDirectoryDep) -> OperationPublic:
    _validate_operation(body, uow, products, files)
    ensure_product_editable(uow, body.product_id)
    body.code = body.code or generate_entity_code("PROC")
    values = body.model_dump()
    values["attachments"] = [a.model_dump(mode="json") for a in body.attachments]
    last_sort = uow.session.exec(
        select(Operation.sort_order).where(
            Operation.tenant_id == uow.tenant_id, Operation.product_id == body.product_id
        ).order_by(col(Operation.sort_order).desc()).limit(1).with_for_update()
    ).first()
    entity = Operation(tenant_id=uow.tenant_id, sort_order=(last_sort + 1) if last_sort is not None else 0, **values)
    uow.session.add(entity)
    _save(uow)
    return OperationPublic.model_validate(entity)


@router.put(
    "/operations/{id}",
    dependencies=[Depends(require_module_access("esop", "esop:operation:update"))],
    response_model=OperationPublic,
)
def update_operation(uow: EsopTenantUowDep, id: uuid.UUID, body: OperationInput,
                     products: ProductDirectoryDep, files: FileAssetDirectoryDep) -> OperationPublic:
    entity = _operation(uow, id)
    original_product_id = entity.product_id
    if "product_id" not in body.model_fields_set:
        body.product_id = entity.product_id
    if "attachments" not in body.model_fields_set:
        body.attachments = [OperationAttachment.model_validate(a) for a in entity.attachments]
    if original_product_id is not None and body.product_id is None:
        raise HTTPException(status_code=422, detail="工序必须关联产品")
    _validate_operation(body, uow, products, files)
    for product_id in sorted({p for p in (original_product_id, body.product_id) if p is not None}):
        ensure_product_editable(uow, product_id)
    entity = _operation(uow, id, lock=True)
    if entity.product_id != original_product_id:
        raise HTTPException(status_code=409, detail="工序所属产品已变化，请刷新后重试")
    if original_product_id is not None and body.product_id != original_product_id:
        last_sort = uow.session.exec(select(Operation.sort_order).where(
            Operation.product_id == body.product_id, Operation.is_deleted == False,  # noqa: E712
        ).order_by(col(Operation.sort_order).desc()).limit(1).with_for_update()).first()
        moved = Operation(
            tenant_id=uow.tenant_id, product_id=body.product_id,
            code=body.code if body.code and body.code != entity.code else generate_entity_code("PROC"),
            name=body.name, description=body.description,
            attachments=[attachment.model_dump(mode="json") for attachment in body.attachments],
            sort_order=(last_sort + 1) if last_sort is not None else 0,
        )
        entity.is_deleted = True
        entity.updated_at = get_datetime_utc()
        uow.session.add_all([entity, moved])
        _save(uow)
        return OperationPublic.model_validate(moved)
    for key, value in body.model_dump(mode="json").items():
        if key == "product_id" and value is not None:
            value = uuid.UUID(value)
        if key != "code" or value is not None:
            setattr(entity, key, value)
    entity.updated_at = get_datetime_utc()
    uow.session.add(entity)
    _save(uow)
    return OperationPublic.model_validate(entity)


@router.post(
    "/operations/{id}/move", response_model=OperationPublic,
    dependencies=[Depends(require_module_access("esop", "esop:operation:update"))],
)
def move_operation(uow: EsopTenantUowDep, id: uuid.UUID, body: OperationMove) -> OperationPublic:
    entity = _operation(uow, id)
    ensure_product_editable(uow, entity.product_id)
    operations = list(uow.session.exec(
        select(Operation).where(Operation.product_id == entity.product_id, Operation.is_deleted == False)  # noqa: E712
        .order_by(Operation.sort_order, Operation.code, Operation.id).with_for_update()
        .execution_options(populate_existing=True)
    ).all())
    moving = next((item for item in operations if item.id == id), None)
    target = next((item for item in operations if item.id == body.target_id), None)
    if moving is None or target is None:
        raise HTTPException(status_code=422, detail="只能调整同一产品下的工序顺序")
    if moving.id == target.id:
        return OperationPublic.model_validate(moving)
    operations.remove(moving)
    index = operations.index(target) + (1 if body.position == "after" else 0)
    operations.insert(index, moving)
    for index, item in enumerate(operations):
        if item.sort_order != index:
            item.sort_order = index
            item.updated_at = get_datetime_utc()
            uow.session.add(item)
    _save(uow)
    return OperationPublic.model_validate(moving)


@router.delete(
    "/operations/{id}", status_code=204,
    dependencies=[Depends(require_module_access("esop", "esop:operation:delete"))],
)
def delete_operation(uow: EsopTenantUowDep, id: uuid.UUID) -> None:
    entity = _operation(uow, id)
    ensure_product_editable(uow, entity.product_id)
    entity = _operation(uow, id, lock=True)
    if entity.product_id is not None:
        entity.is_deleted = True
        entity.updated_at = get_datetime_utc()
        uow.session.add(entity)
        _save(uow)
        return
    if uow.session.exec(select(SopDocument.id).where(SopDocument.operation_id == id)).first():
        raise HTTPException(status_code=409, detail="该工序已被 SOP 引用，无法删除")
    if uow.session.exec(select(ProductionReport.id).where(ProductionReport.operation_id == id)).first():
        raise HTTPException(status_code=409, detail="该工序已有生产报工记录，无法删除")
    if any(str(id) in route.operation_ids for route in uow.session.exec(select(ProcessRoute)).all()):
        raise HTTPException(status_code=409, detail="该工序已被工艺流程引用，无法删除")
    for model in (ProductionPlan, WorkRelease):
        if any(
            str(assignment.get("operation_id")) == str(id)
            for record in uow.session.exec(select(model)).all()
            for assignment in record.assignments
        ):
            raise HTTPException(status_code=409, detail="该工序已被排产或发布记录引用，无法删除")
    uow.session.delete(entity)
    _save(uow)


@router.get(
    "/operations/product-tree", response_model=OperationProductTree,
    dependencies=[Depends(require_module_access("esop", "esop:operation:list"))],
)
def operation_product_tree(products: ProductDirectoryDep) -> OperationProductTree:
    categories, items = products.tree()
    return OperationProductTree(categories=[asdict(c) for c in categories], products=[asdict(p) for p in items])


def _upload_operation_file(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                           files: FileAssetDirectoryDep, file: UploadFile) -> OperationAttachment:
    from app.modules.esop.operation_media import upload_operation_media

    return upload_operation_media(uow, principal, files, file)


@router.post(
    "/operations/files/upload", response_model=OperationAttachment,
    dependencies=[Depends(require_module_access("esop", "esop:operation:create"))],
)
def upload_operation_file(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                          files: FileAssetDirectoryDep, file: UploadFile = File(...)) -> OperationAttachment:
    return _upload_operation_file(uow, principal, files, file)


@router.post(
    "/operations/{id}/files/upload", response_model=OperationAttachment,
    dependencies=[Depends(require_module_access("esop", "esop:operation:update"))],
)
def upload_existing_operation_file(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                                   files: FileAssetDirectoryDep, id: uuid.UUID,
                                   file: UploadFile = File(...)) -> OperationAttachment:
    entity = _operation(uow, id)
    ensure_product_editable(uow, entity.product_id)
    return _upload_operation_file(uow, principal, files, file)


def _editor_file_access(uow, principal, files, file_id, operation=None):
    references = {
        str(value) for attachment in (operation.attachments if operation else [])
        for value in [attachment['file_id'], attachment.get('display_file_id'), *attachment.get('display_pages', [])]
        if value
    }
    if str(file_id) in references:
        return files.direct_read_url(tenant_id=uow.tenant_id, file_id=file_id)
    return files.direct_uploaded_read_url(tenant_id=uow.tenant_id, file_id=file_id, uploader_id=principal.id)


def _import_workbook(uow, principal, files, file_id):
    from app.modules.esop.operation_media import MAX_CONVERSION_BYTES
    from app.modules.esop.sop_import import workbook_sheets

    _editor_file_access(uow, principal, files, file_id)
    asset = files.get_accessible_file(tenant_id=uow.tenant_id, file_id=file_id)
    if asset is None:
        raise HTTPException(404, "Excel 文件不存在")
    extension = Path(asset.original_name).suffix.lower().lstrip(".")
    if extension not in {"xls", "xlsx"}:
        raise HTTPException(422, "请选择 Excel 文件")
    data = files.read_file_bytes(tenant_id=uow.tenant_id, file_id=file_id, max_bytes=MAX_CONVERSION_BYTES)
    return asset, workbook_sheets(data, extension)


@router.get("/operations/files/{file_id}/sop-import", response_model=SopImportAnalysis,
            dependencies=[Depends(require_module_access("esop", "esop:operation:create"))])
def analyze_sop_import(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                       files: FileAssetDirectoryDep, file_id: uuid.UUID) -> SopImportAnalysis:
    _, sheets = _import_workbook(uow, principal, files, file_id)
    return SopImportAnalysis(sheets=sheets)


@router.post("/operations/products/{product_id}/sop-import", response_model=list[OperationPublic],
             dependencies=[Depends(require_module_access("esop", "esop:operation:update"))])
def import_product_sop(uow: EsopTenantUowDep, principal: CurrentPrincipal, files: FileAssetDirectoryDep,
                       products: ProductDirectoryDep, product_id: uuid.UUID, body: SopImportRequest) -> list[OperationPublic]:
    from app.modules.esop.operation_media import resolve_operation_attachment
    from app.modules.esop.product_sop import current_operations

    if not products.exists(product_id):
        raise HTTPException(404, "产品不存在")
    ensure_product_editable(uow, product_id)
    asset, sheets = _import_workbook(uow, principal, files, body.file_id)
    by_index = {int(sheet["index"]): str(sheet["name"]) for sheet in sheets}
    selected = set(body.sheet_indexes)
    if len(selected) != len(body.sheet_indexes) or not selected.issubset(by_index):
        raise HTTPException(422, "请选择有效且不重复的 sheet")
    if any(len(by_index[index]) > 100 for index in selected):
        raise HTTPException(422, "sheet 名称超过工序名称长度限制")
    existing = current_operations(uow, product_id)
    if any(any(str(item.get("file_id")) == str(body.file_id) for item in op.attachments) for op in existing):
        raise HTTPException(409, "此 Excel 已导入当前产品，请勿重复导入")
    if body.mode == "replace":
        for operation in existing:
            operation.is_deleted = True
            operation.updated_at = get_datetime_utc()
            uow.session.add(operation)
    last_sort = max((operation.sort_order for operation in existing), default=-1) if body.mode == "append" else -1
    created = []
    for index in sorted(selected):
        attachment = resolve_operation_attachment(uow, files, asset, sheet_index=index)
        operation = Operation(tenant_id=uow.tenant_id, product_id=product_id,
                              code=generate_entity_code("PROC"), name=by_index[index],
                              sort_order=last_sort + len(created) + 1,
                              attachments=[attachment.model_dump(mode="json")])
        uow.session.add(operation)
        created.append(operation)
    if not created[0].attachments[0].get("display_pages"):
        job = uow.session.exec(select(OperationMediaJob).where(
            OperationMediaJob.tenant_id == uow.tenant_id,
            OperationMediaJob.original_file_id == body.file_id,
        )).first()
        if job is None:
            uow.session.add(OperationMediaJob(tenant_id=uow.tenant_id,
                                              original_file_id=body.file_id, uploader_id=principal.id))
        elif job.status in {"failed", "ready"}:
            job.status, job.attempts, job.error_message = "queued", 0, None
            job.started_at = None
            job.updated_at = get_datetime_utc()
            uow.session.add(job)
    _save(uow)
    return [OperationPublic.model_validate(operation) for operation in created]


@router.get('/operations/files/{file_id}/access', response_model=FileDirectRead,
            dependencies=[Depends(require_module_access('esop', 'esop:operation:create'))])
def editor_uploaded_file_access(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                                files: FileAssetDirectoryDep, file_id: uuid.UUID) -> FileDirectRead:
    return _editor_file_access(uow, principal, files, file_id)


@router.get('/operations/{id}/files/{file_id}/access', response_model=FileDirectRead,
            dependencies=[Depends(require_module_access('esop', 'esop:operation:update'))])
def editor_existing_file_access(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                                files: FileAssetDirectoryDep, id: uuid.UUID, file_id: uuid.UUID) -> FileDirectRead:
    return _editor_file_access(uow, principal, files, file_id, _operation(uow, id))


def _media_status(uow, principal, files, file_id, operation=None) -> OperationMediaStatus:
    from app.modules.esop.operation_media import (
        FILE_KINDS,
        resolve_operation_attachment,
    )

    _editor_file_access(uow, principal, files, file_id, operation)
    asset = files.get_accessible_file(tenant_id=uow.tenant_id, file_id=file_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    sheet_index = next((item.get("sheet_index") for item in operation.attachments
                        if str(item.get("file_id")) == str(file_id)), None) if operation else None
    try:
        attachment = resolve_operation_attachment(uow, files, asset, sheet_index=sheet_index)
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        attachment = OperationAttachment(file_id=asset.id, name=asset.original_name, sheet_index=sheet_index,
            original_name=asset.original_name, kind=FILE_KINDS[Path(asset.original_name).suffix.lower().lstrip('.')],
            content_type=asset.content_type, size=asset.size)
    job = uow.session.exec(select(OperationMediaJob).where(OperationMediaJob.original_file_id == file_id)).first()
    return OperationMediaStatus(
        status="ready" if attachment.display_pages or attachment.display_file_id else (job.status if job and job.status != "ready" else "failed"),
        error_message=job.error_message if job and job.status == "failed" else None,
        attachment=attachment,
    )


@router.get('/operations/files/{file_id}/conversion', response_model=OperationMediaStatus,
            dependencies=[Depends(require_module_access('esop', 'esop:operation:create'))])
def uploaded_file_conversion(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                             files: FileAssetDirectoryDep, file_id: uuid.UUID) -> OperationMediaStatus:
    return _media_status(uow, principal, files, file_id)


@router.get('/operations/{id}/files/{file_id}/conversion', response_model=OperationMediaStatus,
            dependencies=[Depends(require_module_access('esop', 'esop:operation:update'))])
def existing_file_conversion(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                             files: FileAssetDirectoryDep, id: uuid.UUID, file_id: uuid.UUID) -> OperationMediaStatus:
    return _media_status(uow, principal, files, file_id, _operation(uow, id))


def _retry_media(uow, principal, files, file_id, operation=None) -> OperationMediaStatus:
    from app.modules.esop.operation_media import OFFICE_EXTENSIONS, VIDEO_EXTENSIONS

    status = _media_status(uow, principal, files, file_id, operation)
    if status.status != "failed":
        return status
    extension = Path(status.attachment.original_name or status.attachment.name).suffix.lower().lstrip('.')
    if extension not in OFFICE_EXTENSIONS | VIDEO_EXTENSIONS | {'pdf'}:
        raise HTTPException(status_code=422, detail="该格式无需转换")
    job = uow.session.exec(select(OperationMediaJob).where(OperationMediaJob.original_file_id == file_id).with_for_update()).first()
    if job is None:
        job = OperationMediaJob(tenant_id=uow.tenant_id, original_file_id=file_id, uploader_id=principal.id)
    else:
        job.status = "queued"
        job.attempts = 0
        job.error_message = None
        job.started_at = None
        job.updated_at = get_datetime_utc()
    uow.session.add(job)
    uow.session.commit()
    return _media_status(uow, principal, files, file_id, operation)


@router.post('/operations/files/{file_id}/conversion/retry', response_model=OperationMediaStatus,
             dependencies=[Depends(require_module_access('esop', 'esop:operation:create'))])
def retry_uploaded_file_conversion(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                                   files: FileAssetDirectoryDep, file_id: uuid.UUID) -> OperationMediaStatus:
    return _retry_media(uow, principal, files, file_id)


@router.post('/operations/{id}/files/{file_id}/conversion/retry', response_model=OperationMediaStatus,
             dependencies=[Depends(require_module_access('esop', 'esop:operation:update'))])
def retry_existing_file_conversion(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                                   files: FileAssetDirectoryDep, id: uuid.UUID, file_id: uuid.UUID) -> OperationMediaStatus:
    return _retry_media(uow, principal, files, file_id, _operation(uow, id))


def _begin_direct_image_upload(uow, principal, files, body):
    from pathlib import Path
    if Path(body.name).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
        raise HTTPException(status_code=422, detail="图片直传仅支持 PNG、JPG、WebP 和 GIF")
    image_types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif'}
    if body.content_type != image_types[Path(body.name).suffix.lower()]:
        raise HTTPException(status_code=422, detail="图片格式与上传类型不一致")
    return files.begin_direct_upload(tenant_id=uow.tenant_id, uploader_id=principal.id, request=body)


def _complete_direct_image_upload(uow, principal, files, ticket):
    from app.modules.esop.operation_media import resolve_operation_attachment
    asset = files.complete_direct_upload(tenant_id=uow.tenant_id, uploader_id=principal.id, ticket=ticket)
    return resolve_operation_attachment(uow, files, asset)


@router.post("/operations/files/direct-upload", response_model=FileDirectUpload,
             dependencies=[Depends(require_module_access("esop", "esop:operation:create"))])
def begin_operation_image(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                          files: FileAssetDirectoryDep, body: FileDirectUploadRequest):
    return _begin_direct_image_upload(uow, principal, files, body)


@router.post("/operations/{id}/files/direct-upload", response_model=FileDirectUpload,
             dependencies=[Depends(require_module_access("esop", "esop:operation:update"))])
def begin_existing_operation_image(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                                   files: FileAssetDirectoryDep, id: uuid.UUID, body: FileDirectUploadRequest):
    ensure_product_editable(uow, _operation(uow, id).product_id)
    return _begin_direct_image_upload(uow, principal, files, body)


@router.post("/operations/files/direct-upload/complete", response_model=OperationAttachment,
             dependencies=[Depends(require_module_access("esop", "esop:operation:create"))])
def complete_operation_image(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                             files: FileAssetDirectoryDep, body: DirectFileTicket):
    return _complete_direct_image_upload(uow, principal, files, body.ticket)


@router.post("/operations/{id}/files/direct-upload/complete", response_model=OperationAttachment,
             dependencies=[Depends(require_module_access("esop", "esop:operation:update"))])
def complete_existing_operation_image(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                                      files: FileAssetDirectoryDep, id: uuid.UUID, body: DirectFileTicket):
    ensure_product_editable(uow, _operation(uow, id).product_id)
    return _complete_direct_image_upload(uow, principal, files, body.ticket)


@router.post("/operations/files/direct-upload/abort", status_code=204,
             dependencies=[Depends(require_module_access("esop", "esop:operation:create"))])
def abort_operation_image(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                          files: FileAssetDirectoryDep, body: DirectFileTicket):
    files.abort_direct_upload(tenant_id=uow.tenant_id, uploader_id=principal.id, ticket=body.ticket)


@router.post("/operations/{id}/files/direct-upload/abort", status_code=204,
             dependencies=[Depends(require_module_access("esop", "esop:operation:update"))])
def abort_existing_operation_image(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                                   files: FileAssetDirectoryDep, id: uuid.UUID, body: DirectFileTicket):
    _operation(uow, id)
    files.abort_direct_upload(tenant_id=uow.tenant_id, uploader_id=principal.id, ticket=body.ticket)


@router.get(
    "/operations/{id}/files/{file_id}/download", response_model=None,
    dependencies=[Depends(require_module_access("esop", "esop:operation:list"))],
)
def download_operation_file(uow: EsopTenantUowDep, id: uuid.UUID, file_id: uuid.UUID):
    entity = _operation(uow, id)
    if not any(a["file_id"] == str(file_id) for a in entity.attachments):
        raise HTTPException(status_code=404, detail="Operation file not found")
    return download_authorized_file(session=uow.session, tenant_id=uow.tenant_id, file_id=file_id)


@router.get(
    "/operations/{id}/files/{file_id}/preview", response_model=None,
    dependencies=[Depends(require_module_access("esop", "esop:operation:list"))],
)
def preview_operation_file(uow: EsopTenantUowDep, id: uuid.UUID, file_id: uuid.UUID):
    entity = _operation(uow, id)
    references = {
        str(value) for attachment in entity.attachments
        for value in [attachment["file_id"], attachment.get("display_file_id"), *attachment.get("display_pages", [])]
        if value
    }
    if str(file_id) not in references:
        raise HTTPException(status_code=404, detail="该工序不包含此文件")
    return preview_authorized_file(session=uow.session, tenant_id=uow.tenant_id, file_id=file_id)


@router.get(
    "/routes",
    dependencies=[Depends(require_module_access("esop", "esop:route:list"))],
    response_model=ListRoutes,
)
def list_routes(uow: EsopTenantUowDep) -> ListRoutes:
    entities = uow.session.exec(select(ProcessRoute).order_by(ProcessRoute.code)).all()
    return ListRoutes(items=[RoutePublic.model_validate(entity) for entity in entities], total=len(entities))


@router.post(
    "/routes",
    dependencies=[Depends(require_module_access("esop", "esop:route:create"))],
    response_model=RoutePublic,
)
def create_route(uow: EsopTenantUowDep, body: RouteInput) -> RoutePublic:
    _validate_steps(uow, body.operation_ids)
    entity = ProcessRoute(
        tenant_id=uow.tenant_id, code=body.code or generate_entity_code("ROUTE"), name=body.name,
        operation_ids=[str(value) for value in body.operation_ids],
    )
    uow.session.add(entity)
    _save(uow)
    return RoutePublic.model_validate(entity)


@router.put(
    "/routes/{id}",
    dependencies=[Depends(require_module_access("esop", "esop:route:update"))],
    response_model=RoutePublic,
)
def update_route(uow: EsopTenantUowDep, id: uuid.UUID, body: RouteInput) -> RoutePublic:
    entity = _route(uow, id)
    _validate_steps(uow, body.operation_ids)
    entity.code = body.code or entity.code
    entity.name = body.name
    entity.operation_ids = [str(value) for value in body.operation_ids]
    entity.updated_at = get_datetime_utc()
    uow.session.add(entity)
    _save(uow)
    return RoutePublic.model_validate(entity)


@router.get(
    "/sops",
    dependencies=[Depends(require_module_access("esop", "esop:sop:list"))],
    response_model=ListSops,
)
def list_sops(
    uow: EsopTenantUowDep,
    product_id: uuid.UUID | None = None,
    operation_id: uuid.UUID | None = None,
    status: str | None = None,
    latest_only: bool = False,
    page: int = 1,
    page_size: int = 100,
) -> ListSops:
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    statement = select(SopDocument)
    if product_id:
        statement = statement.where(SopDocument.product_id == product_id)
    if operation_id:
        statement = statement.where(SopDocument.operation_id == operation_id)
    if status:
        statement = statement.where(SopDocument.status == status)
    entities = uow.session.exec(statement.order_by(SopDocument.version.desc(), SopDocument.created_at.desc())).all()
    if latest_only:
        if product_id is None or status != "approved":
            raise HTTPException(status_code=422, detail="最新版本查询需要指定产品和已审核状态")
        latest: dict[uuid.UUID, SopDocument] = {}
        for entity in entities:
            latest.setdefault(entity.operation_id, entity)
        entities = list(latest.values())
    return ListSops(
        items=[SopPublic.model_validate(entity) for entity in entities[(page - 1) * page_size:page * page_size]],
        total=len(entities),
    )


@router.post(
    "/sops/files/upload",
    dependencies=[Depends(require_module_access("esop", "esop:sop:upload"))],
)
def upload_sop_file(
    uow: EsopTenantUowDep, current_principal: CurrentPrincipal,
    file: UploadFile = File(...),
) -> dict[str, uuid.UUID]:
    content_type = (file.content_type or "").lower()
    if content_type not in SOP_MEDIA_TYPES:
        raise HTTPException(status_code=422, detail="SOP supports PDF and images only")
    file_id = upload_authorized_file(
        session=uow.session, tenant_id=uow.tenant_id,
        uploader_id=current_principal.id, file=file,
    )
    return {"id": file_id}


@router.get(
    "/sops/{id}/versions",
    dependencies=[Depends(require_module_access("esop", "esop:sop:list"))],
    response_model=ListSops,
)
def list_sop_versions(uow: EsopTenantUowDep, id: uuid.UUID) -> ListSops:
    source = _sop(uow, id)
    versions = uow.session.exec(
        select(SopDocument).where(SopDocument.family_id == source.family_id)
        .order_by(SopDocument.version.desc())
    ).all()
    return ListSops(items=[SopPublic.model_validate(item) for item in versions], total=len(versions))


@router.get(
    "/sops/{id}",
    dependencies=[Depends(require_module_access("esop", "esop:sop:list"))],
    response_model=SopPublic,
)
def read_sop(uow: EsopTenantUowDep, id: uuid.UUID) -> SopPublic:
    return SopPublic.model_validate(_sop(uow, id))


@router.get(
    "/sops/{id}/pages/{file_id}/preview",
    dependencies=[Depends(require_module_access("esop", "esop:sop:list"))],
    response_model=None,
)
def preview_sop_page(
    uow: EsopTenantUowDep, id: uuid.UUID, file_id: uuid.UUID
) -> FileResponse | StreamingResponse:
    entity = _sop(uow, id)
    if not any(page.get("file_id") == str(file_id) for page in entity.pages):
        raise HTTPException(status_code=404, detail="SOP page not found")
    return preview_authorized_file(
        session=uow.session, tenant_id=uow.tenant_id, file_id=file_id
    )


@router.post(
    "/sops",
    dependencies=[Depends(require_module_access("esop", "esop:sop:create"))],
    response_model=SopPublic,
)
def create_sop(
    uow: EsopTenantUowDep,
    current_principal: CurrentPrincipal,
    products: ProductDirectoryDep,
    files: FileAssetDirectoryDep,
    body: SopCreate,
) -> SopPublic:
    if not products.exists(body.product_id):
        raise HTTPException(status_code=422, detail="产品不存在")
    operation = _operation(uow, body.operation_id, lock=True)
    if operation.product_id not in {None, body.product_id}:
        raise HTTPException(status_code=422, detail="工序与 SOP 产品不匹配")
    _validate_pages(tenant_id=uow.tenant_id, pages=body.pages, files=files)
    existing = uow.session.exec(
        select(SopDocument).where(
            SopDocument.product_id == body.product_id,
            SopDocument.operation_id == body.operation_id,
        )
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="SOP already exists; create a new version")
    entity = SopDocument(
        tenant_id=uow.tenant_id, family_id=uuid.uuid4(),
        product_id=body.product_id, operation_id=body.operation_id,
        title=body.title, pages=_pages_payload(body.pages), created_by=current_principal.id,
    )
    uow.session.add(entity)
    _save(uow)
    return SopPublic.model_validate(entity)


@router.put(
    "/sops/{id}",
    dependencies=[Depends(require_module_access("esop", "esop:sop:update"))],
    response_model=SopPublic,
)
def update_sop(
    uow: EsopTenantUowDep, files: FileAssetDirectoryDep,
    id: uuid.UUID, body: SopUpdate,
) -> SopPublic:
    entity = _sop(uow, id)
    if entity.status not in {"draft", "rejected"}:
        raise HTTPException(status_code=409, detail="Only drafts can be edited")
    _validate_pages(tenant_id=uow.tenant_id, pages=body.pages, files=files)
    entity.title = body.title
    entity.pages = _pages_payload(body.pages)
    entity.status = "draft"
    entity.review_note = None
    entity.updated_at = get_datetime_utc()
    uow.session.add(entity)
    _save(uow)
    return SopPublic.model_validate(entity)


@router.post(
    "/sops/{id}/submit",
    dependencies=[Depends(require_module_access("esop", "esop:sop:submit"))],
    response_model=SopPublic,
)
def submit_sop(uow: EsopTenantUowDep, id: uuid.UUID) -> SopPublic:
    entity = _sop(uow, id)
    if entity.status not in {"draft", "rejected"}:
        raise HTTPException(status_code=409, detail="SOP cannot be submitted")
    if not entity.pages:
        raise HTTPException(status_code=422, detail="SOP has no content")
    entity.status = "pending"
    entity.updated_at = get_datetime_utc()
    uow.session.add(entity)
    _save(uow)
    return SopPublic.model_validate(entity)


@router.post(
    "/sops/{id}/approve",
    dependencies=[Depends(require_module_access("esop", "esop:sop:review"))],
    response_model=SopPublic,
)
def approve_sop(
    uow: EsopTenantUowDep, current_principal: CurrentPrincipal, id: uuid.UUID
) -> SopPublic:
    entity = _sop(uow, id)
    if entity.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending SOP can be approved")
    entity.status = "approved"
    entity.reviewed_by = current_principal.id
    entity.reviewed_at = get_datetime_utc()
    entity.updated_at = entity.reviewed_at
    uow.session.add(entity)
    _save(uow)
    return SopPublic.model_validate(entity)


@router.post(
    "/sops/{id}/reject",
    dependencies=[Depends(require_module_access("esop", "esop:sop:review"))],
    response_model=SopPublic,
)
def reject_sop(
    uow: EsopTenantUowDep, current_principal: CurrentPrincipal,
    id: uuid.UUID, body: SopReject,
) -> SopPublic:
    entity = _sop(uow, id)
    if entity.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending SOP can be rejected")
    entity.status = "rejected"
    entity.review_note = body.reason
    entity.reviewed_by = current_principal.id
    entity.reviewed_at = get_datetime_utc()
    entity.updated_at = entity.reviewed_at
    uow.session.add(entity)
    _save(uow)
    return SopPublic.model_validate(entity)


@router.post(
    "/sops/{id}/new-version",
    dependencies=[Depends(require_module_access("esop", "esop:sop:create"))],
    response_model=SopPublic,
)
def new_sop_version(
    uow: EsopTenantUowDep, current_principal: CurrentPrincipal, id: uuid.UUID
) -> SopPublic:
    source = _sop(uow, id)
    if source.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved SOP can start a new version")
    versions = uow.session.exec(
        select(SopDocument).where(SopDocument.family_id == source.family_id)
    ).all()
    if source.version != max(item.version for item in versions if item.status == "approved"):
        raise HTTPException(status_code=409, detail="Start from the latest approved version")
    if any(item.status in {"draft", "pending", "rejected"} for item in versions):
        raise HTTPException(status_code=409, detail="An editable version already exists")
    entity = SopDocument(
        tenant_id=uow.tenant_id, family_id=source.family_id,
        product_id=source.product_id, operation_id=source.operation_id,
        title=source.title, pages=list(source.pages),
        version=max(item.version for item in versions) + 1,
        created_by=current_principal.id,
    )
    uow.session.add(entity)
    _save(uow)
    return SopPublic.model_validate(entity)


@router.post(
    "/sops/{id}/rollback",
    dependencies=[Depends(require_module_access("esop", "esop:sop:create"))],
    response_model=SopPublic,
)
def rollback_sop_version(
    uow: EsopTenantUowDep, current_principal: CurrentPrincipal, id: uuid.UUID
) -> SopPublic:
    source = _sop(uow, id)
    if source.status != "approved":
        raise HTTPException(status_code=409, detail="只能从已审核通过的版本回滚")
    versions = uow.session.exec(
        select(SopDocument).where(SopDocument.family_id == source.family_id)
    ).all()
    latest_approved = max(item.version for item in versions if item.status == "approved")
    if source.version == latest_approved:
        raise HTTPException(status_code=409, detail="当前已是最新审核版本")
    if any(item.status in {"draft", "pending", "rejected"} for item in versions):
        raise HTTPException(status_code=409, detail="该 SOP 已有待处理版本，请先完成审核")
    entity = SopDocument(
        tenant_id=uow.tenant_id, family_id=source.family_id,
        product_id=source.product_id, operation_id=source.operation_id,
        title=source.title, pages=list(source.pages),
        version=max(item.version for item in versions) + 1,
        created_by=current_principal.id,
    )
    uow.session.add(entity)
    _save(uow)
    return SopPublic.model_validate(entity)
