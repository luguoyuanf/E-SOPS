"""Dashboard integration checks against the configured isolated MySQL database."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.core.database import engine
from app.modules.esop.dashboard_routes import read_esop_dashboard
from app.modules.esop.infrastructure.models import (
    AlarmEvent,
    Operation,
    ProductionLine,
    ProductionOrder,
    ProductionPlan,
    ProductionReport,
    ProductSopVersion,
    SopDocument,
    Station,
    Terminal,
    WorkRelease,
    Workshop,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork


def test_dashboard_scopes_versions_reports_and_live_devices(monkeypatch):
    now = datetime(2026, 10, 30, 9, tzinfo=UTC)
    monkeypatch.setattr('app.modules.esop.dashboard_routes.get_datetime_utc', lambda: now)
    tenants = [uuid.uuid4(), uuid.uuid4()]
    ids = []
    with Session(engine) as session:
        try:
            for tenant in tenants:
                with EsopTenantUnitOfWork(session, tenant):
                    workshop = Workshop(tenant_id=tenant, code='DASH-WS', name='仪表盘测试车间')
                    line = ProductionLine(tenant_id=tenant, workshop_id=workshop.id, code='DASH-LINE', name='测试产线')
                    station = Station(tenant_id=tenant, line_id=line.id, position=1, row=1, column=1)
                    product = uuid.uuid4()
                    op = Operation(tenant_id=tenant, code='DASH-OP', name='装配', product_id=product)
                    second_op = Operation(tenant_id=tenant, code='DASH-OP-2', name='检验', product_id=product)
                    order = ProductionOrder(tenant_id=tenant, code='DASH-ORDER', product_id=product, quantity=100, due_date=now.date())
                    plan = ProductionPlan(tenant_id=tenant, code='DASH-PLAN', order_id=order.id, line_id=line.id, quantity=100, status='published', start_at=now-timedelta(days=1), end_at=now+timedelta(days=1))
                    release = WorkRelease(tenant_id=tenant, plan_id=plan.id, order_id=order.id, line_id=line.id, product_id=product, quantity=100, due_date=now.date(), published_by=uuid.uuid4())
                    release.assignments = [{"operation_id": str(op.id)}]
                    family = uuid.uuid4()
                    docs = [SopDocument(tenant_id=tenant, family_id=family, product_id=product, operation_id=op.id, title='装配', version=v, status='approved', created_by=uuid.uuid4(), reviewed_at=now-timedelta(days=40 if v==1 else 1)) for v in (1, 2)]
                    second_doc = SopDocument(tenant_id=tenant, family_id=uuid.uuid4(), product_id=product, operation_id=second_op.id, title='检验', version=1, status='approved', created_by=uuid.uuid4(), reviewed_at=now-timedelta(days=1))
                    version = ProductSopVersion(tenant_id=tenant, product_id=product, product_name='产品', version=2, status='approved', created_by=uuid.uuid4(), reviewed_at=now-timedelta(days=1), operations=[{'sop_id':str(docs[1].id)}, {'sop_id':str(second_doc.id)}])
                    terminal = Terminal(tenant_id=tenant, device_code=str(uuid.uuid4()), station_id=station.id, last_seen_at=now-timedelta(seconds=60))
                    other = Terminal(tenant_id=tenant, device_code=str(uuid.uuid4()), is_active=False, last_seen_at=now)
                    reports = [ProductionReport(tenant_id=tenant, request_id=str(uuid.uuid4()), request_hash='x'*64, staff_user_id=uuid.uuid4(), staff_name='test', release_id=release.id, order_id=order.id, order_code=order.code, station_id=station.id, station_position=1, operation_id=op.id, sop_id=docs[1].id, sop_version=2, sop_title='装配', input_qty=10, good_qty=9, defect_qty=1, occurred_at=occurred, is_deleted=deleted) for occurred,deleted in [(now, False), (now, True), (datetime(2026,10,29,15,59,tzinfo=UTC), False), (datetime(2026,10,30,16,tzinfo=UTC),False)]]
                    session.add_all([workshop,line,station,op,second_op,order,plan,release,version,terminal,other,*docs,second_doc,*reports])
                    session.add(AlarmEvent(tenant_id=tenant, terminal_id=terminal.id,
                        station_id=station.id, request_id=str(uuid.uuid4()), request_hash='x'*64,
                        level='warning', reason='Dashboard test'))
                    session.flush()
                    ids.append((workshop.id, line.id, docs, version))
            with EsopTenantUnitOfWork(session, tenants[0]) as uow:
                result = read_esop_dashboard(uow, day=now.date())
                assert result.lines[0].planned_qty == 100
                assert result.lines[0].finished_qty == 9
                assert result.lines[0].unresolved_alarms == 1
                assert len(result.lines) == 1
                assert result.effective_sop == result.cumulative_sop == 1  # two operations, one product SOP
                assert result.effective_operations == 2
                assert result.sop_trend[-1].count == 1
                assert [row.count for row in result.sop_trend] == sorted(row.count for row in result.sop_trend)
                assert result.terminal_total == 2 and result.terminal_online == 1 and result.terminal_unbound == 1
                assert len(result.reports) == 1 and result.reports[0].count == 1
                assert result.reports[0].good_qty == 9
                assert result.lines[0].plan_total == 1 and result.lines[0].terminal_total == 1
                scoped = read_esop_dashboard(uow, day=now.date(), workshop_id=ids[0][0], line_id=ids[0][1])
                assert scoped.terminal_total == scoped.terminal_online == 1 and scoped.terminal_unbound == 0
                assert scoped.effective_sop == 1
                with pytest.raises(HTTPException) as error:
                    read_esop_dashboard(uow, day=now.date(), line_id=ids[1][1])
                assert error.value.status_code == 404
                with pytest.raises(HTTPException):
                    read_esop_dashboard(uow, day=now.date(), timezone='Invalid/Zone')
                with pytest.raises(HTTPException):
                    read_esop_dashboard(uow, day=now.date()+timedelta(days=1))
                # A later approved snapshot removes the step; drafts do not.
                removed = ProductSopVersion(tenant_id=tenants[0], product_id=ids[0][3].product_id, product_name='产品', version=3, status='approved', created_by=uuid.uuid4(), reviewed_at=now-timedelta(hours=1), operations=[])
                session.add(removed)
                session.flush()
                removed_result = read_esop_dashboard(uow, day=now.date())
                assert removed_result.effective_sop == 0 and removed_result.cumulative_sop == 1
                assert removed_result.effective_operations == 0
            with EsopTenantUnitOfWork(session, uuid.uuid4()) as uow:
                empty = read_esop_dashboard(uow, day=now.date())
                assert empty.lines == empty.reports == []
                assert empty.effective_sop == empty.terminal_total == 0
                assert all(row.count == 0 for row in empty.sop_trend)
        finally:
            session.rollback()
