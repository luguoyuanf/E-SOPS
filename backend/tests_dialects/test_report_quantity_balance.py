"""New report writes balance input against good + defective; old facts remain idempotent."""
import hashlib
import json
import uuid

import pytest
from fastapi import HTTPException

from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import ProductionReport, Terminal
from app.modules.esop.public_api.terminal_dto import (
    ReportChangeInput,
    ReportCorrectionInput,
    ReportInput,
)
from app.modules.esop.report_change_routes import request_report_change
from app.modules.esop.report_routes import (
    correct_report,
    submit_report,
    submit_web_report,
)
from app.platform.web_api import TenantContext
from tests_dialects.test_web_reporting import task as task


def terminal_context(task):
    terminal = Terminal(tenant_id=task.uow.tenant_id, device_code='balance-' + uuid.uuid4().hex, station_id=task.station.id)
    task.uow.session.add(terminal)
    task.uow.session.flush()
    return (DeviceIdentity(tenant_id=task.uow.tenant_id, terminal_id=terminal.id),
            TenantContext(tenant_id=task.uow.tenant_id, tenant_code='TEST', user_id=task.principal.id))


@pytest.mark.parametrize('path', ['web', 'terminal', 'change', 'correction'])
@pytest.mark.parametrize('quantities', [(0, 0, 0), (0, 1, 0), (2, 1, 0), (1, 1, 1), (1, 0, 0)])
def test_invalid_quantity_cannot_write_any_report_path(task, path, quantities):
    input_qty, good_qty, defect_qty = quantities
    device, tenant = terminal_context(task)
    values = {'input_qty': input_qty, 'good_qty': good_qty, 'defect_qty': defect_qty}
    saved = submit_web_report(task.body, task.uow, task.principal, task.users) if path in {'change', 'correction'} else None
    task.users.can_correct_production_reports = lambda user, tenant: True
    with pytest.raises(HTTPException) as error:
        if path == 'web':
            submit_web_report(task.body.model_copy(update=values), task.uow, task.principal, task.users)
        elif path == 'terminal':
            submit_report(task.uow.session, device, task.principal, tenant, task.users,
                          ReportInput(requestId=uuid.uuid4().hex, releaseId=task.release.id,
                                      orderId=task.order.id, sopId=task.body.sop_id,
                                      inputQty=input_qty, goodQty=good_qty, defectQty=defect_qty))
        elif path == 'change':
            request_report_change(saved.id, ReportChangeInput(request_id=uuid.uuid4(), expected_revision=0, reason='数量核对', **values),
                                  task.uow.session, device, task.principal, tenant, task.users)
        else:
            correct_report(saved.id, ReportCorrectionInput(expected_revision=0, staff_user_id=task.principal.id,
                                                          reason='数量核对', **values), task.uow, task.principal, task.users)
    assert error.value.status_code == 422
    assert '投入数量' in error.value.detail
    if saved:
        row = task.uow.session.get(ProductionReport, saved.id)
        assert (row.input_qty, row.good_qty, row.defect_qty, row.revision) == (1, 1, 0, 0)


@pytest.mark.parametrize('quantities', [(10, 9, 1), (10, 10, 0), (10, 0, 10)])
def test_balanced_reports_allow_mixed_all_good_or_all_defective(task, quantities):
    input_qty, good_qty, defect_qty = quantities
    task.release.quantity = 10
    task.order.quantity = 10
    task.uow.session.flush()
    result = submit_web_report(task.body.model_copy(update={'input_qty': input_qty, 'good_qty': good_qty, 'defect_qty': defect_qty}),
                               task.uow, task.principal, task.users)
    assert result.input_qty == result.good_qty + result.defect_qty == 10


def test_old_successful_partial_report_retry_returns_original_fact(task):
    saved = submit_web_report(task.body, task.uow, task.principal, task.users)
    # Simulate a pre-rule fact; do not rewrite old records when replaying its request.
    legacy = task.body.model_copy(update={'input_qty': 0})
    row = task.uow.session.get(ProductionReport, saved.id)
    row.input_qty = 0
    row.request_hash = hashlib.sha256(json.dumps(
        {**legacy.model_dump(mode='json'), 'staff_user_id': str(task.principal.id)}, sort_keys=True,
    ).encode()).hexdigest()
    task.uow.session.flush()
    assert submit_web_report(legacy, task.uow, task.principal, task.users).id == saved.id
    assert row.input_qty == 0
    with pytest.raises(HTTPException) as error:
        submit_web_report(legacy.model_copy(update={'request_id': uuid.uuid4()}), task.uow, task.principal, task.users)
    assert error.value.status_code == 422
