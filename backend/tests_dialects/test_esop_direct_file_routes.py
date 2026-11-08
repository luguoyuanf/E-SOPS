import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.modules.esop import product_sop_routes, routes


def test_direct_images_reject_type_spoofing_before_issuing_policy():
    files = Mock()
    with pytest.raises(HTTPException) as error:
        routes._begin_direct_image_upload(Mock(), Mock(), files, SimpleNamespace(name='photo.png', content_type='text/html'))
    assert error.value.status_code == 422
    files.begin_direct_upload.assert_not_called()


def test_direct_access_preserves_frozen_version_scope(monkeypatch):
    product, file_id, version_id, tenant = [uuid.uuid4() for _ in range(4)]
    monkeypatch.setattr(product_sop_routes, 'version_by_id', lambda *_: SimpleNamespace(product_id=product, operations=[{'attachments': [{'file_id': str(file_id)}]}]))
    files = Mock()
    uow = SimpleNamespace(tenant_id=tenant)
    product_sop_routes.product_instruction_direct_access(uow, files, product, file_id, version_id)
    files.direct_read_url.assert_called_once_with(tenant_id=tenant, file_id=file_id)
    with pytest.raises(HTTPException) as error:
        product_sop_routes.product_instruction_direct_access(uow, files, product, uuid.uuid4(), version_id)
    assert error.value.status_code == 404


def test_unsaved_editor_preview_checks_current_uploader():
    tenant, actor, file_id = [uuid.uuid4() for _ in range(3)]
    files = Mock()
    routes._editor_file_access(SimpleNamespace(tenant_id=tenant), SimpleNamespace(id=actor), files, file_id)
    files.direct_uploaded_read_url.assert_called_once_with(tenant_id=tenant, uploader_id=actor, file_id=file_id)
    files.direct_read_url.assert_not_called()


def test_existing_editor_reference_uses_operation_scope():
    tenant, actor, file_id = [uuid.uuid4() for _ in range(3)]
    files = Mock()
    operation = SimpleNamespace(attachments=[{'file_id': str(file_id), 'display_pages': []}])
    routes._editor_file_access(SimpleNamespace(tenant_id=tenant), SimpleNamespace(id=actor), files, file_id, operation)
    files.direct_read_url.assert_called_once_with(tenant_id=tenant, file_id=file_id)
    files.direct_uploaded_read_url.assert_not_called()
