"""Conversion/authorization boundaries without replacing online dependencies."""

import io
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from PIL import Image, ImageDraw

from app.api import deps
from app.modules.esop import operation_media as media
from app.platform.public_api.files import FileAssetSummary


def test_spreadsheet_content_crops_outer_white_but_preserves_internal_layout():
    image = Image.new("RGB", (600, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 100, 500, 400), outline="black")
    draw.rectangle((120, 160, 180, 200), fill="green")
    draw.text((100, 370), "Revision A", fill="black")
    content = io.BytesIO()
    image.save(content, format="PNG")
    blank = io.BytesIO()
    Image.new("RGB", (600, 500), "white").save(blank, format="PNG")
    pages = media._spreadsheet_content_pages([blank.getvalue(), content.getvalue()])
    assert len(pages) == 1
    result = Image.open(io.BytesIO(pages[0]))
    assert result.size == (429, 309)
    assert result.getpixel((44, 64)) == (0, 128, 0)
    assert result.getpixel((200, 200)) == (255, 255, 255)


def test_spreadsheet_all_empty_is_rejected():
    blank = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(blank, format="PNG")
    with pytest.raises(HTTPException) as error:
        media._spreadsheet_content_pages([blank.getvalue()])
    assert error.value.status_code == 422


@pytest.mark.parametrize("extension", ["xls", "xlsx"])
def test_spreadsheet_export_keeps_one_complete_sheet_per_page(monkeypatch, extension):
    calls = []
    monkeypatch.setattr(media.shutil, "which", lambda _: "/usr/bin/libreoffice")

    def run(command, _timeout):
        calls.append(command)
        if "--convert-to" in command:
            Path(command[-1]).with_suffix(".pdf").write_bytes(b"%PDF-fixture")
        else:
            image = Image.new("RGB", (100, 100), "white")
            ImageDraw.Draw(image).rectangle((10, 30, 90, 70), outline="black")
            image.save(command[-1] + "-1.png")

    monkeypatch.setattr(media, "_run", run)
    _, pages = media.convert_document(b"workbook fixture", extension)
    assert '"SinglePageSheets"' in calls[0][calls[0].index("--convert-to") + 1]
    assert Image.open(io.BytesIO(pages[0])).size == (89, 49)


def test_office_conversion_uses_private_profile_and_renders_terminal_pages(monkeypatch):
    calls = []
    monkeypatch.setattr(media.shutil, "which", lambda _: "/usr/bin/libreoffice")

    def run(command, timeout):
        calls.append((command, timeout))
        if "--convert-to" in command:
            Path(command[-1]).with_suffix(".pdf").write_bytes(b"%PDF-1.4\nfixture")
        else:
            Path(command[-1] + "-1.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")

    monkeypatch.setattr(media, "_run", run)
    pdf, pages = media.convert_document(b"office bytes", "docx")
    assert pdf.startswith(b"%PDF-") and len(pages) == 1
    assert any(a.startswith("-env:UserInstallation=file://") for a in calls[0][0])
    assert calls[1][0][0] == "pdftoppm"


def test_office_upload_persists_original_and_queues_conversion(monkeypatch):
    original = uuid.uuid4()
    store = Mock(return_value=original)
    monkeypatch.setattr(media, "upload_authorized_file", store)
    convert = Mock(side_effect=AssertionError("conversion must run in worker"))
    monkeypatch.setattr(media, "convert_document", convert)
    monkeypatch.setattr(media, "resolve_operation_attachment", lambda _uow, _files, _asset: media.OperationAttachment(file_id=original, name="work.xlsx", kind="excel", size=3))
    files = Mock()
    files.get_accessible_file.return_value = SimpleNamespace(original_name="work.xlsx")
    uow = SimpleNamespace(tenant_id=uuid.uuid4(), session=Mock())
    file = SimpleNamespace(filename="bad.xlsx", file=__import__("io").BytesIO(b"bad"))
    result = media.upload_operation_media(uow, SimpleNamespace(id=uuid.uuid4()), files, file)
    assert result.file_id == original
    assert uow.session.add.call_args.args[0].status == "queued"
    uow.session.commit.assert_called_once()
    convert.assert_not_called()


def test_canonical_rendition_requires_all_derived_files():
    tenant = uuid.uuid4()
    asset = FileAssetSummary(
        id=uuid.uuid4(), original_name="work.docx", size=12, sha256="0" * 64
    )
    rendition = SimpleNamespace(
        display_file_id=uuid.uuid4(), page_file_ids=[str(uuid.uuid4())]
    )
    session = Mock()
    session.exec.return_value.first.return_value = rendition
    uow = SimpleNamespace(session=session, tenant_id=tenant)
    files = Mock()
    files.get_accessible_file.return_value = asset
    result = media.resolve_operation_attachment(uow, files, asset)
    assert (
        result.display_file_id == rendition.display_file_id
        and len(result.display_pages) == 1
    )
    assert files.get_accessible_file.call_args.kwargs["tenant_id"] == tenant
    files.get_accessible_file.return_value = None
    with pytest.raises(HTTPException) as error:
        media.resolve_operation_attachment(uow, files, asset)
    assert error.value.status_code == 422


def test_any_permission_preserves_module_gate(monkeypatch):
    principal = SimpleNamespace(is_superuser=False)
    context = SimpleNamespace(tenant_id=uuid.uuid4())
    check = deps.require_any_module_access("esop", ("esop:sop:list", "esop:sop:review"))
    monkeypatch.setattr(
        deps, "evaluate_module_access", lambda **_: SimpleNamespace(allowed=True)
    )
    permission = Mock(
        side_effect=lambda **kwargs: kwargs["permission_code"] == "esop:sop:review"
    )
    monkeypatch.setattr(deps, "user_has_permission", permission)
    assert check(Mock(), principal, context) is principal
    permission.reset_mock()
    monkeypatch.setattr(
        deps,
        "evaluate_module_access",
        lambda **_: SimpleNamespace(allowed=False, error_code="TENANT_MODULE_DISABLED"),
    )
    with pytest.raises(HTTPException) as error:
        check(Mock(), principal, context)
    assert error.value.status_code == 403
    permission.assert_not_called()


def test_remote_preview_supports_chinese_rendition_filenames(monkeypatch):
    from app.platform.infra import storage_impl

    monkeypatch.setattr(storage_impl, '_stream_s3_object', lambda *_: iter([b'png']))
    response = storage_impl.get_file_download_response(
        storage_provider='oss', storage_path='test.png', filename='指导书-第1页.png',
        content_type='image/png',
    )
    assert response.headers['content-disposition'].startswith("attachment; filename*=UTF-8''")
    assert '%E6%8C%87' in response.headers['content-disposition']


def test_file_directory_binds_verified_device_tenant(monkeypatch):
    from contextlib import contextmanager

    from app.platform.infra import file_directory

    tenant = uuid.uuid4()
    scopes = []

    @contextmanager
    def scope(_session, tenant_id):
        scopes.append(tenant_id)
        yield

    monkeypatch.setattr(file_directory, 'PlatformTenantUnitOfWork', scope)
    session = Mock()
    session.exec.return_value.first.return_value = SimpleNamespace(
        id=uuid.uuid4(), original_name='指导书.png', content_type='image/png', size=12, sha256='0' * 64,
    )
    asset = file_directory.SqlFileAssetDirectory(session).get_accessible_file(tenant_id=tenant, file_id=uuid.uuid4())
    assert asset.original_name == '指导书.png' and scopes == [tenant]
