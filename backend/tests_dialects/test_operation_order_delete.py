"""Operation move and reference-protected deletion; no substitute database."""
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.modules.esop.infrastructure.models import Operation
from app.modules.esop.public_api.dto import OperationMove
from app.modules.esop.routes import delete_operation, move_operation


def setup_operations():
    tenant, product = uuid.uuid4(), uuid.uuid4()
    operations = [Operation(tenant_id=tenant, product_id=product, code=f"P{i}", name=f"step {i}", sort_order=i) for i in range(3)]
    session = Mock()
    session.exec.return_value.first.return_value = None
    session.get.return_value = operations[2]
    session.exec.return_value.all.return_value = operations
    return SimpleNamespace(session=session, tenant_id=tenant), operations


def test_move_before_after_and_reject_unknown_target_without_writes():
    uow, operations = setup_operations()
    first, second, third = operations
    move_operation(uow, third.id, OperationMove(target_id=first.id))
    assert [item.id for item in sorted(operations, key=lambda item: item.sort_order)] == [third.id, first.id, second.id]
    uow.session.exec.return_value.all.return_value = sorted(operations, key=lambda item: item.sort_order)
    move_operation(uow, third.id, OperationMove(target_id=second.id, position="after"))
    assert [item.id for item in sorted(operations, key=lambda item: item.sort_order)] == [first.id, second.id, third.id]
    uow.session.reset_mock()
    with pytest.raises(HTTPException) as error:
        move_operation(uow, third.id, OperationMove(target_id=uuid.uuid4()))
    assert error.value.status_code == 422
    uow.session.commit.assert_not_called()


def result(*, first=None, items=()):
    value = Mock()
    value.first.return_value = first
    value.all.return_value = items
    return value


@pytest.mark.parametrize("reference", ["sop", "report", "route", "plan", "release", None])
def test_delete_guards_all_reference_owners(reference):
    uow, operations = setup_operations()
    operation = operations[2]
    operation.product_id = None  # Historical unbound operations retain reference-protected deletion.
    linked = SimpleNamespace(operation_ids=[str(operation.id)], assignments=[{"operation_id": str(operation.id)}])
    uow.session.exec.side_effect = [
        result(first=uuid.uuid4() if reference == "sop" else None),
        result(first=uuid.uuid4() if reference == "report" else None),
        result(items=[linked] if reference == "route" else []),
        result(items=[linked] if reference == "plan" else []),
        result(items=[linked] if reference == "release" else []),
    ]
    if reference:
        with pytest.raises(HTTPException) as error:
            delete_operation(uow, operation.id)
        assert error.value.status_code == 409
        uow.session.delete.assert_not_called()
        uow.session.commit.assert_not_called()
    else:
        delete_operation(uow, operation.id)
        uow.session.delete.assert_called_once_with(operation)
        uow.session.commit.assert_called_once()


def test_delete_foreign_tenant_is_not_found():
    uow, operations = setup_operations()
    uow.tenant_id = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        delete_operation(uow, operations[2].id)
    assert error.value.status_code == 404
    uow.session.delete.assert_not_called()
