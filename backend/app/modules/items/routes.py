import csv
import io
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import col, select

from app.core.export_datetime import (
    ExportTimezoneHeader,
    export_datetime,
    export_timezone,
)
from app.modules.items.infrastructure.models import (
    Item,
)
from app.modules.items.infrastructure.repository import ItemsRepository
from app.modules.items.infrastructure.tenant_uow import ItemsTenantUowDep
from app.modules.items.public_api.dto import (
    ItemCreate,
    ItemPublic,
    ItemsPublic,
    ItemUpdate,
)
from app.platform.web_api import (
    CurrentPrincipal,
    CurrentTenant,
    build_owner_data_scope_filter,
    normalize_pagination,
    require_module_access,
)

router = APIRouter(prefix="/items", tags=["items"])


def item_to_csv_row(item: Item, timezone: ZoneInfo) -> list[Any]:
    return [
        item.id,
        item.title,
        item.description or "",
        item.owner_id,
        export_datetime(item.created_at, timezone),
        export_datetime(item.updated_at, timezone),
    ]


def ensure_item_in_data_scope(
    *,
    uow: ItemsTenantUowDep,
    current_principal: CurrentPrincipal,
    tenant_id: uuid.UUID,
    item: Item,
) -> None:
    scope_filter = build_owner_data_scope_filter(
        session=uow.session,
        current_principal=current_principal,
        tenant_id=tenant_id,
        owner_id_column=Item.owner_id,
    )
    allowed = uow.session.exec(
        select(Item.id).where(
            Item.id == item.id,
            scope_filter,
        )
    ).first()
    if allowed is None:
        raise HTTPException(status_code=403, detail="Not enough permissions")


@router.get(
    "",
    dependencies=[Depends(require_module_access("items", "business:item:list"))],
    response_model=ItemsPublic,
)
def read_items(
    uow: ItemsTenantUowDep,
    current_principal: CurrentPrincipal,
    tenant_context: CurrentTenant,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Any:
    """
    Retrieve items.
    """
    page, page_size = normalize_pagination(page=page, page_size=page_size)

    repository = ItemsRepository(uow)
    filters = []
    if keyword:
        pattern = f"%{keyword}%"
        filters.append(
            (col(Item.title).ilike(pattern)) | (col(Item.description).ilike(pattern))
        )
    if created_from is not None:
        filters.append(Item.created_at >= created_from)
    if created_to is not None:
        filters.append(Item.created_at <= created_to)

    filters.append(
        build_owner_data_scope_filter(
            session=uow.session,
            current_principal=current_principal,
            tenant_id=tenant_context.tenant_id,
            owner_id_column=Item.owner_id,
        )
    )
    items, count = repository.list(page=page, page_size=page_size, filters=filters)

    items_public = [ItemPublic.model_validate(item) for item in items]
    return ItemsPublic(
        items=items_public,
        total=count,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/export",
    dependencies=[Depends(require_module_access("items", "business:item:list"))],
)
def export_items(
    uow: ItemsTenantUowDep,
    current_principal: CurrentPrincipal,
    tenant_context: CurrentTenant,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    keyword: str | None = None,
    x_export_timezone: ExportTimezoneHeader = None,
) -> StreamingResponse:
    timezone = export_timezone(x_export_timezone)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(
        ["编号", "标题", "描述", "负责人编号", "创建时间", "更新时间"]
    )
    filters = [
        build_owner_data_scope_filter(
            session=uow.session,
            current_principal=current_principal,
            tenant_id=tenant_context.tenant_id,
            owner_id_column=Item.owner_id,
        )
    ]
    if created_from is not None:
        filters.append(Item.created_at >= created_from)
    if created_to is not None:
        filters.append(Item.created_at <= created_to)
    if keyword:
        pattern = f"%{keyword}%"
        filters.append((col(Item.title).ilike(pattern)) | (col(Item.description).ilike(pattern)))
    items = ItemsRepository(uow).all(filters=filters)
    for item in items:
        writer.writerow(item_to_csv_row(item, timezone))
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('资源列表.csv')}"},
    )


@router.get(
    "/import-template",
    dependencies=[Depends(require_module_access("items", "business:item:create"))],
)
def download_import_template() -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["title", "description"])
    writer.writerow(["示例资源", "这是导入模板示例"])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="items-import-template.csv"'
        },
    )


@router.post(
    "/import",
    dependencies=[Depends(require_module_access("items", "business:item:create"))],
)
async def import_items(
    uow: ItemsTenantUowDep,
    current_principal: CurrentPrincipal,
    tenant_context: CurrentTenant,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    raw_content = await file.read()
    try:
        content = raw_content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV file must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or "title" not in reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV must contain title column")

    success_count = 0
    errors: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        title = (row.get("title") or "").strip()
        description = (row.get("description") or "").strip() or None
        if not title:
            errors.append({"row": row_number, "error": "title is required"})
            continue
        item = Item(
            title=title[:255],
            description=description[:255] if description else None,
            owner_id=current_principal.id,
            tenant_id=tenant_context.tenant_id,
        )
        ItemsRepository(uow).add(item)
        success_count += 1

    uow.session.commit()
    return {
        "errors": errors,
        "failed": len(errors),
        "success": success_count,
        "total": success_count + len(errors),
    }


@router.get(
    "/{id}",
    dependencies=[Depends(require_module_access("items", "business:item:list"))],
    response_model=ItemPublic,
)
def read_item(
    uow: ItemsTenantUowDep,
    current_principal: CurrentPrincipal,
    tenant_context: CurrentTenant,
    id: uuid.UUID,
) -> Any:
    """
    Get item by ID.
    """
    item = ItemsRepository(uow).get(id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    ensure_item_in_data_scope(
        uow=uow,
        current_principal=current_principal,
        tenant_id=tenant_context.tenant_id,
        item=item,
    )
    return item


@router.post(
    "",
    dependencies=[Depends(require_module_access("items", "business:item:create"))],
    response_model=ItemPublic,
)
def create_item(
    *,
    uow: ItemsTenantUowDep,
    current_principal: CurrentPrincipal,
    tenant_context: CurrentTenant,
    item_in: ItemCreate,
) -> Any:
    """
    Create new item.
    """
    item = Item.model_validate(
        item_in,
        update={
            "owner_id": current_principal.id,
            "tenant_id": tenant_context.tenant_id,
        },
    )
    ItemsRepository(uow).add(item)
    uow.session.commit()
    uow.session.refresh(item)
    return item


@router.patch(
    "/{id}",
    dependencies=[Depends(require_module_access("items", "business:item:update"))],
    response_model=ItemPublic,
)
def update_item(
    *,
    uow: ItemsTenantUowDep,
    current_principal: CurrentPrincipal,
    tenant_context: CurrentTenant,
    id: uuid.UUID,
    item_in: ItemUpdate,
) -> Any:
    """
    Update an item.
    """
    item = ItemsRepository(uow).get(id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    ensure_item_in_data_scope(
        uow=uow,
        current_principal=current_principal,
        tenant_id=tenant_context.tenant_id,
        item=item,
    )
    update_dict = item_in.model_dump(exclude_unset=True)
    ItemsRepository(uow).update(item, update_dict)
    uow.session.commit()
    uow.session.refresh(item)
    return item


@router.delete(
    "/{id}",
    dependencies=[Depends(require_module_access("items", "business:item:delete"))],
    status_code=204,
)
def delete_item(
    uow: ItemsTenantUowDep,
    current_principal: CurrentPrincipal,
    tenant_context: CurrentTenant,
    id: uuid.UUID,
) -> Response:
    """
    Delete an item.
    """
    item = ItemsRepository(uow).get(id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    ensure_item_in_data_scope(
        uow=uow,
        current_principal=current_principal,
        tenant_id=tenant_context.tenant_id,
        item=item,
    )
    ItemsRepository(uow).delete(item)
    uow.session.commit()
    return Response(status_code=204)
