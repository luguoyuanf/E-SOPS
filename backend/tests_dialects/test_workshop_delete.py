"""Deletion keeps referenced workshops and rejects foreign tenant records."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.esop.infrastructure.models import Workshop
from app.modules.esop.production_routes import delete_workshop


def test_empty_workshop_can_be_deleted():
    tenant = uuid.uuid4()
    workshop = Workshop(tenant_id=tenant, code="WS12345678", name="空车间")
    session = MagicMock()
    session.exec.side_effect = [MagicMock(first=lambda: workshop), MagicMock(first=lambda: None)]
    delete_workshop(SimpleNamespace(session=session, tenant_id=tenant), workshop.id)
    session.delete.assert_called_once_with(workshop)
    session.commit.assert_called_once()


@pytest.mark.parametrize("case,status", [("referenced", 409), ("foreign", 404), ("missing", 404)])
def test_workshop_delete_refuses_unsafe_targets(case, status):
    tenant = uuid.uuid4()
    workshop = Workshop(tenant_id=uuid.uuid4() if case == "foreign" else tenant, code="W1", name="车间")
    session = MagicMock()
    session.exec.side_effect = [MagicMock(first=lambda: None if case == "missing" else workshop), MagicMock(first=lambda: uuid.uuid4())]
    with pytest.raises(HTTPException) as error:
        delete_workshop(SimpleNamespace(session=session, tenant_id=tenant), workshop.id)
    assert error.value.status_code == status
    session.delete.assert_not_called()
    session.commit.assert_not_called()
