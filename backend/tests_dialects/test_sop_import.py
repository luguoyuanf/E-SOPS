"""A workbook sheet becomes one draft operation and one preview page."""

import io
import uuid
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.modules.esop.infrastructure.models import (
    OWNED_MODELS,
    Operation,
    OperationMediaJob,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.operation_media import resolve_operation_attachment
from app.modules.esop.public_api.dto import SopImportRequest
from app.modules.esop.routes import import_product_sop
from app.modules.esop.sop_import import workbook_sheets
from app.platform.public_api.files import FileAssetSummary


def workbook(compression=ZIP_STORED):
    output = io.BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        archive.writestr("xl/workbook.xml", '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="变更履历表" sheetId="1" r:id="r1"/><sheet name="空白" sheetId="2" r:id="r2"/><sheet name="装配" sheetId="3" r:id="r3"/><sheet name="检验" sheetId="4" r:id="r4"/></sheets></workbook>''')
        archive.writestr("xl/_rels/workbook.xml.rels", '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/><Relationship Id="r3" Target="worksheets/sheet3.xml"/><Relationship Id="r4" Target="worksheets/sheet4.xml"/></Relationships>''')
        for index in (1, 3, 4):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData></worksheet>')
        archive.writestr("xl/worksheets/sheet2.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>')
    return output.getvalue()


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED])
def test_sheet_analysis_skips_empty_and_defaults_revision_off(compression):
    assert workbook_sheets(workbook(compression), "xlsx") == [
        {"index": 0, "name": "变更履历表", "selected": False},
        {"index": 1, "name": "装配", "selected": True},
        {"index": 2, "name": "检验", "selected": True},
    ]


def test_import_appends_operations_without_deleting_existing():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in OWNED_MODELS])
    tenant, product, uploader = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    file_id = uuid.uuid4()
    asset = FileAssetSummary(id=file_id, original_name="guidance.xlsx", size=100, sha256="0" * 64)
    files = Mock()
    files.get_accessible_file.return_value = asset
    files.read_file_bytes.return_value = workbook()
    products = Mock()
    products.exists.return_value = True
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant) as uow:
        existing = Operation(tenant_id=tenant, product_id=product, code="PROC-OLD", name="旧工序", sort_order=0)
        failed_job = OperationMediaJob(tenant_id=tenant, original_file_id=file_id,
                                       uploader_id=uploader, status="failed", attempts=3,
                                       error_message="转换服务暂时失败")
        session.add_all([existing, failed_job])
        session.commit()
        created = import_product_sop(uow, SimpleNamespace(id=uploader), files, products, product,
                                     SopImportRequest(file_id=file_id, sheet_indexes=[1, 2], mode="append"))
        assert [item.name for item in created] == ["装配", "检验"]
        assert [item.sort_order for item in created] == [1, 2]
        assert [item.attachments[0].sheet_index for item in created] == [1, 2]
        assert all(item.attachments[0].file_id == file_id for item in created)
        assert session.get(Operation, existing.id).is_deleted is False
        job = session.exec(select(OperationMediaJob).where(OperationMediaJob.original_file_id == file_id)).one()
        assert job.status == "queued" and job.attempts == 0 and job.error_message is None
        with pytest.raises(HTTPException) as error:
            import_product_sop(uow, SimpleNamespace(id=uploader), files, products, product,
                               SopImportRequest(file_id=file_id, sheet_indexes=[1], mode="append"))
        assert error.value.status_code == 409


def test_excel_attachment_uses_only_selected_preview_page():
    file_id, first, second, pdf = (uuid.uuid4() for _ in range(4))
    asset = FileAssetSummary(id=file_id, original_name="guidance.xlsx", size=100, sha256="0" * 64)
    session = Mock()
    session.exec.return_value.first.return_value = SimpleNamespace(display_file_id=pdf,
                                                                     page_file_ids=[str(first), str(second)])
    files = Mock()
    files.get_accessible_file.return_value = asset
    attachment = resolve_operation_attachment(SimpleNamespace(session=session, tenant_id=uuid.uuid4()), files,
                                              asset, sheet_index=1)
    assert attachment.display_pages == [second]
    assert attachment.sheet_index == 1
    with pytest.raises(HTTPException) as error:
        resolve_operation_attachment(SimpleNamespace(session=session, tenant_id=uuid.uuid4()), files,
                                     asset, sheet_index=2)
    assert error.value.status_code == 422


@pytest.mark.parametrize("limit", ["entry", "total", "ratio"])
def test_workbook_rejects_expansion_before_reading_xml(monkeypatch, limit):
    from app.modules.esop import sop_import

    data = workbook(ZIP_DEFLATED)
    if limit == "ratio":
        output = io.BytesIO(data)
        with ZipFile(output, "a", compression=ZIP_DEFLATED) as archive:
            archive.writestr("xl/sharedStrings.xml", b"0" * (4 * 1024 * 1024))
        data = output.getvalue()
        with ZipFile(io.BytesIO(data)) as archive:
            bomb = archive.getinfo("xl/sharedStrings.xml")
            assert bomb.file_size > bomb.compress_size * sop_import.MAX_ARCHIVE_COMPRESSION_RATIO
    else:
        with ZipFile(io.BytesIO(data)) as archive:
            sizes = [entry.file_size for entry in archive.infolist()]
        if limit == "entry":
            monkeypatch.setattr(sop_import, "MAX_ARCHIVE_ENTRY_BYTES", max(sizes) - 1)
        else:
            monkeypatch.setattr(sop_import, "MAX_ARCHIVE_EXPANDED_BYTES", sum(sizes) - 1)
    monkeypatch.setattr(ZipFile, "read", Mock(side_effect=AssertionError("Unsafe XML read")))
    with pytest.raises(HTTPException) as error:
        workbook_sheets(data, "xlsx")
    assert error.value.status_code == 422
