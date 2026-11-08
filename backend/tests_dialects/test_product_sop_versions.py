"""Product-level snapshots, projections and draft restoration without a substitute DB."""

import copy
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.modules.esop import product_sop_routes
from app.modules.esop.infrastructure.models import (
    Operation,
    ProductSopVersion,
    SopDocument,
)
from app.modules.esop.product_sop import (
    approve_version,
    comparable_snapshot,
    ensure_product_editable,
    restore_version,
    snapshot_operations,
    submission_pages,
    validate_submission,
    version_by_id,
)
from app.modules.esop.public_api.dto import OperationAttachment, SopReject
from app.platform.public_api.files import FileAssetSummary


def operation(tenant, product, name="装配"):
    return Operation(tenant_id=tenant, product_id=product, code=uuid.uuid4().hex, name=name,
                     attachments=[{"file_id": str(uuid.uuid4()), "kind": "image", "name": "work.png", "size": 4}])


def test_snapshot_content_ignores_timestamps_projection_ids_and_sort_gaps_but_keeps_order():
    tenant, product = uuid.uuid4(), uuid.uuid4()
    a, b = operation(tenant, product), operation(tenant, product, "包装")
    before = snapshot_operations([a, b])
    after = copy.deepcopy(before)
    after[0].update(updated_at="another time", sort_order=99, sop_id=str(uuid.uuid4()))
    assert comparable_snapshot(before) == comparable_snapshot(after)
    assert comparable_snapshot(before) != comparable_snapshot(list(reversed(after)))
    after[0]["name"] = "已修改"
    assert comparable_snapshot(before) != comparable_snapshot(after)


def test_legacy_approved_attachment_without_optional_metadata_is_not_a_draft():
    tenant, product = uuid.uuid4(), uuid.uuid4()
    current = snapshot_operations([operation(tenant, product)])
    approved = copy.deepcopy(current)
    approved[0]["attachments"][0].pop("original_name")
    assert comparable_snapshot(current) == comparable_snapshot(approved)
    assert [state.status for state in product_sop_routes.operation_states(current, approved, pending=False)] == ["approved"]
    approved[0]["attachments"][0]["file_id"] = str(uuid.uuid4())
    assert comparable_snapshot(current) != comparable_snapshot(approved)


def test_display_pages_are_frozen_as_terminal_png_pages_and_video_original():
    original, pdf, first, second, video = [uuid.uuid4() for _ in range(5)]
    pages = submission_pages([
        {"file_id": str(original), "kind": "word", "name": "x" * 220 + ".docx", "size": 32,
         "display_file_id": str(pdf), "display_pages": [str(first), str(second)]},
        {"file_id": str(video), "kind": "video", "name": "work.mp4", "size": 32},
    ])
    assert [p["file_id"] for p in pages] == [str(first), str(second), str(video)]
    assert [p["sort"] for p in pages] == [0, 1, 2]
    assert len(pages[0]["caption"]) == 200


def test_pending_product_is_locked_before_mutating():
    uow = SimpleNamespace(session=Mock(), tenant_id=uuid.uuid4())
    uow.session.get.return_value = Mock()
    uow.session.exec.return_value.first.return_value = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        ensure_product_editable(uow, uuid.uuid4())
    assert error.value.status_code == 409
    uow.session.add.assert_not_called()
    uow.session.commit.assert_not_called()


def test_foreign_version_is_not_visible_even_from_identity_map():
    uow = SimpleNamespace(session=Mock(), tenant_id=uuid.uuid4())
    uow.session.get.return_value = SimpleNamespace(tenant_id=uuid.uuid4())
    with pytest.raises(HTTPException) as error:
        version_by_id(uow, uuid.uuid4())
    assert error.value.status_code == 404


def test_approval_creates_fixed_compatibility_sop_without_mutating_snapshot_source():
    tenant, product, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    source = operation(tenant, product)
    version = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品",
                                version=1, created_by=actor, operations=snapshot_operations([source]))
    before = copy.deepcopy(version.operations)
    uow = SimpleNamespace(session=Mock(), tenant_id=tenant)
    uow.session.exec.return_value.all.return_value = []
    approve_version(uow, version, actor)
    projected = [args.args[0] for args in uow.session.add.call_args_list if isinstance(args.args[0], SopDocument)]
    assert len(projected) == 1
    assert projected[0].status == "approved" and projected[0].operation_id == source.id
    assert version.operations[0]["sop_id"] == str(projected[0].id)
    assert version.status == "approved" and version.reviewed_by == actor
    assert "sop_id" not in before[0]
    source.name = "随后编辑草稿"
    assert version.operations[0]["name"] == "装配"
    assert projected[0].title == "装配"


def test_rollback_revives_original_ids_and_soft_deletes_new_steps_only_in_draft():
    tenant, product = uuid.uuid4(), uuid.uuid4()
    old, extra = operation(tenant, product), operation(tenant, product, "新增步骤")
    version = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品", version=1,
                                created_by=uuid.uuid4(), status="approved", operations=snapshot_operations([old]))
    old.name, old.is_deleted = "已编辑", True
    uow = SimpleNamespace(session=Mock(), tenant_id=tenant)
    uow.session.exec.return_value.all.return_value = [old, extra]
    uow.session.get.return_value = old
    frozen = copy.deepcopy(version.operations)
    restore_version(uow, version)
    assert old.name == "装配" and not old.is_deleted
    assert extra.is_deleted
    assert version.operations == frozen and version.status == "approved"
    uow.session.delete.assert_not_called()


def test_reject_restores_approved_working_operations_and_keeps_rejected_snapshot(monkeypatch):
    tenant, product, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    old, extra = operation(tenant, product), operation(tenant, product, "新增步骤")
    base = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品", version=1,
                             created_by=actor, status="approved", operations=snapshot_operations([old]))
    old.name = "待审修改"
    pending = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品", version=2,
                                created_by=actor, base_version_id=base.id, operations=snapshot_operations([old, extra]))
    frozen = copy.deepcopy(pending.operations)
    uow = SimpleNamespace(session=Mock(), tenant_id=tenant)
    uow.session.exec.return_value.all.return_value = [old, extra]
    uow.session.get.return_value = old
    monkeypatch.setattr(product_sop_routes, "_pending_for_review", lambda *_: pending)
    monkeypatch.setattr(product_sop_routes, "version_by_id", lambda *_, **__: base)

    result = product_sop_routes.reject_product_sop(uow, SimpleNamespace(id=actor), pending.id,
                                                     SopReject(reason="请修改"))
    assert result.status == "rejected" and result.review_note == "请修改"
    assert pending.operations == frozen and base.status == "approved"
    assert old.name == "装配" and not old.is_deleted and extra.is_deleted
    uow.session.commit.assert_called_once()


def test_reject_first_submission_keeps_draft_because_no_approved_version(monkeypatch):
    tenant, product, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    current = operation(tenant, product)
    pending = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品", version=1,
                                created_by=actor, operations=snapshot_operations([current]))
    uow = SimpleNamespace(session=Mock(), tenant_id=tenant)
    monkeypatch.setattr(product_sop_routes, "_pending_for_review", lambda *_: pending)
    result = product_sop_routes.reject_product_sop(uow, SimpleNamespace(id=actor), pending.id,
                                                     SopReject(reason="请修改"))
    assert result.status == "rejected" and result.base_version_id is None
    assert current.name == "装配" and not current.is_deleted
    uow.session.exec.assert_not_called()


def test_discard_draft_restores_approved_operations_without_changing_version(monkeypatch):
    tenant, product = uuid.uuid4(), uuid.uuid4()
    old, added = operation(tenant, product), operation(tenant, product, "草稿新增")
    approved = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品", version=1,
                                 created_by=uuid.uuid4(), status="approved", operations=snapshot_operations([old]))
    old.name = "草稿修改"
    uow = SimpleNamespace(session=Mock(), tenant_id=tenant)
    uow.session.exec.return_value.all.return_value = [old, added]
    uow.session.get.return_value = old
    monkeypatch.setattr(product_sop_routes, "ensure_product_editable", Mock())
    monkeypatch.setattr(product_sop_routes, "product_versions", lambda *_args, **_kwargs: [approved])
    monkeypatch.setattr(product_sop_routes, "current_operations", lambda *_: [item for item in (old, added) if not item.is_deleted])
    products = SimpleNamespace(get=lambda _: SimpleNamespace(name="产品"))

    result = product_sop_routes.discard_product_sop_draft(uow, products, product)

    assert result.status == "approved" and not result.dirty
    assert old.name == "装配" and not old.is_deleted and added.is_deleted
    assert approved.status == "approved" and approved.version == 1
    uow.session.commit.assert_called_once()


def test_discard_first_draft_soft_deletes_only_current_operations(monkeypatch):
    tenant, product = uuid.uuid4(), uuid.uuid4()
    draft = operation(tenant, product)
    uow = SimpleNamespace(session=Mock(), tenant_id=tenant)
    monkeypatch.setattr(product_sop_routes, "ensure_product_editable", Mock())
    monkeypatch.setattr(product_sop_routes, "product_versions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(product_sop_routes, "current_operations", lambda *_: [] if draft.is_deleted else [draft])
    products = SimpleNamespace(get=lambda _: SimpleNamespace(name="产品"))

    result = product_sop_routes.discard_product_sop_draft(uow, products, product)

    assert draft.is_deleted
    assert result.status == "empty" and not result.dirty and result.current_operations == []
    uow.session.add.assert_called_once_with(draft)
    uow.session.commit.assert_called_once()


def test_discard_draft_rejects_unchanged_approved_version(monkeypatch):
    tenant, product = uuid.uuid4(), uuid.uuid4()
    existing = operation(tenant, product)
    approved = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品", version=1,
                                 created_by=uuid.uuid4(), status="approved", operations=snapshot_operations([existing]))
    uow = SimpleNamespace(session=Mock(), tenant_id=tenant)
    monkeypatch.setattr(product_sop_routes, "ensure_product_editable", Mock())
    monkeypatch.setattr(product_sop_routes, "product_versions", lambda *_args, **_kwargs: [approved])
    monkeypatch.setattr(product_sop_routes, "current_operations", lambda *_: [existing])

    with pytest.raises(HTTPException) as error:
        product_sop_routes.discard_product_sop_draft(uow, SimpleNamespace(get=lambda _: SimpleNamespace(name="产品")), product)
    assert error.value.status_code == 409
    uow.session.commit.assert_not_called()


def test_discard_draft_rejects_empty_first_workspace(monkeypatch):
    product = uuid.uuid4()
    uow = SimpleNamespace(session=Mock(), tenant_id=uuid.uuid4())
    monkeypatch.setattr(product_sop_routes, "ensure_product_editable", Mock())
    monkeypatch.setattr(product_sop_routes, "product_versions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(product_sop_routes, "current_operations", lambda *_: [])

    with pytest.raises(HTTPException) as error:
        product_sop_routes.discard_product_sop_draft(uow, SimpleNamespace(get=lambda _: SimpleNamespace(name="产品")), product)
    assert error.value.status_code == 409
    uow.session.commit.assert_not_called()


@pytest.mark.parametrize("kind", ["pdf", "word", "excel", "ppt"])
def test_submit_rejects_office_or_pdf_without_terminal_rendition(monkeypatch, kind):
    from app.modules.esop import operation_media

    tenant, product = uuid.uuid4(), uuid.uuid4()
    source = operation(tenant, product)
    asset = FileAssetSummary(id=uuid.UUID(source.attachments[0]["file_id"]), original_name="source.docx", size=4, sha256="0" * 64)
    files = Mock()
    files.get_accessible_file.return_value = asset
    monkeypatch.setattr(operation_media, "resolve_operation_attachment", lambda *_, **__: OperationAttachment(file_id=asset.id, name=asset.original_name, kind=kind, size=4))
    uow = SimpleNamespace(session=Mock(), tenant_id=tenant)
    with pytest.raises(HTTPException) as error:
        validate_submission(uow, [source], files)
    assert error.value.status_code == 422
    uow.session.add.assert_not_called()


def test_submit_checks_all_derived_file_ownership_before_accepting(monkeypatch):
    from app.modules.esop import operation_media

    tenant, product = uuid.uuid4(), uuid.uuid4()
    source = operation(tenant, product)
    original = uuid.UUID(source.attachments[0]["file_id"])
    page = uuid.uuid4()
    asset = FileAssetSummary(id=original, original_name="source.pdf", size=4, sha256="0" * 64)
    files = Mock()
    files.get_accessible_file.side_effect = [asset, None]
    monkeypatch.setattr(operation_media, "resolve_operation_attachment", lambda *_, **__: OperationAttachment(
        file_id=original, name="source.pdf", kind="pdf", size=4, display_file_id=page, display_pages=[page],
    ))
    with pytest.raises(HTTPException) as error:
        validate_submission(SimpleNamespace(session=Mock(), tenant_id=tenant), [source], files)
    assert error.value.status_code == 422
    assert files.get_accessible_file.call_args.kwargs["tenant_id"] == tenant


def test_preview_is_restricted_to_the_chosen_snapshot_and_product(monkeypatch):
    from app.modules.esop import product_sop_routes

    tenant, product = uuid.uuid4(), uuid.uuid4()
    source = operation(tenant, product)
    version = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品", version=1,
                                created_by=uuid.uuid4(), operations=snapshot_operations([source]))
    uow = SimpleNamespace(session=Mock(), tenant_id=tenant)
    uow.session.get.return_value = version
    preview = Mock()
    monkeypatch.setattr(product_sop_routes, "preview_authorized_file", preview)
    with pytest.raises(HTTPException) as error:
        product_sop_routes.preview_product_instruction(uow, uuid.uuid4(), uuid.uuid4(), version.id)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        product_sop_routes.preview_product_instruction(uow, product, uuid.uuid4(), version.id)
    assert error.value.status_code == 404
    preview.assert_not_called()
    original = uuid.UUID(source.attachments[0]["file_id"])
    product_sop_routes.preview_product_instruction(uow, product, original, version.id)
    preview.assert_called_once_with(session=uow.session, tenant_id=tenant, file_id=original)


def test_review_list_resolves_only_visible_reviewer_names():
    from app.core.clock import get_datetime_utc

    actor = uuid.uuid4()
    versions = [ProductSopVersion(
        tenant_id=uuid.uuid4(), product_id=uuid.uuid4(), product_name="产品", version=i + 1,
        status="approved", operations=[], created_by=actor, submitted_at=get_datetime_utc(),
        reviewed_by=reviewer,
    ) for i, reviewer in enumerate([actor, None])]
    session = Mock()
    session.exec.return_value.all.return_value = versions
    users = Mock()
    users.get_users.return_value = [SimpleNamespace(id=actor, full_name="审核员", email=None)]
    result = product_sop_routes.list_sop_review_versions(SimpleNamespace(session=session), users, "reviewed")
    assert [item.reviewer_name for item in result.items] == ["审核员", None]
    users.get_users.assert_called_once_with({actor})


@pytest.mark.parametrize("status", ["approved", "rejected", "reviewed", "pending"])
def test_review_list_filters_product_name_and_status_before_pagination(status):
    session, users = Mock(), Mock()
    session.exec.return_value.all.return_value = []
    users.get_users.return_value = []
    result = product_sop_routes.list_sop_review_versions(
        SimpleNamespace(session=session), users, status, page=2, page_size=1, keyword="  产品%_  ",
    )
    statement = session.exec.call_args.args[0]
    compiled = statement.compile()
    assert "product_name LIKE" in str(compiled)
    assert "产品/%/_" in compiled.params.values()
    assert (["approved", "rejected"] if status == "reviewed" else status) in compiled.params.values()
    assert result.total == 0 and result.items == []


def test_review_list_rejects_unknown_status():
    with pytest.raises(HTTPException) as error:
        product_sop_routes.list_sop_review_versions(Mock(), Mock(), "unknown")
    assert error.value.status_code == 422
