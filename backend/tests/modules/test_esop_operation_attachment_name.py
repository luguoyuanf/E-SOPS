import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.esop.public_api.dto import OperationAttachment, OperationInput
from app.modules.esop.routes import _validate_operation
from app.platform.public_api.files import FileAssetSummary


def _validate_name(name: str) -> OperationAttachment:
    file_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    body = OperationInput(
        name="装配",
        attachments=[OperationAttachment(file_id=file_id, name=name, kind="image", size=10)],
    )

    class Files:
        def get_accessible_file(self, *, tenant_id: uuid.UUID, file_id: uuid.UUID):
            return FileAssetSummary(id=file_id, original_name="原图.png", size=10, sha256="a" * 64)

    _validate_operation(body, SimpleNamespace(tenant_id=tenant_id), None, Files())
    return body.attachments[0]


def test_operation_rename_keeps_display_name_and_original_file_name():
    attachment = _validate_name("装配步骤.png")
    assert attachment.name == "装配步骤.png"
    assert attachment.original_name == "原图.png"


def test_operation_rename_cannot_change_file_extension():
    with pytest.raises(HTTPException) as error:
        _validate_name("装配步骤.pdf")
    assert error.value.status_code == 422
