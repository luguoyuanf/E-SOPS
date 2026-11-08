"""Order quota and approved supplement rules on the ESOP test database."""

import uuid

import pytest
from fastapi import HTTPException

from app.modules.esop.infrastructure.models import (
    ProductionPlan,
    ProductionReport,
    WorkRelease,
)
from app.modules.esop.production_routes import (
    _order_production_status,
    _require_order_capacity,
    create_order_supplement,
    order_allocation,
    review_order_supplement,
)
from app.modules.esop.public_api.production_dto import SupplementInput, SupplementReview
from app.modules.esop.report_routes import submit_web_report
from tests_dialects.test_web_reporting import task as task


def test_order_quota_allows_split_but_rejects_duplicate_full_plan(task):
    with pytest.raises(HTTPException) as error:
        _require_order_capacity(task.uow, task.order.id, 1)
    assert error.value.status_code == 409
    task.plan.quantity = 1
    task.release.quantity = 1
    task.uow.session.flush()
    assert _require_order_capacity(task.uow, task.order.id, 1).id == task.order.id
    with pytest.raises(HTTPException) as error:
        _require_order_capacity(task.uow, task.order.id, 2)
    assert error.value.status_code == 409


def test_two_operations_each_use_full_order_quantity_and_complete_together(task):
    first = str(task.plan.assignments[0]['operation_id'])
    second = uuid.uuid4()
    task.order.operation_ids = [first, str(second)]
    task.uow.session.add(task.order)
    task.uow.session.flush()
    assert _require_order_capacity(task.uow, task.order.id, 2, operation_ids={str(second)})
    capacities = {item['operation_id']: item for item in order_allocation(task.uow, task.order.id).operations}
    assert capacities[first]['remaining_quantity'] == 0
    assert capacities[first]['plan_codes'] == [task.plan.code]
    assert capacities[str(second)]['remaining_quantity'] == 2
    with pytest.raises(HTTPException):
        _require_order_capacity(task.uow, task.order.id, 1, operation_ids={first})

    assignment = {**task.plan.assignments[0], 'operation_id': str(second)}
    plan = ProductionPlan(tenant_id=task.order.tenant_id, code='SECOND-OP', order_id=task.order.id,
                          quantity=2, line_id=task.plan.line_id, status='completed', assignments=[assignment],
                          created_by=task.principal.id)
    release = WorkRelease(tenant_id=task.order.tenant_id, plan_id=plan.id, order_id=task.order.id,
                          line_id=plan.line_id, product_id=task.order.product_id, quantity=2,
                          due_date=task.order.due_date, published_by=task.principal.id,
                          assignments=[assignment])
    task.uow.session.add_all([plan, release])
    task.uow.session.flush()
    assert _order_production_status(task.uow, task.order, True) != 'completed'
    task.uow.session.add_all([
        ProductionReport(tenant_id=task.order.tenant_id, request_id=uuid.uuid4().hex,
                         request_hash='x' * 64, staff_user_id=task.principal.id, staff_name='测试',
                         release_id=current_release.id, order_id=task.order.id, order_code=task.order.code,
                         station_id=task.station.id, station_position=1, operation_id=operation_id,
                         sop_id=uuid.UUID(str(assignment['sop_id'])), sop_version=1, sop_title='测试',
                         good_qty=2, input_qty=2)
        for current_release, operation_id in [(task.release, uuid.UUID(first)), (release, second)]
    ])
    task.uow.session.flush()
    assert _order_production_status(task.uow, task.order, True) == 'completed'


def test_supplement_requires_manager_request_and_admin_approval(task):
    task.users.can_correct_production_reports = lambda user, tenant: True
    submit_web_report(task.body.model_copy(update={
        'request_id': uuid.uuid4(), 'input_qty': 2, 'good_qty': 1, 'defect_qty': 1,
    }), task.uow, task.principal, task.users)
    assert task.plan.status == 'completed'
    request = create_order_supplement(
        task.uow, SupplementInput(order_id=task.order.id, quantity=1, reason='良品短缺'),
        task.principal, task.users,
    )
    assert request.status == 'pending'
    with pytest.raises(HTTPException) as error:
        _require_order_capacity(task.uow, task.order.id, 1)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        review_order_supplement(task.uow, request.id, SupplementReview(approve=True), task.principal, task.users)
    assert error.value.status_code == 403
    task.users.is_tenant_administrator = lambda user, tenant: True
    approved = review_order_supplement(
        task.uow, request.id, SupplementReview(approve=True), task.principal, task.users,
    )
    assert approved.status == 'approved'
    assert _require_order_capacity(task.uow, task.order.id, 1).id == task.order.id
