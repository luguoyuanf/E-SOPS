"""Durable conversion, failure visibility and explicit retry."""

import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.modules.esop import operation_media as media
from app.modules.esop import routes
from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import (
    Operation,
    OperationFileRendition,
    OperationMediaJob,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.platform.public_api.files import FileAssetSummary


def _database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[Operation.__table__, OperationFileRendition.__table__, OperationMediaJob.__table__])
    return engine


def test_worker_persists_ready_state_and_updates_saved_draft(monkeypatch):
    engine = _database()
    tenant, uploader, product, file_id = (uuid.uuid4() for _ in range(4))
    asset = FileAssetSummary(id=file_id, original_name="work.xlsx", size=3, sha256="0" * 64)
    files = Mock()
    files.get_accessible_file.return_value = asset
    files.read_file_bytes.return_value = b"xls"
    monkeypatch.setattr("app.platform.infra.file_directory.SqlFileAssetDirectory", lambda _session: files)
    monkeypatch.setattr(media, "convert_document", lambda _data, _ext: (b"%PDF-1.4", [b"png"]))

    def persist(uow, _principal, _files, original, _name, _extension, _converted, **_kwargs):
        uow.session.add(OperationFileRendition(tenant_id=tenant, original_file_id=original,
                        display_file_id=uuid.uuid4(), page_file_ids=[str(uuid.uuid4())]))
        uow.session.commit()

    monkeypatch.setattr(media, "_persist_rendition", persist)
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
        operation = Operation(tenant_id=tenant, product_id=product, code="STEP-1", name="工序",
                              attachments=[{"file_id": str(file_id), "name": "work.xlsx", "kind": "excel", "size": 3}])
        session.add_all([operation, OperationMediaJob(tenant_id=tenant, original_file_id=file_id, uploader_id=uploader)])
        session.commit()
        operation_id = operation.id
        media.run_media_conversion(session, tenant)
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
        assert session.exec(select(OperationMediaJob)).one().status == "ready"
        assert len(session.get(Operation, operation_id).attachments[0]["display_pages"]) == 1


def test_failed_conversion_can_be_requeued(monkeypatch):
    engine = _database()
    tenant, uploader, file_id = (uuid.uuid4() for _ in range(3))
    asset = FileAssetSummary(id=file_id, original_name="broken.xlsx", size=3, sha256="0" * 64)
    files = Mock()
    files.get_accessible_file.return_value = asset
    files.read_file_bytes.return_value = b"bad"
    monkeypatch.setattr("app.platform.infra.file_directory.SqlFileAssetDirectory", lambda _session: files)
    monkeypatch.setattr(media, "convert_document", Mock(side_effect=HTTPException(422, "文档转换失败")))
    monkeypatch.setattr(routes, "_editor_file_access", lambda *_args: None)
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
        session.add(OperationMediaJob(tenant_id=tenant, original_file_id=file_id, uploader_id=uploader))
        session.commit()
        media.run_media_conversion(session, tenant)
        failed = routes._media_status(SimpleNamespace(session=session, tenant_id=tenant), SimpleNamespace(id=uploader), files, file_id)
        assert failed.status == "failed" and failed.error_message == "文档转换失败"
        queued = routes._retry_media(SimpleNamespace(session=session, tenant_id=tenant), SimpleNamespace(id=uploader), files, file_id)
        assert queued.status == "queued"


def test_interrupted_job_is_reclaimed_and_transient_failure_retries(monkeypatch):
    engine = _database()
    tenant, uploader, file_id = (uuid.uuid4() for _ in range(3))
    asset = FileAssetSummary(id=file_id, original_name="work.xlsx", size=3, sha256="0" * 64)
    files = Mock()
    files.get_accessible_file.return_value = asset
    files.read_file_bytes.return_value = b"xls"
    monkeypatch.setattr("app.platform.infra.file_directory.SqlFileAssetDirectory", lambda _session: files)
    monkeypatch.setattr(media, "convert_document", Mock(side_effect=HTTPException(503, "服务暂不可用")))
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
        session.add(OperationMediaJob(tenant_id=tenant, original_file_id=file_id, uploader_id=uploader,
                    status="running", attempts=1, started_at=get_datetime_utc() - timedelta(minutes=11)))
        session.commit()
        media.run_media_conversion(session, tenant)
        job = session.exec(select(OperationMediaJob)).one()
        assert job.status == "queued" and job.attempts == 2
        media.run_media_conversion(session, tenant)
        session.refresh(job)
        assert job.status == "failed" and job.attempts == 3


def test_worker_does_not_claim_another_tenants_job(monkeypatch):
    engine = _database()
    owner, other, uploader, file_id = (uuid.uuid4() for _ in range(4))
    files = Mock()
    monkeypatch.setattr("app.platform.infra.file_directory.SqlFileAssetDirectory", lambda _session: files)
    with Session(engine) as session, EsopTenantUnitOfWork(session, owner):
        session.add(OperationMediaJob(tenant_id=owner, original_file_id=file_id, uploader_id=uploader))
        session.commit()
    with Session(engine) as session:
        media.run_media_conversion(session, other)
    assert not files.get_accessible_file.called
    with Session(engine) as session, EsopTenantUnitOfWork(session, owner):
        job = session.exec(select(OperationMediaJob)).one()
        assert job.status == "queued" and job.attempts == 0


def test_generated_preview_upload_has_platform_tenant_scope(monkeypatch):
    engine = _database()
    tenant, uploader, file_id = (uuid.uuid4() for _ in range(3))

    def upload(*, session, tenant_id, uploader_id, file):
        assert session.info.get("platform_tenant_id") == tenant_id == tenant
        assert uploader_id == uploader
        assert file.filename == "preview.pdf"
        return file_id

    monkeypatch.setattr(media, "upload_authorized_file", upload)
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant) as uow:
        assert media._store(uow, SimpleNamespace(id=uploader), b"pdf", "preview.pdf", "application/pdf") == file_id
        assert session.info.get("platform_tenant_id") is None
