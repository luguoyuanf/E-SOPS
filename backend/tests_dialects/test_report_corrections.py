"""Audit, concurrency and administrator/manager-post boundaries on fixed MySQL."""
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.clock import get_datetime_utc
from app.core.database import engine
from app.modules.esop.infrastructure.models import (
    ProductionReport,
    ProductionReportRevision,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.terminal_dto import ReportCorrectionInput
from app.modules.esop.report_routes import (
    _progress,
    correct_report,
    report_correction_options,
    report_revisions,
    submit_web_report,
)
from app.platform.core.authorization_models import Post, Role, UserPost, UserRole
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import TenantMembership
from app.platform.public_api.users import UserSummary
from app.platform.tenant_uow import PlatformTenantUnitOfWork
from app.platform.user_directory import SqlUserDirectory
from tests_dialects.test_web_reporting import task as task


def report_and_input(task):
    saved = submit_web_report(task.body, task.uow, task.principal, task.users)
    task.users.can_correct_production_reports = lambda user, tenant: True
    body = ReportCorrectionInput(expected_revision=0, staff_user_id=task.employee, input_qty=2, good_qty=2, defect_qty=0, reason='  补正统计  ')
    return saved, body


def test_correction_history_actor_time_and_original_intake_retry(task):
    saved, body = report_and_input(task)
    original = task.uow.session.get(ProductionReport, saved.id)
    original_hash, occurred_at, submitted_by = original.request_hash, original.occurred_at, original.submitted_by
    now = get_datetime_utc()
    changed = correct_report(saved.id, body, task.uow, task.principal, task.users)
    assert changed.revision == 1 and changed.staff_user_id == task.employee and changed.good_qty == 2
    totals = _progress(task.uow.session, task.order)
    assert (totals.input_total, totals.good_total, totals.bad_total) == (2, 2, 0)
    history = report_revisions(saved.id, task.uow).items
    assert len(history) == 1
    entry = history[0]
    assert entry.reason == '补正统计' and entry.changed_by == task.principal.id
    assert entry.changed_by_name == '操作员' and entry.changed_at >= now
    assert entry.before['good_qty'] == 1 and entry.after['good_qty'] == 2
    assert entry.before['staff_user_id'] == str(task.principal.id) and entry.after['staff_user_id'] == str(task.employee)
    row = task.uow.session.get(ProductionReport, saved.id)
    assert (row.request_hash, row.occurred_at, row.submitted_by) == (original_hash, occurred_at, submitted_by)
    retry = submit_web_report(task.body, task.uow, task.principal, task.users)
    assert retry.id == saved.id and retry.good_qty == 2 and retry.revision == 1
    second = body.model_copy(update={'expected_revision': 1, 'input_qty': 1, 'good_qty': 1, 'reason': '复核后补正'})
    correct_report(saved.id, second, task.uow, task.principal, task.users)
    entries = report_revisions(saved.id, task.uow).items
    assert [entry.revision for entry in entries] == [2, 1]
    assert entries[0].before == entries[1].after


def test_ordinary_user_cannot_edit_but_can_read_history(task):
    saved, body = report_and_input(task)
    task.users.can_correct_production_reports = lambda user, tenant: False
    assert not report_correction_options(task.uow, task.principal, task.users).can_edit
    with pytest.raises(HTTPException) as error:
        correct_report(saved.id, body, task.uow, task.principal, task.users)
    assert error.value.status_code == 403
    assert report_revisions(saved.id, task.uow).total == 0


def test_stale_revision_does_not_overwrite_or_duplicate_history(task):
    saved, body = report_and_input(task)
    correct_report(saved.id, body, task.uow, task.principal, task.users)
    with pytest.raises(HTTPException) as error:
        correct_report(saved.id, body.model_copy(update={'good_qty': 99}), task.uow, task.principal, task.users)
    assert error.value.status_code == 409
    assert task.uow.session.get(ProductionReport, saved.id).good_qty == 2
    assert report_revisions(saved.id, task.uow).total == 1


@pytest.mark.parametrize('invalid', ['foreign_employee', 'inactive_employee', 'zero', 'unchanged'])
def test_invalid_correction_leaves_no_audit_or_data_change(task, invalid):
    saved, body = report_and_input(task)
    if invalid == 'foreign_employee':
        body = body.model_copy(update={'staff_user_id': uuid.uuid4()})
    if invalid == 'inactive_employee':
        task.users.get_users = lambda ids: [UserSummary(id=id, is_active=False) for id in ids]
    if invalid == 'zero':
        body = body.model_copy(update={'input_qty': 0, 'good_qty': 0, 'defect_qty': 0})
    if invalid == 'unchanged':
        body = body.model_copy(update={'staff_user_id': task.principal.id, 'input_qty': 1, 'good_qty': 1})
    with pytest.raises(HTTPException) as error:
        correct_report(saved.id, body, task.uow, task.principal, task.users)
    assert error.value.status_code in {403, 422}
    assert task.uow.session.get(ProductionReport, saved.id).revision == 0
    assert report_revisions(saved.id, task.uow).total == 0


def test_reason_required_and_negative_quantity_rejected(task):
    _, body = report_and_input(task)
    for change in [{'reason': ' \n '}, {'reason': 'x' * 501}, {'good_qty': -1}]:
        with pytest.raises(ValidationError):
            ReportCorrectionInput.model_validate({**body.model_dump(), **change})


def test_completed_execution_state_is_retained(task):
    saved, body = report_and_input(task)
    task.plan.status = 'completed'
    task.release.is_active = False
    task.uow.session.flush()
    correct_report(saved.id, body.model_copy(update={'staff_user_id': task.principal.id, 'input_qty': 1, 'good_qty': 0, 'defect_qty': 1}), task.uow, task.principal, task.users)
    assert task.plan.status == 'completed' and not task.release.is_active


def test_other_tenant_cannot_edit_or_read_audit(task):
    saved, body = report_and_input(task)
    correct_report(saved.id, body, task.uow, task.principal, task.users)
    with Session(bind=task.uow.session.connection(), join_transaction_mode='create_savepoint') as other:
        with EsopTenantUnitOfWork(other, uuid.uuid4()) as uow:
            for call in [lambda: report_revisions(saved.id, uow), lambda: correct_report(saved.id, body, uow, task.principal, task.users)]:
                with pytest.raises(HTTPException) as error:
                    call()
                assert error.value.status_code == 404
            assert other.exec(select(ProductionReportRevision)).all() == []


def test_failed_commit_rolls_back_correction_and_history(task, monkeypatch):
    saved, body = report_and_input(task)
    def fail():
        raise RuntimeError('simulated transaction failure')
    monkeypatch.setattr(task.uow.session, 'commit', fail)
    with pytest.raises(RuntimeError):
        correct_report(saved.id, body, task.uow, task.principal, task.users)
    task.uow.session.rollback()
    row = task.uow.session.get(ProductionReport, saved.id)
    assert row.revision == 0 and row.good_qty == 1
    assert report_revisions(saved.id, task.uow).total == 0


@pytest.mark.parametrize('authority', ['manager', 'administrator'])
def test_platform_directory_checks_live_tenant_authority(authority):
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
            membership = session.exec(select(TenantMembership).where(TenantMembership.is_active)).first()
            assert membership is not None
            tenant = membership.tenant_id
            with PlatformTenantUnitOfWork(session, tenant):
                user = User(username='correction' + uuid.uuid4().hex[:10], full_name='Correction test', hashed_password='not-used-for-login')
                session.add(user)
                session.flush()
                member = TenantMembership(user_id=user.id, tenant_id=tenant)
                session.add(member)
                session.flush()
                directory = SqlUserDirectory(session)
                assert not directory.can_correct_production_reports(user.id, tenant)
                if authority == 'manager':
                    owner = session.exec(select(Post).where(Post.code == 'manager', Post.is_active)).first()
                    assert owner is not None
                    session.add(UserPost(user_id=user.id, post_id=owner.id, tenant_id=tenant))
                else:
                    owner = session.exec(select(Role).where(Role.code == 'super_admin', Role.is_system, Role.is_active)).first()
                    assert owner is not None
                    session.add(UserRole(user_id=user.id, role_id=owner.id, tenant_id=tenant))
                session.flush()
                assert directory.can_correct_production_reports(user.id, tenant)
                assert not directory.can_correct_production_reports(user.id, uuid.uuid4())
                owner.is_active = False
                session.flush()
                assert not directory.can_correct_production_reports(user.id, tenant)
            session.rollback()
        transaction.rollback()
