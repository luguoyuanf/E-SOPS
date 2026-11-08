"""Plan-scoped progress and reference-protected order deletion."""
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.modules.esop.infrastructure.models import ProductionOrder
from app.modules.esop.production_routes import _plan_metrics, _plan_public, delete_order


def report(operation, inputs, good, bad):
    return SimpleNamespace(operation_id=operation, input_qty=inputs, good_qty=good, defect_qty=bad)


def test_metrics_count_parallel_stations_once_and_wait_for_slowest_operation():
    assignments = [{"operation_id": op} for op in ["first", "first", "last"]]
    reports = [report("first", 6, 5, 1), report("first", 4, 4, 0), report("last", 5, 4, 1), report("other", 99, 99, 0)]
    assert _plan_metrics(assignments, reports, 10) == (10, 4, 1, 50.0)
    assert _plan_metrics(assignments, reports[:2], 10) == (10, 0, 0, 0.0)
    assert _plan_metrics([], [], 10) == (0, 0, 0, 0.0)
    assert _plan_metrics([{"operation_id": "last"}], [report("last", 20, 19, 1)], 10) == (20, 19, 1, 100.0)


def test_public_metrics_query_only_current_plan_and_latest_release(monkeypatch):
    from app.modules.esop import production_routes
    plan_id, release_id = uuid.uuid4(), uuid.uuid4()
    public = SimpleNamespace()
    monkeypatch.setattr(production_routes.PlanPublic, "model_validate", lambda row: public)
    row = SimpleNamespace(id=plan_id, product_sop_version_id=None)
    latest = SimpleNamespace(id=release_id, version=2, assignments=[{"operation_id": "op"}], quantity=10)
    session = Mock()
    session.exec.return_value.all.side_effect = [[latest, SimpleNamespace(version=1)], [report("op", 6, 5, 1)]]
    result = _plan_public(SimpleNamespace(session=session), row)
    assert (result.input_total, result.good_total, result.bad_total, result.completion_rate) == (6, 5, 1, 60)
    queries = [str(call.args[0]) for call in session.exec.call_args_list]
    assert "plan_id" in queries[0] and "release_id" in queries[1]


@pytest.mark.parametrize("reference", [0, 1, 2, None])
def test_delete_order_protects_references(reference):
    tenant = uuid.uuid4()
    row = ProductionOrder(tenant_id=tenant, code="MO-TEST", product_id=uuid.uuid4(), quantity=10, due_date="2026-11-01")
    session = Mock()
    session.get.return_value = row
    results = []
    for index in range(3):
        result = Mock()
        result.first.return_value = uuid.uuid4() if reference == index else None
        results.append(result)
    session.exec.side_effect = results
    uow = SimpleNamespace(session=session, tenant_id=tenant)
    if reference is None:
        assert delete_order(uow, row.id) == {"deleted": True}
        session.delete.assert_called_once_with(row)
        session.commit.assert_called_once()
    else:
        with pytest.raises(HTTPException) as error:
            delete_order(uow, row.id)
        assert error.value.status_code == 409
        session.delete.assert_not_called()
        session.commit.assert_not_called()


def test_delete_foreign_order_rejected():
    row = SimpleNamespace(tenant_id=uuid.uuid4())
    session = Mock()
    session.get.return_value = row
    with pytest.raises(HTTPException) as error:
        delete_order(SimpleNamespace(session=session, tenant_id=uuid.uuid4()), uuid.uuid4())
    assert error.value.status_code == 404
    session.delete.assert_not_called()
