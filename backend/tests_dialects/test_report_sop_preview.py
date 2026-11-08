"""Report viewers can only read the immutable SOP and files referenced by their record."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.esop.infrastructure.models import ProductSopVersion, SopDocument
from app.modules.esop.report_routes import (
    report_sop_file_access,
    report_sop_preview,
    submit_web_report,
)
from tests_dialects.test_web_reporting import task  # noqa: F401


def test_report_preview_keeps_historical_attachments_and_rejects_other_files(task):  # noqa: F811
    report = submit_web_report(task.body, task.uow, task.principal, task.users)
    old_file, page, other_file = [uuid.uuid4() for _ in range(3)]
    sop = SopDocument(id=report.sop_id, tenant_id=task.uow.tenant_id, family_id=uuid.uuid4(),
                      product_id=task.release.product_id, operation_id=task.body.operation_id,
                      version=3, title='历史工序', status='approved', created_by=task.principal.id)
    attachment = {'file_id': str(old_file), 'display_pages': [str(page)], 'name': '历史文档', 'kind': 'word', 'size': 1}
    version = ProductSopVersion(tenant_id=task.uow.tenant_id, product_id=sop.product_id, product_name='历史产品',
                                version=3, status='approved', created_by=task.principal.id,
                                operations=[{'id': str(sop.operation_id), 'sop_id': str(sop.id), 'attachments': [attachment]}])
    latest = ProductSopVersion(tenant_id=task.uow.tenant_id, product_id=sop.product_id, product_name='历史产品',
                               version=4, status='approved', created_by=task.principal.id,
                               operations=[{'id': str(sop.operation_id), 'sop_id': str(uuid.uuid4()), 'attachments': []}])
    task.uow.session.add_all([sop, version, latest])
    task.uow.session.flush()
    files = SimpleNamespace(direct_read_url=lambda **kw: kw['file_id'])
    result = report_sop_preview(report.id, task.uow, files)
    assert result.version == 3
    assert result.attachments[0].file_id == old_file
    assert report_sop_file_access(report.id, page, task.uow, files) == page
    for missing in (other_file,):
        with pytest.raises(HTTPException) as error:
            report_sop_file_access(report.id, missing, task.uow, files)
        assert error.value.status_code == 404
    from sqlmodel import Session

    from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
    with Session(bind=task.uow.session.connection(), join_transaction_mode="create_savepoint") as session:
        with EsopTenantUnitOfWork(session, uuid.uuid4()) as foreign:
            with pytest.raises(HTTPException) as error:
                report_sop_preview(report.id, foreign, files)
            assert error.value.status_code == 404


def test_legacy_report_pages_and_missing_sop(task):  # noqa: F811
    report = submit_web_report(task.body, task.uow, task.principal, task.users)
    with pytest.raises(HTTPException) as error:
        report_sop_preview(report.id, task.uow, SimpleNamespace())
    assert error.value.status_code == 404
    file_id = uuid.uuid4()
    sop = SopDocument(id=report.sop_id, tenant_id=task.uow.tenant_id, family_id=uuid.uuid4(),
                      product_id=task.release.product_id, operation_id=task.body.operation_id,
                      version=3, title='旧版', created_by=task.principal.id,
                      pages=[{'file_id': str(file_id), 'sort': 0}])
    task.uow.session.add(sop)
    task.uow.session.flush()
    files = SimpleNamespace(get_accessible_file=lambda **kw: SimpleNamespace(id=file_id, content_type='image/png', original_name='旧图', size=1))
    assert report_sop_preview(report.id, task.uow, files).attachments[0].file_id == file_id
