"""Fixed MySQL: group-wide versus per-station transition and monotonic task selection."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.modules.esop import production_routes
from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import (
    ProductionPlan,
    ProductionPlanGroup,
    Station,
    Terminal,
    WorkRelease,
)
from app.modules.esop.plan_scheduler import advance_due_plans, station_can_start_plan
from app.modules.esop.production_routes import update_plan_group
from app.modules.esop.public_api.production_dto import PlanGroupInput
from app.modules.esop.public_api.terminal_dto import (
    ReportChangeReview,
    ReportDeleteInput,
)
from app.modules.esop.report_change_routes import (
    request_report_deletion,
    review_report_change,
)
from app.modules.esop.report_routes import submit_web_report
from app.modules.esop.terminal_routes import _active_tasks
from app.platform.web_api import TenantContext
from tests_dialects.test_web_reporting import task as task


def configure(task, monkeypatch, mode):
    session, tenant = task.uow.session, task.uow.tenant_id
    group = ProductionPlanGroup(tenant_id=tenant, name='切换模式验收', created_by=task.principal.id, switch_mode=mode, is_paused=False)
    station = Station(tenant_id=tenant, line_id=task.station.line_id, position=2, row=1, column=2)
    other = {**task.release.assignments[0], 'station_id': str(station.id), 'station_position': 2,
             'operation_id': str(uuid.uuid4()), 'operation_name': '工序B', 'sop_id': str(uuid.uuid4())}
    assignments = [task.release.assignments[0], other]
    task.plan.group_id, task.plan.group_position = group.id, 0
    task.order.quantity = 4
    task.plan.assignments = task.release.assignments = assignments
    following = ProductionPlan(tenant_id=tenant, code='NEXT-TEST', order_id=task.order.id, line_id=task.plan.line_id,
                               quantity=2, group_id=group.id, group_position=1, assignments=assignments, created_by=task.principal.id)
    terminals = [Terminal(tenant_id=tenant, device_code='mode-' + uuid.uuid4().hex, station_id=item.id)
                 for item in (task.station, station)]
    task.station.current_release_id = station.current_release_id = task.release.id
    session.add_all([group, station, following, *terminals])
    session.flush()

    def snapshot(_uow, body, *, complete):
        assert complete
        return [next(dict(item) for item in assignments if str(value.operation_id) == item['operation_id'] and str(value.station_id) == item['station_id'])
                for value in body.assignments]
    monkeypatch.setattr(production_routes, '_validate_assignments', snapshot)
    task.users.can_correct_production_reports = lambda user, tenant: True
    return SimpleNamespace(group=group, station=station, following=following, terminals=terminals, other=other)


def report(task, state, *, release=None, second=False):
    changes = {'request_id': uuid.uuid4(), 'input_qty': 2, 'good_qty': 2}
    if release:
        changes['release_id'] = release.id
    if second:
        changes.update(station_id=state.station.id, operation_id=uuid.UUID(state.other['operation_id']), sop_id=uuid.UUID(state.other['sop_id']))
    return submit_web_report(task.body.model_copy(update=changes), task.uow, task.principal, task.users)


def following_release(task, state):
    return task.uow.session.exec(select(WorkRelease).where(WorkRelease.plan_id == state.following.id)).first()


def test_together_waits_for_all_operations_then_switches_whole_line(task, monkeypatch):
    state = configure(task, monkeypatch, 'together')
    report(task, state)
    assert state.following.status == 'draft'
    assert _active_tasks(task.uow.session, state.terminals[0]) == []
    assert _active_tasks(task.uow.session, state.terminals[1])[0][0].id == task.release.id
    report(task, state, second=True)
    next_release = following_release(task, state)
    assert task.plan.status == 'completed' and state.following.status == 'published'
    assert all(_active_tasks(task.uow.session, terminal)[0][0].id == next_release.id for terminal in state.terminals)


def test_independent_station_advances_while_other_station_keeps_previous_plan(task, monkeypatch):
    state = configure(task, monkeypatch, 'independent')
    report(task, state)
    next_release = following_release(task, state)
    assert task.plan.status == 'published' and state.following.status == 'published'
    assert _active_tasks(task.uow.session, state.terminals[0], advance_cursor=True)[0][0].id == next_release.id
    assert task.station.current_release_id == next_release.id
    assert _active_tasks(task.uow.session, state.terminals[1])[0][0].id == task.release.id
    assert not station_can_start_plan(task.uow.session, state.following, state.station.id)
    with pytest.raises(HTTPException) as error:
        report(task, state, release=next_release, second=True)
    assert error.value.status_code == 409
    report(task, state, second=True)
    assert _active_tasks(task.uow.session, state.terminals[1], advance_cursor=True)[0][0].id == next_release.id
    report(task, state, release=next_release)
    report(task, state, release=next_release, second=True)
    assert state.following.status == 'completed'
    assert all(_active_tasks(task.uow.session, terminal) == [] for terminal in state.terminals)


@pytest.mark.parametrize('entry', ['poll', 'report'])
def test_approved_deletion_reverses_statistics_without_rewinding_advanced_station(task, monkeypatch, entry):
    state = configure(task, monkeypatch, 'independent')
    saved = report(task, state)
    next_release = following_release(task, state)
    if entry == 'poll':
        _active_tasks(task.uow.session, state.terminals[0], advance_cursor=True)
    else:
        submit_web_report(task.body.model_copy(update={'request_id': uuid.uuid4(), 'release_id': next_release.id}), task.uow, task.principal, task.users)
    assert task.station.current_release_id == next_release.id
    device = DeviceIdentity(tenant_id=task.uow.tenant_id, terminal_id=state.terminals[0].id)
    tenant = TenantContext(tenant_id=task.uow.tenant_id, tenant_code='TEST', user_id=task.principal.id)
    change = request_report_deletion(saved.id, ReportDeleteInput(request_id=uuid.uuid4(), expected_revision=0, reason='撤销误报'),
                                     task.uow.session, device, task.principal, tenant, task.users)
    review_report_change(change.id, ReportChangeReview(approve=True), task.uow, task.principal, task.users)
    assert _active_tasks(task.uow.session, state.terminals[0])[0][0].id == next_release.id
    assert _active_tasks(task.uow.session, state.terminals[1])[0][0].id == task.release.id
    report(task, state, second=True)
    assert task.plan.status == 'completed'  # Execution passed this task; statistics remain reversed.
    assert _active_tasks(task.uow.session, state.terminals[0])[0][0].id == next_release.id


def test_pause_blocks_further_station_transition_but_current_plan_continues(task, monkeypatch):
    state = configure(task, monkeypatch, 'independent')
    report(task, state)
    next_release = following_release(task, state)
    _active_tasks(task.uow.session, state.terminals[0], advance_cursor=True)
    state.group.is_paused = True
    task.uow.session.flush()
    report(task, state, second=True)
    assert _active_tasks(task.uow.session, state.terminals[0])[0][0].id == next_release.id
    assert _active_tasks(task.uow.session, state.terminals[1]) == []
    state.group.is_paused = False
    task.uow.session.flush()
    advance_due_plans(task.uow.session)
    assert _active_tasks(task.uow.session, state.terminals[1])[0][0].id == next_release.id


def test_group_mode_can_enable_independence_but_cannot_merge_running_station_tasks(task, monkeypatch):
    state = configure(task, monkeypatch, 'together')
    updated = update_plan_group(task.uow, state.group.id, PlanGroupInput(name=state.group.name, plan_ids=[task.plan.id, state.following.id], switch_mode='independent'))
    assert updated.switch_mode == 'independent'
    report(task, state)
    with pytest.raises(HTTPException) as error:
        update_plan_group(task.uow, state.group.id, PlanGroupInput(name=state.group.name, plan_ids=[task.plan.id, state.following.id], switch_mode='together'))
    assert error.value.status_code == 409


def test_paused_previous_plan_can_resume_alongside_same_independent_group(task, monkeypatch):
    from app.modules.esop.production_routes import pause_plan, resume_plan

    state = configure(task, monkeypatch, 'independent')
    report(task, state)
    next_release = following_release(task, state)
    _active_tasks(task.uow.session, state.terminals[0], advance_cursor=True)
    pause_plan(task.uow, task.plan.id)
    assert _active_tasks(task.uow.session, state.terminals[1]) == []
    resume_plan(task.uow, task.plan.id)
    assert _active_tasks(task.uow.session, state.terminals[1])[0][0].id == task.release.id
    assert _active_tasks(task.uow.session, state.terminals[0])[0][0].id == next_release.id
