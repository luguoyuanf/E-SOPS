"""Unified-unit contracts on an explicitly isolated MySQL ERP database."""

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.modules.erp.infrastructure.models import ProductUnit
from app.modules.erp.infrastructure.tenant_uow import (
    ErpTenantUnitOfWork,
    TenantScopeError,
)
from tests.mysql.test_http_acceptance import (
    authenticated_fixture,
    cleanup_fixture_sessions,
)

live = pytest.mark.skipif(
    os.environ.get("MYSQL_ERP_TEST") != "1",
    reason="isolated ERP test schema required",
)

COMMON_CODES = {
    "PCS", "EA", "SET", "UNIT", "PACK", "BOX", "ROLL", "SHEET", "PIECE",
    "STICK", "STRIP", "M", "M2", "KG", "G", "T", "L", "ML",
}


def test_platform_unit_permissions_are_module_owned_but_not_tenant_grantable():
    from app.modules.access import module_for_permission
    from app.platform.core.tenant_menu_access import tenant_permission_allowed

    for action in ("list", "create", "update"):
        permission = f"platform:erp-unit:{action}"
        assert module_for_permission(permission) == "erp"
        assert not tenant_permission_allowed(permission)
    assert tenant_permission_allowed("erp:product-unit:update")


@live
def test_platform_unit_http_provisioning_sync_read_only_and_custom_isolation():
    assert settings.DATABASE_TYPE == "mysql"
    assert settings.MYSQL_DB.startswith("esop_fva_test_erp_")
    from app.main import app

    prefix = "units-" + uuid.uuid4().hex[:10]
    tenants = []
    catalog_ids = []
    with TestClient(app) as client:
        root = authenticated_fixture(settings.FIRST_SUPERUSER)

        def call(method, path, body=None, *, token=root, status=200):
            response = client.request(
                method,
                "/api/v1" + path,
                json=body,
                headers={
                    "Authorization": "Bearer " + token,
                    "Idempotency-Key": uuid.uuid4().hex,
                },
            )
            assert response.status_code == status, (
                method, path, response.status_code, response.text[:1000]
            )
            return response.json() if response.content else None

        def units(token):
            return call("GET", "/erp/product-units?page_size=100", token=token)["items"]

        plan = next(
            plan for plan in call("GET", "/tenants/plans")["items"]
            if plan["is_default"]
        )
        call("PUT", f'/platform/modules/plans/{plan["id"]}/erp', {"is_enabled": True})

        def new_tenant(suffix):
            code = prefix + "-" + suffix
            email = code + "@example.com"
            tenant = call("POST", "/tenants", {
                "code": code,
                "name": "统一单位验收 " + suffix,
                "username": email,
                "password": uuid.uuid4().hex + "Aa9!",
                "plan_id": plan["id"],
            })
            tenants.append(tenant)
            return authenticated_fixture(email, code)

        try:
            catalog = call("GET", "/erp/platform-product-units?page_size=100")["items"]
            assert COMMON_CODES <= {item["code"] for item in catalog}
            a, b = new_tenant("a"), new_tenant("b")
            a_units, b_units = units(a), units(b)
            assert COMMON_CODES <= {item["code"] for item in a_units if item["is_platform"]}
            assert COMMON_CODES <= {item["code"] for item in b_units if item["is_platform"]}
            assert all(item["platform_unit_id"] for item in a_units if item["is_platform"])
            assert {item["id"] for item in a_units}.isdisjoint(item["id"] for item in b_units)
            menus = call("GET", "/menus/me", token=a)
            assert not any(
                (menu.get("permission_code") or "").startswith("platform:erp-unit:")
                for menu in menus
            )
            call("GET", "/erp/platform-product-units", token=a, status=403)
            call("POST", "/erp/platform-product-units", {
                "code": prefix, "name": prefix,
            }, token=a, status=403)
            call("PATCH", f'/erp/platform-product-units/{catalog[0]["id"]}', {
                "is_active": False,
            }, token=a, status=403)
            locked = next(item for item in a_units if item["code"] == "PCS")
            for body in ({"name": "恶意修改"}, {"is_active": False}, {"symbol": "bad"}):
                call("PATCH", f'/erp/product-units/{locked["id"]}', body, token=a, status=403)
            call("DELETE", f'/erp/product-units/{locked["id"]}', token=a, status=403)
            selected_root = authenticated_fixture(settings.FIRST_SUPERUSER, tenants[0]["code"])
            call("PATCH", f'/erp/product-units/{locked["id"]}', {
                "is_active": False,
            }, token=selected_root, status=403)
            call("DELETE", f'/erp/product-units/{locked["id"]}', token=selected_root, status=403)

            custom = call("POST", "/erp/product-units", {
                "code": prefix + "-custom", "name": prefix + "专用单位",
            }, token=a)
            assert not custom["is_platform"] and custom["platform_unit_id"] is None
            assert not any(item["id"] == custom["id"] for item in units(b))
            call("GET", f'/erp/product-units/{custom["id"]}', token=b, status=404)
            call("PATCH", f'/erp/product-units/{custom["id"]}', {"name": "越权"}, token=b, status=404)
            call("DELETE", f'/erp/product-units/{custom["id"]}', token=b, status=404)
            call("POST", "/erp/product-units", {
                "code": prefix + "-forged", "name": prefix + "伪造来源",
                "platform_unit_id": catalog[0]["id"],
            }, token=a, status=422)
            call("PATCH", f'/erp/product-units/{custom["id"]}', {
                "platform_unit_id": catalog[0]["id"],
            }, token=a, status=422)
            call("POST", "/erp/product-units", {
                "code": "PCS", "name": prefix + "重复编码",
            }, token=a, status=409)
            call("PATCH", f'/erp/product-units/{custom["id"]}', {
                "name": prefix + "专用单位已编辑",
            }, token=a)

            shared = call("POST", "/erp/platform-product-units", {
                "code": prefix + "-shared", "name": prefix + "平台单位", "symbol": "u",
            })
            catalog_ids.append(shared["id"])
            a_copy = next(item for item in units(a) if item["platform_unit_id"] == shared["id"])
            b_copy = next(item for item in units(b) if item["platform_unit_id"] == shared["id"])
            category = call("POST", "/erp/product-categories", {
                "code": prefix, "name": prefix + "分类",
            }, token=a)
            product = call("POST", "/erp/products", {
                "code": prefix, "name": prefix + "产品",
                "category_id": category["id"], "unit_id": a_copy["id"],
            }, token=a)
            assert product["unit_id"] == a_copy["id"]

            updated_name = prefix + "平台单位已编辑"
            call("PATCH", f'/erp/platform-product-units/{shared["id"]}', {
                "name": updated_name, "symbol": "updated",
            })
            for token, copy in ((a, a_copy), (b, b_copy)):
                row = call("GET", f'/erp/product-units/{copy["id"]}', token=token)
                assert row["name"] == updated_name and row["symbol"] == "updated"
            assert call("GET", f'/erp/products/{product["id"]}', token=a)["unit_id"] == a_copy["id"]

            # A collision in one tenant must roll back both the catalog and all copies.
            collision_name = prefix + "专用单位已编辑"
            call("PATCH", f'/erp/platform-product-units/{shared["id"]}', {
                "name": collision_name,
            }, status=409)
            for token, copy in ((a, a_copy), (b, b_copy)):
                assert call("GET", f'/erp/product-units/{copy["id"]}', token=token)["name"] == updated_name
            assert next(
                item for item in call("GET", "/erp/platform-product-units?page_size=100")["items"]
                if item["id"] == shared["id"]
            )["name"] == updated_name

            c = new_tenant("c")
            assert next(item for item in units(c) if item["platform_unit_id"] == shared["id"])["name"] == updated_name
            call("PATCH", f'/erp/platform-product-units/{shared["id"]}', {"is_active": False})
            for token in (a, b, c):
                assert not next(item for item in units(token) if item["platform_unit_id"] == shared["id"])["is_active"]
            call("POST", "/erp/products", {
                "code": prefix + "-inactive", "name": prefix + "停用单位产品",
                "category_id": category["id"], "unit_id": a_copy["id"],
            }, token=a, status=422)
            call("DELETE", f'/erp/product-units/{custom["id"]}', token=a, status=204)
        finally:
            for catalog_id in catalog_ids:
                call("PATCH", f"/erp/platform-product-units/{catalog_id}", {"is_active": False})
            for tenant in tenants:
                call("PATCH", "/tenants/" + tenant["id"], {"is_active": False})
            cleanup_fixture_sessions()


@live
@pytest.mark.parametrize("operation", ["edit", "delete", "detach", "attach", "forge"])
def test_platform_unit_copies_reject_direct_orm_writes(operation):
    assert settings.MYSQL_DB.startswith("esop_fva_test_erp_")
    from app.platform.core.tenancy_models import Tenant

    with Session(engine) as session:
        tenant_id = session.exec(select(Tenant.id).where(Tenant.code == "default")).one()
        with ErpTenantUnitOfWork(session, tenant_id):
            shared = session.exec(select(ProductUnit).where(ProductUnit.platform_unit_id.is_not(None))).first()
            assert shared is not None
            with pytest.raises(TenantScopeError):
                if operation == "edit":
                    shared.name = "非法直接更新"
                elif operation == "delete":
                    session.delete(shared)
                elif operation == "detach":
                    shared.platform_unit_id = None
                else:
                    custom = ProductUnit(tenant_id=tenant_id, code=uuid.uuid4().hex, name=uuid.uuid4().hex)
                    if operation == "attach":
                        session.add(custom)
                        session.flush()
                    custom.platform_unit_id = shared.platform_unit_id
                    session.add(custom)
                session.flush()
            session.rollback()


@live
@pytest.mark.parametrize("operation", ["create", "edit", "delete", "bulk_update", "core_update"])
def test_platform_catalog_requires_authorized_write_scope(operation):
    assert settings.MYSQL_DB.startswith("esop_fva_test_erp_")
    from sqlalchemy import update

    from app.modules.erp.infrastructure.models import PlatformProductUnit

    with Session(engine) as session:
        source = session.exec(select(PlatformProductUnit)).first()
        assert source is not None
        with pytest.raises(TenantScopeError):
            if operation == "create":
                session.add(PlatformProductUnit(code=uuid.uuid4().hex, name=uuid.uuid4().hex))
            elif operation == "edit":
                source.name = "未授权目录更新"
            elif operation == "delete":
                session.delete(source)
            elif operation == "bulk_update":
                session.exec(update(PlatformProductUnit).values(is_active=False))
            else:
                session.connection().execute(PlatformProductUnit.__table__.update().values(is_active=False))
            session.flush()
        session.rollback()


@live
def test_catalog_add_waiting_for_tenant_creation_sees_new_tenant_under_repeatable_read(monkeypatch):
    """Force the add command's auth snapshot to predate tenant commit.

    The new tenant holds the catalog lock before its row exists. The platform
    add waits on that lock, then must enumerate tenants using a current read.
    A snapshot SELECT would miss this tenant despite both requests succeeding.
    """
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from threading import Event

    from sqlalchemy import event
    from sqlalchemy.sql import visitors

    from app.main import app
    from app.modules.erp.infrastructure.models import PlatformProductUnit
    from app.modules.registry import MODULE_DEFINITIONS

    assert settings.MYSQL_DB.startswith("esop_fva_test_erp_")
    with engine.connect() as connection:
        assert connection.get_isolation_level() == "REPEATABLE READ"

    held, catalog_waiting, release = Event(), Event(), Event()
    definition = MODULE_DEFINITIONS["erp"]
    original_prepare = definition.lifecycle.prepare_tenant_creation
    assert original_prepare is not None

    def hold_before_tenant_insert(session):
        session.info["unit_test_tenant_creation"] = True
        original_prepare(session)
        held.set()
        assert release.wait(15), "Catalog command never reached the held lock"

    monkeypatch.setitem(MODULE_DEFINITIONS, "erp", replace(
        definition,
        lifecycle=replace(definition.lifecycle, prepare_tenant_creation=hold_before_tenant_insert),
    ))

    def observe_catalog_lock(connection, clause, _multiparams, _params, _options):
        session = connection.info.get("erp_scope_session")
        if (
            held.is_set()
            and session is not None
            and not session.info.get("unit_test_tenant_creation")
            and getattr(clause, "_for_update_arg", None) is not None
            and any(node in {PlatformProductUnit.__table__} for node in visitors.iterate(clause))
        ):
            catalog_waiting.set()

    prefix = "units-race-" + uuid.uuid4().hex[:8]
    tenant = shared = None
    with TestClient(app) as client:
        root = authenticated_fixture(settings.FIRST_SUPERUSER)

        def call(method, path, body=None):
            response = client.request(method, "/api/v1" + path, json=body, headers={
                "Authorization": "Bearer " + root,
                "Idempotency-Key": uuid.uuid4().hex,
            })
            assert response.status_code == 200, (path, response.status_code, response.text[:1000])
            return response.json()

        plan = next(plan for plan in call("GET", "/tenants/plans")["items"] if plan["is_default"])
        call("PUT", f'/platform/modules/plans/{plan["id"]}/erp', {"is_enabled": True})
        event.listen(engine, "before_execute", observe_catalog_lock)
        try:
            with ThreadPoolExecutor(max_workers=2) as workers:
                tenant_request = workers.submit(call, "POST", "/tenants", {
                    "code": prefix, "name": "单位并发初始化验收", "plan_id": plan["id"],
                })
                assert held.wait(15), "Tenant creation did not acquire the catalog lock"
                catalog_request = workers.submit(call, "POST", "/erp/platform-product-units", {
                    "code": prefix, "name": prefix + "并发单位",
                })
                try:
                    assert catalog_waiting.wait(15), "Catalog add did not overlap tenant creation"
                finally:
                    release.set()
                tenant = tenant_request.result(timeout=30)
                shared = catalog_request.result(timeout=30)
            selected_root = authenticated_fixture(settings.FIRST_SUPERUSER, prefix)
            response = client.get("/api/v1/erp/product-units?page_size=100", headers={
                "Authorization": "Bearer " + selected_root,
            })
            assert response.status_code == 200
            copies = [item for item in response.json()["items"] if item["platform_unit_id"] == shared["id"]]
            assert len(copies) == 1 and copies[0]["is_platform"]
            assert copies[0]["code"] == prefix and copies[0]["is_active"]
        finally:
            release.set()
            event.remove(engine, "before_execute", observe_catalog_lock)
            if shared:
                call("PATCH", f'/erp/platform-product-units/{shared["id"]}', {"is_active": False})
            if tenant:
                call("PATCH", f'/tenants/{tenant["id"]}', {"is_active": False})
            cleanup_fixture_sessions()
