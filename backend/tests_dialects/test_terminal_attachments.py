"""Approved attachment boundaries and device/station file access."""
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.modules.esop import terminal_routes as routes
from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import (
    ALL_MODELS,
    OperationFileRendition,
    ProductionOrder,
    ProductSopVersion,
    SopDocument,
    Terminal,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.erp.public_api.products import ProductSummary


def test_approved_files_are_grouped_and_scoped_to_active_device(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS])
    tenant, other, product, operation, station, actor = (uuid.uuid4() for _ in range(6))
    original, first, second, video, model, resource, foreign = (uuid.uuid4() for _ in range(7))
    def attachment(fid, name, kind, pages=()):
        return {"file_id": str(fid), "name": name, "kind": kind, "size": 1,
                "display_pages": [str(x) for x in pages]}
    snapshot = [attachment(original, "指导书.xlsx", "excel", (first, second)),
                attachment(video, "操作.mp4", "video"),
                attachment(model, "机壳.glb", "model3d"),
                attachment(resource, "配件.bin", "model_resource")]
    assets = {fid: SimpleNamespace(original_name=f"{fid}.png", content_type="image/png")
              for fid in (original, first, second, video, model, resource)}
    assets[video] = SimpleNamespace(original_name="操作.mp4", content_type="video/mp4")
    files = SimpleNamespace(get_accessible_file=lambda *, tenant_id, file_id:
                            assets.get(file_id) if tenant_id == tenant else None)
    monkeypatch.setattr(routes, "get_file_asset_directory", lambda _session: files)
    monkeypatch.setattr(routes, "product_directory_for_tenant", lambda *_: SimpleNamespace(
        get=lambda _: ProductSummary(id=product, code="P1", name="产品1", model="M-100"), tree=lambda: ([], [])))
    monkeypatch.setattr("app.modules.esop.plan_scheduler.advance_due_plans", lambda _session: None)
    monkeypatch.setattr(routes, "preview_authorized_file", lambda **kwargs: str(kwargs["file_id"]))
    with Session(engine) as session:
        with EsopTenantUnitOfWork(session, tenant):
            terminal = Terminal(tenant_id=tenant, device_code="terminal-a", station_id=station)
            no_station = Terminal(tenant_id=tenant, device_code="terminal-b")
            order = ProductionOrder(tenant_id=tenant, code="order", product_id=product, quantity=1, due_date=date.today())
            sop = SopDocument(tenant_id=tenant, family_id=uuid.uuid4(), product_id=product,
                              operation_id=operation, status="approved", title="安装", created_by=actor,
                              pages=[{"file_id": str(fid), "sort": n} for n, fid in enumerate((first, second, video))])
            version = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品", version=1,
                                        status="approved", created_by=actor, operations=[{"id": str(operation),
                                        "name": "安装", "sop_id": str(sop.id), "attachments": snapshot}])
            release = WorkRelease(tenant_id=tenant, plan_id=uuid.uuid4(), order_id=order.id, line_id=uuid.uuid4(),
                                  product_id=product, product_sop_version_id=version.id, quantity=1,
                                  due_date=date.today(), published_by=actor,
                                  assignments=[{"operation_id": str(operation), "station_id": str(station)}])
            session.add_all([terminal, no_station, order, sop, version, release])
            session.commit()
            terminal_id, no_station_id, release_id = terminal.id, no_station.id, release.id
        device, unbound = DeviceIdentity(tenant, terminal_id), DeviceIdentity(tenant, no_station_id)
        task = routes.terminal_tasks(session, device)["list"][0]
        assert task["productModel"] == "M-100"
        assert [a["name"] for a in task["attachments"]] == ["指导书.xlsx", "操作.mp4", "机壳.glb"]
        assert [p["fileId"] for p in task["attachments"][0]["pages"]] == [str(first), str(second)]
        assert task["defaultAttachmentId"] is None
        assert [r["id"] for r in task["resources"]] == [str(resource)]
        assert len(task["pages"]) == 2 and len(task["videos"]) == 1
        assert routes.terminal_file(session, device, original) == str(original)
        assert routes.terminal_file(session, device, first) == str(first)
        assert routes.terminal_file(session, device, model) == str(model)
        assert routes.terminal_file(session, device, resource) == str(resource)
        for denied in (foreign,):
            with pytest.raises(HTTPException) as error:
                routes.terminal_file(session, device, denied)
            assert error.value.status_code == 404
        with pytest.raises(HTTPException) as error:
            routes.terminal_file(session, unbound, original)
        assert error.value.status_code == 404
        with pytest.raises(HTTPException) as error:
            routes.terminal_file(session, DeviceIdentity(other, terminal_id), original)
        assert error.value.status_code == 401
        with EsopTenantUnitOfWork(session, tenant):
            release = session.get(WorkRelease, release_id)
            release.is_active = False
            session.add(release)
            session.commit()
        with pytest.raises(HTTPException) as error:
            routes.terminal_file(session, device, model)
        assert error.value.status_code == 404


def test_legacy_and_incomplete_attachments_do_not_invent_boundaries():
    fid, page = uuid.uuid4(), uuid.uuid4()
    legacy = SimpleNamespace(pages=[{"file_id": str(page)}])
    files = SimpleNamespace(get_accessible_file=lambda **_: SimpleNamespace(original_name="page.png", content_type="image/png"))
    assert routes._attachment_payload({}, legacy, files, uuid.uuid4()) == ([], [])
    raw = {"_attachments": [{"file_id": str(fid), "name": "x.xlsx", "kind": "excel", "size": 1,
                             "display_pages": [str(page), str(uuid.uuid4())]}]}
    assert routes._attachment_payload(raw, legacy, files, uuid.uuid4()) == ([], [])


def test_catalog_lists_all_approved_tenant_products_and_scopes_files(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS])
    tenant, product, hidden_product, assigned_op, sibling_op, station, actor = (
        uuid.uuid4() for _ in range(7)
    )
    assigned_file, sibling_file, hidden_file = (uuid.uuid4() for _ in range(3))
    assets = {fid: SimpleNamespace(original_name="指导书.png", content_type="image/png", size=1)
              for fid in (assigned_file, sibling_file, hidden_file)}
    monkeypatch.setattr(routes, "get_file_asset_directory", lambda _session: SimpleNamespace(
        get_accessible_file=lambda *, tenant_id, file_id: assets.get(file_id) if tenant_id == tenant else None))
    category = uuid.uuid4()
    products = [
        ProductSummary(id=product, code="P1", name="产品1", category_id=category, model="M-100"),
        ProductSummary(id=hidden_product, code="P2", name="产品2", category_id=category),
    ]
    monkeypatch.setattr(routes, "product_directory_for_tenant", lambda *_: SimpleNamespace(
        tree=lambda: ([SimpleNamespace(id=category, name="电子产品")], products)))
    monkeypatch.setattr(routes, "preview_authorized_file", lambda **kwargs: str(kwargs["file_id"]))
    with Session(engine) as session:
        with EsopTenantUnitOfWork(session, tenant):
            terminal = Terminal(tenant_id=tenant, device_code="catalog-device", station_id=station)
            order = ProductionOrder(tenant_id=tenant, code="catalog-order", product_id=product,
                                    quantity=1, due_date=date.today())
            assigned_sop = SopDocument(tenant_id=tenant, family_id=uuid.uuid4(), product_id=product,
                                       operation_id=assigned_op, status="approved", title="装配", created_by=actor,
                                       pages=[{"file_id": str(assigned_file), "sort": 1}])
            sibling_sop = SopDocument(tenant_id=tenant, family_id=uuid.uuid4(), product_id=product,
                                      operation_id=sibling_op, status="approved", title="包装", created_by=actor,
                                      pages=[{"file_id": str(sibling_file), "sort": 1}])
            hidden_sop = SopDocument(tenant_id=tenant, family_id=uuid.uuid4(), product_id=hidden_product,
                                     operation_id=uuid.uuid4(), status="approved", title="隐藏产品", created_by=actor,
                                     pages=[{"file_id": str(hidden_file), "sort": 1}])
            version = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品1", version=1,
                                        status="approved", created_by=actor, operations=[
                                            {"id": str(assigned_op), "name": "装配", "sop_id": str(assigned_sop.id)},
                                            {"id": str(sibling_op), "name": "包装", "sop_id": str(sibling_sop.id)},
                                        ])
            hidden_version = ProductSopVersion(tenant_id=tenant, product_id=hidden_product, product_name="隐藏产品",
                                               version=1, status="approved", created_by=actor,
                                               operations=[{"id": str(hidden_sop.operation_id), "name": "隐藏",
                                                            "sop_id": str(hidden_sop.id)}])
            release = WorkRelease(tenant_id=tenant, plan_id=uuid.uuid4(), order_id=order.id,
                                  line_id=uuid.uuid4(), product_id=product, product_sop_version_id=version.id,
                                  quantity=1, due_date=date.today(), published_by=actor,
                                  assignments=[{"operation_id": str(assigned_op), "station_id": str(station)}])
            session.add_all([terminal, order, assigned_sop, sibling_sop, hidden_sop,
                             version, hidden_version, release])
            session.commit()
            terminal_id = terminal.id
        device = DeviceIdentity(tenant, terminal_id)
        catalog = routes.terminal_sop_catalog(session, device)["list"]
        assert [item["operationName"] for item in catalog] == ["装配", "包装", "隐藏"]
        assert catalog[1]["productCategoryName"] == "电子产品"
        assert catalog[1]["productModel"] == "M-100"
        assert routes.terminal_file(session, device, sibling_file) == str(sibling_file)
        assert routes.terminal_file(session, device, hidden_file) == str(hidden_file)
        with pytest.raises(HTTPException) as error:
            routes.terminal_file(session, device, uuid.uuid4())
        assert error.value.status_code == 404


def test_legacy_approved_pages_recover_exact_originals_and_list_remaining_pages(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS])
    tenant, product, operation, station, actor = (uuid.uuid4() for _ in range(5))
    original, first, second, image, unrelated, hidden = (uuid.uuid4() for _ in range(6))
    assets = {
        original: SimpleNamespace(original_name="指导书.docx", content_type=None, size=10),
        first: SimpleNamespace(original_name="指导书-第1页.png", content_type="image/png", size=1),
        second: SimpleNamespace(original_name="指导书-第2页.png", content_type="image/png", size=1),
        image: SimpleNamespace(original_name="照片.png", content_type="image/png", size=1),
        unrelated: SimpleNamespace(original_name="其他.pdf", content_type="application/pdf", size=10),
        hidden: SimpleNamespace(original_name="其他-第1页.png", content_type="image/png", size=1),
    }
    files = SimpleNamespace(get_accessible_file=lambda *, tenant_id, file_id:
                            assets.get(file_id) if tenant_id == tenant else None)
    monkeypatch.setattr(routes, "get_file_asset_directory", lambda _session: files)
    monkeypatch.setattr(routes, "product_directory_for_tenant", lambda *_: SimpleNamespace(
        get=lambda _: None, tree=lambda: ([], [])))
    monkeypatch.setattr("app.modules.esop.plan_scheduler.advance_due_plans", lambda _session: None)
    monkeypatch.setattr(routes, "preview_authorized_file", lambda **kwargs: str(kwargs["file_id"]))
    with Session(engine) as session:
        with EsopTenantUnitOfWork(session, tenant):
            terminal = Terminal(tenant_id=tenant, device_code="legacy-device", station_id=station)
            order = ProductionOrder(tenant_id=tenant, code="legacy-order", product_id=product,
                                    quantity=1, due_date=date.today())
            sop = SopDocument(tenant_id=tenant, family_id=uuid.uuid4(), product_id=product,
                              operation_id=operation, status="approved", title="旧版指导书", created_by=actor,
                              pages=[{"file_id": str(fid), "sort": n} for n, fid in enumerate((first, second, image))])
            version = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品", version=1,
                                        status="approved", created_by=actor, operations=[{"id": str(operation),
                                        "name": "装配", "sop_id": str(sop.id), "attachments": []}])
            release = WorkRelease(tenant_id=tenant, plan_id=uuid.uuid4(), order_id=order.id, line_id=uuid.uuid4(),
                                  product_id=product, product_sop_version_id=version.id, quantity=1,
                                  due_date=date.today(), published_by=actor,
                                  assignments=[{"operation_id": str(operation), "station_id": str(station)}])
            rendition = OperationFileRendition(tenant_id=tenant, original_file_id=original,
                                               display_file_id=original,
                                               page_file_ids=[str(first), str(second)])
            incomplete = OperationFileRendition(tenant_id=tenant, original_file_id=unrelated,
                                                display_file_id=unrelated,
                                                page_file_ids=[str(first), str(hidden)])
            session.add_all([terminal, order, sop, version, release, rendition, incomplete])
            session.commit()
            terminal_id = terminal.id
        device = DeviceIdentity(tenant, terminal_id)
        task = routes.terminal_tasks(session, device)["list"][0]
        assert [item["name"] for item in task["attachments"]] == ["指导书.docx", "照片.png"]
        assert [page["fileId"] for page in task["attachments"][0]["pages"]] == [str(first), str(second)]
        assert routes.terminal_file(session, device, original) == str(original)
        with pytest.raises(HTTPException) as error:
            routes.terminal_file(session, device, unrelated)
        assert error.value.status_code == 404
