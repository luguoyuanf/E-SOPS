"""Alarm categories remain tenant-local while global defaults are shared."""

import hashlib
import json
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.routes.dictionaries import (
    create_dictionary_item,
    delete_dictionary_item,
    delete_dictionary_type,
    update_dictionary_item,
)
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.modules.esop.alarm_type_routes import (
    AlarmTypeInput,
    AlarmTypePreferenceInput,
    AlarmTypePreferencesInput,
    create_tenant_alarm_type,
    list_alarm_types,
    rename_platform_alarm_type,
    rename_tenant_alarm_type,
    terminal_alarm_types,
    update_alarm_type_preferences,
)
from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import (
    AlarmEvent,
    AlarmTypePreference,
    ProductionOrder,
    ProductionPlan,
    ProductionReport,
    Terminal,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.terminal_dto import AlarmInput
from app.modules.esop.report_routes import (
    _hash_request,
    resolve_alarm,
    resolve_own_alarm,
    submit_alarm,
    terminal_alarms,
)
from app.platform.alarm_type_directory import SqlAlarmTypeDirectory
from app.platform.core.configuration_models import (
    DictionaryItem,
    DictionaryItemCreate,
    DictionaryItemUpdate,
    DictionaryType,
)
from app.platform.tenant_uow import PlatformTenantUnitOfWork
from app.platform.web_api import Principal


class _TenantAdmin:
    def is_tenant_administrator(self, _user_id, _tenant_id):
        return True


@pytest.fixture
def data():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[
        DictionaryType.__table__, DictionaryItem.__table__,
        AlarmTypePreference.__table__, Terminal.__table__, AlarmEvent.__table__,
        WorkRelease.__table__, ProductionPlan.__table__, ProductionReport.__table__, ProductionOrder.__table__,
    ])
    with Session(engine) as session:
        with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
            type_ = DictionaryType(tenant_id=DEFAULT_TENANT_ID, code="esop_alarm_type", name="报警类型")
            session.add(type_)
            session.flush()
            for sort, (code, name) in enumerate((("production", "生产问题"), ("sop", "SOP问题"),
                                                ("personnel", "人员问题"), ("other", "其他问题"))):
                session.add(DictionaryItem(tenant_id=DEFAULT_TENANT_ID, type_id=type_.id,
                                           value=code, label=name, sort=sort))
            session.commit()
        yield session


def test_global_category_visible_to_tenants_and_preferences_isolated(data):
    session = data
    first, second = uuid.uuid4(), uuid.uuid4()
    directory = SqlAlarmTypeDirectory(session)
    directory.create_global("设备问题")
    session.commit()
    with EsopTenantUnitOfWork(session, first) as uow:
        choices = list_alarm_types(uow, directory, Principal(id=uuid.uuid4(), is_superuser=False))
        assert len(choices.items) == 5
        assert choices.items[0].code == "production"
        assert choices.items[-1].name == "设备问题"
        pref = AlarmTypePreference(tenant_id=first, type_code="production", enabled=False, sort=9)
        session.add(pref)
        session.commit()
        assert "production" not in {item.code for item in terminal_alarm_types(
            session, DeviceIdentity(tenant_id=first, terminal_id=uuid.uuid4()), directory,
        ).items}
    assert "production" in {item.code for item in terminal_alarm_types(
        session, DeviceIdentity(tenant_id=second, terminal_id=uuid.uuid4()), directory,
    ).items}


def test_alarm_submission_validates_category_and_preserves_legacy(data):
    session = data
    tenant, other, station = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    terminal_id = uuid.uuid4()
    terminal = Terminal(id=terminal_id, tenant_id=tenant, device_code="T-1", station_id=station)
    with EsopTenantUnitOfWork(session, tenant):
        session.add(terminal)
        session.commit()
    device = DeviceIdentity(tenant_id=tenant, terminal_id=terminal_id)
    directory = SqlAlarmTypeDirectory(session)
    principal = Principal(id=uuid.uuid4(), is_superuser=False)
    context = SimpleNamespace(tenant_id=tenant)
    first = submit_alarm(session, device, AlarmInput(requestId="a-1", typeCode="production"), directory, principal, context)
    second = submit_alarm(session, device, AlarmInput(requestId="a-1", typeCode="production"), directory, principal, context)
    assert first.id == second.id and first.type_name == "生产问题"
    rename_platform_alarm_type("production", AlarmTypeInput(name="生产异常"),
                               Principal(id=uuid.uuid4(), is_superuser=True), directory, session)
    assert directory.list_global()[0].name == "生产异常"
    assert first.type_name == "生产问题"
    legacy = submit_alarm(session, device, AlarmInput(requestId="a-2", level="yellow", reason="旧终端原因"), directory, principal, context)
    assert legacy.type_code is None and legacy.reason == "旧终端原因"
    with EsopTenantUnitOfWork(session, tenant):
        session.add(AlarmTypePreference(tenant_id=tenant, type_code="sop", enabled=False, sort=1))
        session.commit()
    with pytest.raises(HTTPException) as stopped:
        submit_alarm(session, device, AlarmInput(requestId="a-3", typeCode="sop"), directory, principal, context)
    assert stopped.value.status_code == 422
    directory.create_tenant(other, "别的租户自定义")
    session.commit()
    foreign = directory.list_tenant(other)[0]
    with pytest.raises(HTTPException) as forbidden:
        submit_alarm(session, device, AlarmInput(requestId="a-4", typeCode=foreign.code), directory, principal, context)
    assert forbidden.value.status_code == 422
    with EsopTenantUnitOfWork(session, tenant):
        assert len(session.exec(select(AlarmEvent)).all()) == 2


def test_tenant_admin_can_configure_but_cannot_rename_builtins(data):
    session = data
    tenant = uuid.uuid4()
    directory = SqlAlarmTypeDirectory(session)
    principal = Principal(id=uuid.uuid4(), is_superuser=False)
    with EsopTenantUnitOfWork(session, tenant) as uow:
        created = create_tenant_alarm_type(AlarmTypeInput(name="物料问题"), uow, directory,
                                           principal, _TenantAdmin())
        assert created.tenant_owned
        updated = update_alarm_type_preferences(
            AlarmTypePreferencesInput(items=[AlarmTypePreferenceInput(
                code="production", enabled=False, sort=8,
            )]), uow, directory, principal, _TenantAdmin(),
        )
        assert next(item for item in updated.items if item.code == "production").enabled is False
        with pytest.raises(HTTPException) as protected:
            rename_tenant_alarm_type("production", AlarmTypeInput(name="篡改"),
                                     uow, directory, principal, _TenantAdmin())
        assert protected.value.status_code == 403
        with pytest.raises(HTTPException) as platform_denied:
            rename_platform_alarm_type("production", AlarmTypeInput(name="改名"),
                                       principal, directory, session)
        assert platform_denied.value.status_code == 403


def test_legacy_alarm_request_hash_remains_compatible():
    body = AlarmInput(requestId="old-1", level="yellow", reason="旧原因")
    legacy_payload = {
        "requestId": "old-1", "releaseId": None, "level": "yellow",
        "reason": "旧原因", "occurredAt": None,
    }
    expected = hashlib.sha256(json.dumps(legacy_payload, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    assert _hash_request(body) == expected


def test_generic_dictionary_routes_cannot_mutate_alarm_catalog(data):
    session = data
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID):
        type_ = session.exec(select(DictionaryType).where(DictionaryType.code == "esop_alarm_type")).one()
        item = session.exec(select(DictionaryItem).where(
            DictionaryItem.type_id == type_.id, DictionaryItem.value == "production",
        )).one()
        type_id, item_id = type_.id, item.id

    class Tenant:
        tenant_id = DEFAULT_TENANT_ID

    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID):
        for action in (
            lambda: create_dictionary_item(session=session, tenant_context=Tenant(),
                                           item_in=DictionaryItemCreate(type_id=type_id, value="bypass", label="绕过")),
            lambda: update_dictionary_item(session=session, tenant_context=Tenant(), item_id=item_id,
                                           item_in=DictionaryItemUpdate(label="绕过")),
            lambda: delete_dictionary_item(session=session, tenant_context=Tenant(), item_id=item_id),
            lambda: delete_dictionary_type(session=session, tenant_context=Tenant(), type_id=type_id),
        ):
            with pytest.raises(HTTPException) as denied:
                action()
            assert denied.value.status_code == 403


def test_own_alarm_history_is_authenticated_paginated_and_tenant_scoped(data):
    session = data
    tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    principal = Principal(id=uuid.uuid4(), is_superuser=False)
    other = Principal(id=uuid.uuid4(), is_superuser=False)
    context = SimpleNamespace(tenant_id=tenant)
    terminal = Terminal(tenant_id=tenant, device_code="history", station_id=uuid.uuid4())
    with EsopTenantUnitOfWork(session, tenant):
        session.add(terminal)
        session.commit()
        device = DeviceIdentity(tenant_id=tenant, terminal_id=terminal.id)
    directory = SqlAlarmTypeDirectory(session)
    for i in range(22):
        submit_alarm(session, device, AlarmInput(requestId=f"mine-{i}", typeCode="sop", reason="  情况说明  "), directory, principal, context)
    submit_alarm(session, device, AlarmInput(requestId="other", typeCode="sop"), directory, other, context)
    with EsopTenantUnitOfWork(session, tenant):
        session.add(AlarmEvent(tenant_id=tenant, terminal_id=device.terminal_id, station_id=uuid.uuid4(),
                               request_id="legacy", request_hash="legacy", level="red", reason="历史"))
        session.commit()
    first = terminal_alarms(session, device, principal, context)
    second = terminal_alarms(session, device, principal, context, page=2)
    assert first.total == second.total == 22
    assert len(first.items) == 20 and len(second.items) == 2
    assert all(row.staff_user_id == principal.id and row.reason == "情况说明" for row in first.items)
    assert not {row.id for row in first.items} & {row.id for row in second.items}
    with pytest.raises(HTTPException) as denied:
        terminal_alarms(session, device, principal, SimpleNamespace(tenant_id=other_tenant))
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as denied:
        submit_alarm(session, device, AlarmInput(requestId="cross", typeCode="sop"), directory, principal, SimpleNamespace(tenant_id=other_tenant))
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as denied:
        submit_alarm(session, device, AlarmInput(requestId="mine-0", typeCode="sop", reason="  情况说明  "), directory, other, context)
    assert denied.value.status_code == 409
    from app.core.clock import get_datetime_utc
    with EsopTenantUnitOfWork(session, tenant):
        row = session.get(AlarmEvent, first.items[0].id)
        row.resolved_at = get_datetime_utc()
        row.resolved_by = principal.id
        session.add(row)
        session.commit()
    assert terminal_alarms(session, device, principal, context, status="resolved").total == 1
    assert terminal_alarms(session, device, principal, context, status="unresolved").total == 21
    assert terminal_alarms(session, device, principal, context, type_code="production").total == 0
    assert terminal_alarms(session, device, principal, context, type_code="sop", status="resolved").total == 1


def test_resolution_owner_isolation_remote_and_idempotence(data):
    session = data
    tenant = uuid.uuid4()
    principal = Principal(id=uuid.uuid4(), is_superuser=False)
    other = Principal(id=uuid.uuid4(), is_superuser=False)
    context = SimpleNamespace(tenant_id=tenant)
    terminal = Terminal(tenant_id=tenant, device_code="resolve", station_id=uuid.uuid4())
    with EsopTenantUnitOfWork(session, tenant):
        session.add(terminal)
        session.commit()
        device = DeviceIdentity(tenant_id=tenant, terminal_id=terminal.id)
    directory = SqlAlarmTypeDirectory(session)
    row = submit_alarm(session, device, AlarmInput(requestId="resolve", typeCode="sop"), directory, principal, context)
    assert row.resolved_at is None
    with pytest.raises(HTTPException) as denied:
        resolve_own_alarm(row.id, session, device, other, context)
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        resolve_own_alarm(row.id, session, device, principal, SimpleNamespace(tenant_id=uuid.uuid4()))
    assert denied.value.status_code == 403
    resolved = resolve_own_alarm(row.id, session, device, principal, context)
    assert resolved.resolved_by == principal.id and resolved.resolved_at is not None
    with EsopTenantUnitOfWork(session, tenant) as uow:
        repeated = resolve_alarm(row.id, uow, other)
        assert repeated.resolved_by == principal.id and repeated.resolved_at == resolved.resolved_at
    row2 = submit_alarm(session, device, AlarmInput(requestId="remote", typeCode="sop"), directory, principal, context)
    with EsopTenantUnitOfWork(session, tenant) as uow:
        remote = resolve_alarm(row2.id, uow, other)
        assert remote.resolved_by == other.id
    with EsopTenantUnitOfWork(session, uuid.uuid4()) as uow:
        with pytest.raises(HTTPException) as denied:
            resolve_alarm(row2.id, uow, other)
        assert denied.value.status_code == 404


@pytest.mark.parametrize("mode", ["current", "none", "paused", "other_station"])
def test_alarm_automatically_binds_only_current_station_task(data, mode):
    session = data
    tenant, station = uuid.uuid4(), uuid.uuid4()
    principal = Principal(id=uuid.uuid4(), is_superuser=False)
    context = SimpleNamespace(tenant_id=tenant)
    terminal = Terminal(tenant_id=tenant, device_code="alarm-association", station_id=station)
    order = ProductionOrder(tenant_id=tenant, code="ORDER-ALARM", product_id=uuid.uuid4(), quantity=100, due_date=date(2026, 11, 1))
    plan = ProductionPlan(tenant_id=tenant, code="PLAN-ALARM", order_id=order.id, line_id=uuid.uuid4(), quantity=100, status="published")
    release = WorkRelease(tenant_id=tenant, plan_id=plan.id, order_id=order.id, line_id=plan.line_id,
                          product_id=order.product_id, quantity=100, due_date=order.due_date, published_by=principal.id,
                          assignments=[{"station_id":str(station if mode != "other_station" else uuid.uuid4()), "operation_id":str(uuid.uuid4())}],
                          is_active=mode != "paused")
    release_id, plan_id, order_id = release.id, plan.id, order.id
    with EsopTenantUnitOfWork(session, tenant):
        session.add(terminal)
        if mode != "none":
            session.add_all([order, plan, release])
        session.commit()
        device = DeviceIdentity(tenant_id=tenant, terminal_id=terminal.id)
    body = AlarmInput(requestId="auto-association", typeCode="sop", releaseId=uuid.uuid4())
    row = submit_alarm(session, device, body, SqlAlarmTypeDirectory(session), principal, context)
    if mode == "current":
        assert (row.release_id, row.plan_id, row.order_id) == (release_id, plan_id, order_id)
        assert (row.plan_code, row.order_code) == ("PLAN-ALARM", "ORDER-ALARM")
        # Retrying after task changes must return the original association, not rebind history.
        with EsopTenantUnitOfWork(session, tenant):
            current_release = session.get(WorkRelease, release_id)
            current_release.is_active = False
            session.add(current_release)
            session.commit()
        retry = submit_alarm(session, device, body, SqlAlarmTypeDirectory(session), principal, context)
        assert retry.release_id == row.release_id and retry.id == row.id
        history = terminal_alarms(session, device, principal, context)
        assert history.items[0].plan_code == "PLAN-ALARM"
    else:
        assert row.release_id is row.plan_id is row.order_id is None
        assert row.plan_code is row.order_code is None
