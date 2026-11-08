"""Fixed product-version publication contracts without replacing configured DB services."""

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.modules.esop import production_routes
from app.modules.esop.infrastructure.models import (
    ProductionLine,
    ProductionOrder,
    ProductionPlan,
    ProductSopVersion,
    SopDocument,
    Station,
    WorkRelease,
)
from app.modules.esop.production_routes import (
    _approved_version,
    _release_public,
    _validate_assignments,
    approved_product_versions,
    create_plan,
    publish_plan,
)
from app.modules.esop.public_api.production_dto import Assignment, PlanInput
from app.modules.esop.terminal_routes import _split_task_media


@pytest.fixture(autouse=True)
def skip_database_lock_for_mock_session(monkeypatch):
    monkeypatch.setattr(production_routes, "lock_product", lambda _uow, _product_id: None)


def fixture():
    tenant, product, actor, operation = (uuid.uuid4() for _ in range(4))
    order = ProductionOrder(tenant_id=tenant, product_id=product, code="ORDER", quantity=5, due_date=date(2026, 11, 1))
    line = ProductionLine(tenant_id=tenant, workshop_id=uuid.uuid4(), code="LINE", name="产线", station_count=1)
    station = Station(tenant_id=tenant, line_id=line.id, position=1, row=1, column=1)
    sop = SopDocument(tenant_id=tenant, family_id=uuid.uuid4(), product_id=product, operation_id=operation, status="approved", title="旧版指导书", created_by=actor, pages=[])
    version = ProductSopVersion(
        tenant_id=tenant, product_id=product, product_name="产品", version=1,
        status="approved", created_by=actor,
        operations=[{"id": str(operation), "code": "OP", "name": "已审核工序名称", "sop_id": str(sop.id), "attachments": []}],
    )
    registry = {(type(entity), entity.id): entity for entity in (order, line, station, sop, version)}
    session = Mock()
    session.get.side_effect = lambda model, key: registry.get((model, key))
    session.add.side_effect = lambda entity: registry.__setitem__((type(entity), entity.id), entity)
    session.exec.return_value.all.return_value = []
    session.exec.return_value.first.return_value = version
    uow = SimpleNamespace(session=session, tenant_id=tenant)
    body = PlanInput(order_id=order.id, line_id=line.id, product_sop_version_id=version.id,
                     assignments=[Assignment(operation_id=operation, station_id=station.id, sop_id=sop.id)])
    return uow, registry, body, version


def test_saved_draft_cannot_publish_old_version_after_new_approval():
    uow, registry, body, original = fixture()
    created = create_plan(uow, body, SimpleNamespace(id=original.created_by))
    assert created.product_sop_version_id == original.id
    assert created.code.startswith("PLAN") and len(created.code) == 12
    newer = ProductSopVersion(
        tenant_id=uow.tenant_id, product_id=original.product_id, product_name="产品", version=2,
        status="approved", created_by=original.created_by,
        operations=[{**original.operations[0], "name": "新版本修改的名称"}],
    )
    registry[(ProductSopVersion, newer.id)] = newer
    uow.session.exec.return_value.first.return_value = newer
    # A queued task follows the latest approved SOP when it starts.
    assert approved_product_versions(uow, original.product_id).items[0].id == newer.id
    assert registry[(ProductionPlan, created.id)].status == "draft"
    assert approved_product_versions(uow, original.product_id).total == 1
    with pytest.raises(HTTPException) as error:
        _approved_version(uow, original.product_id, original.id)
    assert error.value.status_code in {404, 422}


@pytest.mark.parametrize("status", ["pending", "draft", "rejected"])
def test_unapproved_whole_product_version_rejected(status):
    uow, _, body, version = fixture()
    version.status = status
    with pytest.raises(HTTPException) as error:
        _validate_assignments(uow, body, complete=True)
    assert error.value.status_code == 422
    uow.session.commit.assert_not_called()


def test_other_product_or_tenant_version_rejected():
    uow, _, body, version = fixture()
    version.product_id = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        _validate_assignments(uow, body, complete=True)
    assert error.value.status_code == 422
    version.tenant_id = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        _approved_version(uow, version.product_id, version.id)
    assert error.value.status_code == 404


def test_cannot_mix_operation_projection_from_another_version():
    uow, _, body, _ = fixture()
    body.assignments[0].sop_id = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        _validate_assignments(uow, body, complete=True)
    assert error.value.status_code == 422


def test_plan_can_start_with_only_staffed_operations():
    uow, registry, body, version = fixture()
    original_result = uow.session.exec.return_value
    def exec_with_bound_terminal(statement):
        if "terminal.station_id" in str(statement):
            return SimpleNamespace(all=lambda: [body.assignments[0].station_id])
        return original_result
    uow.session.exec.side_effect = exec_with_bound_terminal
    other_operation = uuid.uuid4()
    other_sop = SopDocument(
        tenant_id=uow.tenant_id, family_id=uuid.uuid4(), product_id=version.product_id,
        operation_id=other_operation, status="approved", title="未上班工序", created_by=version.created_by,
    )
    registry[(SopDocument, other_sop.id)] = other_sop
    version.operations.append({
        "id": str(other_operation), "code": "OP2", "name": "未上班工序", "sop_id": str(other_sop.id),
    })
    assert len(_validate_assignments(uow, body, complete=True)) == 1
    body.assignments = []
    with pytest.raises(HTTPException) as error:
        _validate_assignments(uow, body, complete=True)
    assert error.value.status_code == 422


def test_legacy_draft_requires_binding_but_legacy_release_stays_readable():
    uow, registry, body, version = fixture()
    old = ProductionPlan(tenant_id=uow.tenant_id, order_id=body.order_id, quantity=5, line_id=body.line_id, route_id=uuid.uuid4(), assignments=[])
    registry[(ProductionPlan, old.id)] = old
    with pytest.raises(HTTPException) as error:
        publish_plan(uow, SimpleNamespace(id=version.created_by), old.id)
    assert error.value.status_code == 422
    release = WorkRelease(tenant_id=uow.tenant_id, plan_id=old.id, order_id=body.order_id, line_id=body.line_id,
                          product_id=version.product_id, quantity=5, due_date=date(2026, 11, 1), assignments=[], published_by=version.created_by)
    public = _release_public(uow, release)
    assert public.product_sop_version_id is None and public.product_sop_version is None
    assert public.id == release.id


def test_terminal_videos_do_not_enter_image_pages():
    png = {"fileId": "png", "mimeType": "image/png", "url": "/png"}
    first = {"fileId": "mp4", "mimeType": "video/mp4", "url": "/mp4"}
    second = {"fileId": "webm", "mimeType": "VIDEO/WEBM", "url": "/webm"}
    pages, videos = _split_task_media([png, first, second])
    assert pages == [png] and videos == [first, second]
