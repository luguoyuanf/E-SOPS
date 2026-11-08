"""Derived operation/product lifecycle state without a substitute database."""

import copy
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

from app.modules.esop.infrastructure.models import Operation, ProductSopVersion
from app.modules.esop.product_sop import operation_states, snapshot_operations
from app.modules.esop.product_sop_routes import product_sop_statuses


def source(tenant, product, name="装配"):
    return Operation(tenant_id=tenant, product_id=product, name=name, code=uuid.uuid4().hex,
                     attachments=[{"file_id": str(uuid.uuid4()), "kind": "image", "name": "指导图.png", "size": 4}])


def test_new_operation_is_draft_or_pending_with_no_approved_content():
    operation = source(uuid.uuid4(), uuid.uuid4())
    snapshot = snapshot_operations([operation])
    draft = operation_states(snapshot, [], pending=False)[0]
    assert draft.status == "draft" and not draft.has_approved_version and not draft.is_deleted
    assert operation_states(snapshot, [], pending=True)[0].status == "pending"


def test_changed_content_is_draft_but_unchanged_operation_remains_approved_in_pending_product():
    tenant, product = uuid.uuid4(), uuid.uuid4()
    before = snapshot_operations([source(tenant, product), source(tenant, product, "检查")])
    after = copy.deepcopy(before)
    after[0]["name"] = "装配修订"
    after[1]["updated_at"] = "2030-01-01T00:00:00Z"
    states = operation_states(after, before, pending=True)
    assert [state.status for state in states] == ["pending", "approved"]
    assert all(state.has_approved_version for state in states)
    assert before[0]["name"] == "装配"
    assert operation_states(after, before, pending=False)[0].status == "draft"


def test_attachment_order_and_operation_order_are_authored_changes():
    tenant, product = uuid.uuid4(), uuid.uuid4()
    before = snapshot_operations([source(tenant, product), source(tenant, product, "检查")])
    after = copy.deepcopy(before)
    after[0]["attachments"].append(copy.deepcopy(before[1]["attachments"][0]))
    assert operation_states(after, before, pending=False)[0].status == "draft"
    assert [state.status for state in operation_states(list(reversed(before)), before, pending=False)] == ["draft", "draft"]


def test_deleted_approved_operation_stays_visible_but_deleted_new_draft_does_not():
    tenant, product = uuid.uuid4(), uuid.uuid4()
    before = snapshot_operations([source(tenant, product), source(tenant, product, "检查")])
    states = operation_states(before[:1], before, pending=False)
    assert [state.status for state in states] == ["approved", "pending_delete"]
    assert states[1].is_deleted and states[1].has_approved_version
    assert states[1].operation.id == uuid.UUID(before[1]["id"])
    assert operation_states([], [], pending=False) == []
    retained = operation_states(before[1:], before, pending=False)
    assert retained[0].status == "approved"
    inserted = snapshot_operations([source(tenant, product, "准备")]) + before
    assert [state.status for state in operation_states(inserted, before, pending=False)] == ["draft", "approved", "approved"]


def test_batch_product_summaries_use_two_scoped_queries_and_do_not_mark_empty_products_draft():
    tenant = uuid.uuid4()
    active, draft, pending, empty = [uuid.uuid4() for _ in range(4)]
    a, d, p = source(tenant, active), source(tenant, draft), source(tenant, pending)
    approved = ProductSopVersion(tenant_id=tenant, product_id=active, product_name="生效产品", version=1,
                                status="approved", created_by=uuid.uuid4(), operations=snapshot_operations([a]))
    submitted = ProductSopVersion(tenant_id=tenant, product_id=pending, product_name="待审产品", version=1,
                                 created_by=uuid.uuid4(), operations=snapshot_operations([p]))
    session = Mock()
    session.exec.side_effect = [SimpleNamespace(all=lambda: [a, d, p]), SimpleNamespace(all=lambda: [submitted, approved])]
    products = Mock()
    products.list.return_value = [SimpleNamespace(id=id) for id in (active, draft, pending, empty)]
    result = product_sop_statuses(SimpleNamespace(session=session, tenant_id=tenant), products)
    assert {row.product_id: row.status for row in result.items} == {active: "approved", draft: "draft", pending: "pending"}
    assert result.total == 3 and session.exec.call_count == 2
    for args in session.exec.call_args_list:
        compiled = args.args[0].compile()
        assert tenant in compiled.params.values()
        assert [active, draft, pending, empty] in compiled.params.values()


def test_batch_summaries_never_query_operations_without_visible_products():
    session, products = Mock(), Mock()
    products.list.return_value = []
    assert product_sop_statuses(SimpleNamespace(session=session, tenant_id=uuid.uuid4()), products).items == []
    session.exec.assert_not_called()
