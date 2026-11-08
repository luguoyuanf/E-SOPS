"""Exported CSV cells use the same calendar representation as their pages."""

import asyncio
import csv
import io
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI

from app.api.main import create_api_router
from app.api.routes import users as users_routes
from app.core.export_datetime import export_timezone
from app.modules.erp import export_routes, stock_routes
from app.modules.items.routes import item_to_csv_row
from app.modules.items.routes import router as items_router


async def _csv_rows(response):
    body = "".join([
        part.decode() if isinstance(part, bytes) else part
        async for part in response.body_iterator
    ])
    return list(csv.reader(io.StringIO(body.removeprefix("\ufeff"))))


def test_every_export_route_declares_page_timezone_header() -> None:
    esop_app = FastAPI()
    esop_app.include_router(create_api_router(edition="esop"), prefix="/api/v1")
    esop_exports = [
        operation
        for path, methods in esop_app.openapi()["paths"].items()
        if path.endswith("/export")
        for operation in methods.values()
    ]
    assert len(esop_exports) == 27
    assert all(
        any(
            parameter["in"] == "header"
            and parameter["name"] == "X-Export-Timezone"
            for parameter in operation.get("parameters", [])
        )
        for operation in esop_exports
    )

    items_app = FastAPI()
    items_app.include_router(items_router)
    item_export = items_app.openapi()["paths"]["/items/export"]["get"]
    assert any(
        parameter["in"] == "header" and parameter["name"] == "X-Export-Timezone"
        for parameter in item_export["parameters"]
    )


def test_erp_document_and_stock_csv_render_selected_timezone(monkeypatch) -> None:
    instant = datetime(2026, 10, 29, 16, 1, 2, tzinfo=UTC)
    purchase_order = next(
        definition for definition in export_routes._EXPORTS
        if definition.path == "purchase-orders"
    )
    purchase_order = replace(purchase_order, scope=lambda *_: None)
    monkeypatch.setattr(export_routes, "document_list_filters", lambda **_: [])
    monkeypatch.setattr(export_routes, "record_action", lambda **_: None)
    session = MagicMock()
    count_result = MagicMock()
    count_result.one.return_value = 1
    rows_result = MagicMock()
    rows_result.yield_per.return_value = [SimpleNamespace(
        no="PO-1", supplier_name="测试供应商", status="draft",
        business_at=instant, total_quantity=1, total_amount=10,
    )]
    session.exec.side_effect = [count_result, rows_result]
    uow = SimpleNamespace(session=session)
    principal = SimpleNamespace(id=uuid.uuid4())
    rows = asyncio.run(_csv_rows(export_routes._export(purchase_order)(
        uow, principal, x_export_timezone="America/New_York",
    )))
    assert rows[0][3] == "业务时间"
    assert rows[1][3] == "2026-10-29 12:01:02"

    monkeypatch.setattr(stock_routes, "stock_balance_filters", lambda **_: [])
    monkeypatch.setattr(stock_routes, "record_stock_export", lambda **_: None)
    monkeypatch.setattr(stock_routes, "balance_publics", lambda **_: [SimpleNamespace(
        product_code="P-1", product_name="产品", unit_name="件",
        warehouse_name="主仓", quantity=1, version=1, updated_at=instant,
    )])
    session = MagicMock()
    count_result = MagicMock()
    count_result.one.return_value = 1
    rows_result = MagicMock()
    rows_result.yield_per.return_value.partitions.return_value = [[object()]]
    session.exec.side_effect = [count_result, rows_result]
    rows = asyncio.run(_csv_rows(stock_routes.export_stock_balances(
        SimpleNamespace(session=session), principal,
        x_export_timezone="Asia/Taipei",
    )))
    assert rows[0][-1] == "更新时间"
    assert rows[1][-1] == "2026-10-30 00:01:02"


def test_user_and_item_export_cells_keep_empty_values(monkeypatch) -> None:
    instant = datetime(2026, 10, 29, 16, 1, 2, tzinfo=UTC)
    monkeypatch.setattr(users_routes, "build_owner_data_scope_filter", lambda **_: True)
    session = MagicMock()
    user = SimpleNamespace(
        id=uuid.uuid4(), email="example@test.invalid", full_name="测试用户",
        is_active=True, is_superuser=False, created_at=instant,
    )
    session.exec.return_value.all.return_value = [
        (user, SimpleNamespace(department_id=None), None, None, None),
    ]
    rows = asyncio.run(_csv_rows(users_routes.export_users(
        session, SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(tenant_id=uuid.uuid4()),
        x_export_timezone="Asia/Taipei",
    )))
    assert rows[0][-1] == "创建时间"
    assert rows[1][-1] == "2026-10-30 00:01:02"
    assert session.exec.call_count == 1

    item = SimpleNamespace(
        id=uuid.uuid4(), title="资源", description=None,
        owner_id=uuid.uuid4(), created_at=instant, updated_at=None,
    )
    item_row = item_to_csv_row(item, export_timezone("Asia/Taipei"))
    assert item_row[-2:] == ["2026-10-30 00:01:02", ""]


def test_user_export_joins_roles_and_posts_in_one_query(monkeypatch) -> None:
    monkeypatch.setattr(users_routes, "build_owner_data_scope_filter", lambda **_: True)
    instant = datetime(2026, 10, 29, 16, 1, 2, tzinfo=UTC)
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    user = SimpleNamespace(id=user_id, email="a@test.invalid", full_name="甲",
                           is_active=True, is_superuser=False, created_at=instant)
    membership = SimpleNamespace(department_id=uuid.uuid4())
    department = SimpleNamespace(code="D1")
    roles = [SimpleNamespace(id=uuid.uuid4(), code=code, sort=index, created_at=instant)
             for index, code in enumerate(("R1", "R2"))]
    posts = [SimpleNamespace(id=uuid.uuid4(), code=code, sort=index, created_at=instant)
             for index, code in enumerate(("P1", "P2"))]
    session = MagicMock()
    session.exec.return_value.all.return_value = [
        (user, membership, department, role, post) for role in reversed(roles) for post in reversed(posts)
    ]
    rows = asyncio.run(_csv_rows(users_routes.export_users(
        session, SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(tenant_id=tenant_id),
    )))
    assert len(rows) == 2
    assert rows[1][6:9] == ["D1", "R1,R2", "P1,P2"]
    assert session.exec.call_count == 1
