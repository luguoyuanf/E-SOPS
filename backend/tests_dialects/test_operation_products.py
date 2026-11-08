"""Operation validation without replacing the configured database."""
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.modules.esop.infrastructure.models import OWNED_MODELS, Operation, ProductSopVersion
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.operation_media import resolve_operation_attachment
from app.modules.esop.product_sop import restore_version, snapshot_operations
from app.modules.esop.public_api.dto import OperationInput
from app.modules.esop.routes import create_operation, update_operation
from app.platform.public_api.files import FileAssetSummary


def _attachment(asset):
    session = Mock()
    session.exec.return_value.first.return_value = None
    return resolve_operation_attachment(SimpleNamespace(session=session, tenant_id=uuid.uuid4()), Mock(), asset)


@pytest.mark.parametrize(("extension", "kind"), [
    ("PNG", "image"), ("pdf", "pdf"), ("doc", "word"), ("docx", "word"),
    ("xls", "excel"), ("xlsx", "excel"), ("ppt", "ppt"), ("pptx", "ppt"),
    ("mp4", "video"), ("webm", "video"), ("mov", "video"),
])
def test_attachment_types(extension, kind):
    asset = FileAssetSummary(id=uuid.uuid4(), original_name=f"work.{extension}",
                            size=12, sha256="0" * 64)
    assert _attachment(asset).kind == kind


def test_product_files_and_update_boundaries():
    session, products, files = Mock(), Mock(), Mock()
    session.exec.return_value.one.return_value = -1
    session.exec.return_value.first.return_value = None
    uow = SimpleNamespace(session=session, tenant_id=uuid.uuid4())
    stored = FileAssetSummary(id=uuid.uuid4(), original_name="work.docx", size=12, sha256="0" * 64)
    products.exists.return_value = False
    with pytest.raises(HTTPException) as error:
        create_operation(uow, OperationInput(name="工序", product_id=uuid.uuid4()), products, files)
    assert error.value.status_code == 422
    session.add.assert_not_called()
    products.exists.return_value = True
    attachment = _attachment(stored)
    files.get_accessible_file.return_value = None
    for attachments in ([attachment], [attachment, attachment]):
        with pytest.raises(HTTPException) as error:
            create_operation(uow, OperationInput(name="工序", product_id=uuid.uuid4(), attachments=attachments), products, files)
        assert error.value.status_code == 422
    files.get_accessible_file.return_value = stored
    saved = create_operation(uow, OperationInput(name="工序", product_id=uuid.uuid4(), attachments=[attachment]), products, files)
    entity = session.add.call_args.args[0]
    assert entity.attachments[0]["file_id"] == str(stored.id)
    session.get.return_value = entity
    updated = update_operation(uow, entity.id, OperationInput(name="新版"), products, files)
    assert updated.product_id == saved.product_id and updated.attachments == saved.attachments
    session.reset_mock()
    session.get.return_value = entity
    with pytest.raises(HTTPException) as error:
        update_operation(uow, entity.id, OperationInput(name="wrong", product_id=None), products, files)
    assert error.value.status_code == 422
    files.get_accessible_file.return_value = None
    with pytest.raises(HTTPException) as error:
        update_operation(uow, entity.id, OperationInput(name="wrong", attachments=saved.attachments), products, files)
    assert error.value.status_code == 422
    assert entity.name == "新版"
    session.commit.assert_not_called()
    files.get_accessible_file.return_value = stored
    target_product = uuid.uuid4()
    moved = update_operation(uow, entity.id, OperationInput(name="新版", product_id=target_product), products, files)
    assert moved.product_id == target_product
    assert moved.id != entity.id and moved.code != entity.code
    assert moved.sort_order == 0 and moved.attachments == saved.attachments
    assert entity.product_id == saved.product_id and entity.is_deleted
    assert session.add_all.call_args.args[0][0] is entity
    with pytest.raises(HTTPException):
        _attachment(stored.model_copy(update={"original_name": "bad.exe"}))


def test_rebinding_keeps_source_operation_available_for_history_rollback():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in OWNED_MODELS])
    tenant_id, source_id, target_id = (uuid.uuid4() for _ in range(3))
    products, files = Mock(), Mock()
    products.exists.return_value = True
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant_id) as uow:
        original = Operation(tenant_id=tenant_id, product_id=source_id, code="PROC-ORIGINAL", name="装配")
        session.add(original)
        session.commit()
        historical = ProductSopVersion(
            tenant_id=tenant_id, product_id=source_id, product_name="原产品", version=1,
            status="approved", created_by=uuid.uuid4(), operations=snapshot_operations([original]),
        )
        moved = update_operation(
            uow, original.id, OperationInput(name="装配", product_id=target_id), products, files,
        )
        assert moved.id != original.id and moved.code != original.code
        assert session.get(Operation, original.id).is_deleted
        restore_version(uow, historical)
        assert not session.get(Operation, original.id).is_deleted
        assert session.get(Operation, moved.id).product_id == target_id
