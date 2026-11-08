"""ERP end-to-end HTTP contracts on an explicitly isolated MySQL 5.7 schema."""
import os
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from tests.mysql.test_http_acceptance import (
    authenticated_fixture,
    cleanup_fixture_sessions,
)

pytestmark = pytest.mark.skipif(os.environ.get("MYSQL_ERP_TEST") != "1", reason="isolated ERP test schema required")


def test_erp_http_tenant_permissions_stock_and_replay():
    assert settings.MYSQL_DB.startswith("esop_fva_test_erp_")
    from app.main import app
    prefix = "erp-" + uuid.uuid4().hex[:8]
    with TestClient(app) as client:
        root = authenticated_fixture(settings.FIRST_SUPERUSER)

        def call(method, path, body=None, token=root, status=200, key=None):
            headers = {"Authorization": "Bearer " + token}
            if key is not None:
                headers["Idempotency-Key"] = key
            response = client.request(method, "/api/v1" + path, json=body, headers=headers)
            assert response.status_code == status, (method, path, response.status_code, response.text[:1000])
            return response.json() if response.content else None

        plans = call("GET", "/tenants/plans")["items"]
        plan = next(plan for plan in plans if plan["is_default"])
        call("PUT", f'/platform/modules/plans/{plan["id"]}/erp', {"is_enabled": True})
        tenants, tokens = [], []
        for suffix in ("a", "b"):
            code = prefix + suffix
            email = code + "@example.com"
            tenants.append(call("POST", "/tenants", {"code": code, "name": "ERP MySQL 验收 " + suffix,
                "username": email, "password": uuid.uuid4().hex + "Aa9!", "plan_id": plan["id"]}))
            tokens.append(authenticated_fixture(email, code))
        token = tokens[0]
        menus = call("GET", "/menus/me", token=token)
        assert any((menu.get("permission_code") or "").startswith("erp:") for menu in menus)
        for path in ("/product-units", "/product-categories", "/products", "/warehouses", "/suppliers", "/customers", "/settlement-accounts", "/purchase-orders", "/purchase-ins", "/purchase-returns", "/sale-orders", "/sale-outs", "/sale-returns", "/stock-balances", "/stock-records", "/stock-ins", "/stock-outs", "/stock-moves", "/stock-checks", "/finance-payments", "/finance-receipts", "/statistics/summary"):
            call("GET", "/erp" + path, token=token)
        unit = call("POST", "/erp/product-units", {"code": "test-unit", "name": "验收专用单位"}, token=token, key=prefix + "-unit")
        replay = call("POST", "/erp/product-units", {"code": "test-unit", "name": "验收专用单位"}, token=token, key=prefix + "-unit")
        assert replay["id"] == unit["id"]
        call("POST", "/erp/product-units", {"code": "different", "name": "验收专用单位"}, token=token, key=prefix + "-unit", status=409)
        category = call("POST", "/erp/product-categories", {"code": "cat", "name": "分类"}, token=token, key=prefix + "-cat")
        product = call("POST", "/erp/products", {"code": "sku", "name": "MySQL验收产品", "unit_id": unit["id"], "category_id": category["id"]}, token=token, key=prefix + "-product")
        warehouse = call("POST", "/erp/warehouses", {"code": "wh", "name": "MySQL验收仓库", "is_default": True}, token=token, key=prefix + "-wh")
        # The tenant administrator must authorize its own warehouse explicitly.
        me = call("GET", "/users/me", token=token)
        call("PUT", f'/erp/warehouses/{warehouse["id"]}/users', {"user_ids": [me["id"]]}, token=token)
        call("GET", f'/erp/products/{product["id"]}', token=tokens[1], status=404)
        assert call("GET", "/erp/products", token=tokens[1])["total"] == 0
        incoming = call("POST", "/erp/stock-ins", {"items": [{"product_id": product["id"], "warehouse_id": warehouse["id"], "quantity": "10", "reference_price": "2.5"}]}, token=token, key=prefix + "-in")
        approved = call("POST", f'/erp/stock-ins/{incoming["id"]}/approve', {"expected_version": incoming["version"]}, token=token, key=prefix + "-approve-in")
        assert approved["status"] == "approved"
        def quantity():
            balances = call("GET", "/erp/stock-balances", token=token)["items"]
            return sum((Decimal(item["quantity"]) for item in balances), Decimal(0))
        assert quantity() == 10
        outgoing = call("POST", "/erp/stock-outs", {"items": [{"product_id": product["id"], "warehouse_id": warehouse["id"], "quantity": "3"}]}, token=token, key=prefix + "-out")
        approved_out = call("POST", f'/erp/stock-outs/{outgoing["id"]}/approve', {"expected_version": outgoing["version"]}, token=token, key=prefix + "-approve-out")
        assert quantity() == 7
        call("POST", f'/erp/stock-outs/{outgoing["id"]}/reverse', {"expected_version": approved_out["version"], "reason": "验收撤销"}, token=token, key=prefix + "-reverse-out")
        assert quantity() == 10
        call("POST", f'/erp/stock-ins/{incoming["id"]}/reverse', {"expected_version": approved["version"], "reason": "验收撤销"}, token=token, key=prefix + "-reverse-in")
        assert quantity() == 0
        supplier = call("POST", "/erp/suppliers", {"name": "验收供应商"}, token=token, key=prefix + "-supplier")
        customer = call("POST", "/erp/customers", {"name": "验收客户"}, token=token, key=prefix + "-customer")
        account = call("POST", "/erp/settlement-accounts", {"name": "验收账户", "account_no": "TEST-ACCOUNT-0001", "is_default": True}, token=token, key=prefix + "-account")
        def approve(kind, document):
            return call("POST", f'/erp/{kind}/{document["id"]}/approve', {"expected_version": document["version"]}, token=token, key=prefix + "-approve-" + document["id"])
        order = call("POST", "/erp/purchase-orders", {"supplier_id": supplier["id"], "items": [{"product_id": product["id"], "quantity": "5", "unit_price": "2"}]}, token=token, key=prefix + "-po")
        order = approve("purchase-orders", order)
        purchase_in = call("POST", "/erp/purchase-ins", {"purchase_order_id": order["id"], "items": [{"purchase_order_item_id": order["items"][0]["id"], "warehouse_id": warehouse["id"], "quantity": "5"}]}, token=token, key=prefix + "-pi")
        purchase_in = approve("purchase-ins", purchase_in)
        assert quantity() == 5
        payment = call("POST", "/erp/finance-payments", {"supplier_id": supplier["id"], "settlement_account_id": account["id"], "items": [{"source_type": "purchase_in", "source_document_id": purchase_in["id"], "settlement_amount": "10"}]}, token=token, key=prefix + "-payment")
        approve("finance-payments", payment)
        sale = call("POST", "/erp/sale-orders", {"customer_id": customer["id"], "items": [{"product_id": product["id"], "quantity": "2", "unit_price": "3"}]}, token=token, key=prefix + "-so")
        sale = approve("sale-orders", sale)
        sale_out = call("POST", "/erp/sale-outs", {"sale_order_id": sale["id"], "items": [{"sale_order_item_id": sale["items"][0]["id"], "warehouse_id": warehouse["id"], "quantity": "2"}]}, token=token, key=prefix + "-sale-out")
        sale_out = approve("sale-outs", sale_out)
        assert quantity() == 3
        receipt = call("POST", "/erp/finance-receipts", {"customer_id": customer["id"], "settlement_account_id": account["id"], "items": [{"source_type": "sale_out", "source_document_id": sale_out["id"], "settlement_amount": "6"}]}, token=token, key=prefix + "-receipt")
        approve("finance-receipts", receipt)
        reconciliation = call("POST", "/erp/reconciliation-runs", token=token, key=prefix + "-reconcile")
        assert reconciliation["status"] == "passed"
        for granularity in ("day", "month"):
            series = call("GET", f'/erp/statistics/time-series?type=purchase&start=2026-01-01&end=2026-12-31&granularity={granularity}', token=token)
            assert sum(Decimal(item["amount"]) for item in series["items"]) == 10
        # Removing module entitlement immediately removes ERP menus and rejects APIs.
        call("PUT", f'/platform/modules/plans/{plan["id"]}/erp', {"is_enabled": False})
        call("GET", "/erp/products", token=token, status=403)
        assert not any((menu.get("permission_code") or "").startswith("erp:") for menu in call("GET", "/menus/me", token=token))
        call("PUT", f'/platform/modules/plans/{plan["id"]}/erp', {"is_enabled": True})
        for tenant in tenants:
            call("PATCH", "/tenants/" + tenant["id"], {"is_active": False})
        cleanup_fixture_sessions()
