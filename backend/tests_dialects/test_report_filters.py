"""Report filters use tenant master data even without any production reports."""
import uuid
from datetime import date

from sqlmodel import Session, select

from app.core.database import engine
from app.modules.esop.infrastructure.models import (
    ProductionLine,
    ProductionReport,
    Station,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.report_routes import _report_statement, report_filter_options
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import TenantMembership
from app.platform.user_directory import SqlUserDirectory


def test_master_data_without_reports_and_tenant_isolation():
    tenants = [uuid.uuid4(), uuid.uuid4()]
    with Session(engine) as session:
        try:
            ids = []
            for tenant in tenants:
                with EsopTenantUnitOfWork(session, tenant) as uow:
                    line = ProductionLine(tenant_id=tenant, workshop_id=uuid.uuid4(), code='FILTER', name='筛选产线')
                    station = Station(tenant_id=tenant, line_id=line.id, position=1, row=1, column=1, name='装配')
                    session.add_all([line, station])
                    session.flush()
                    ids.append((line.id, station.id))
                    options = report_filter_options(uow, SqlUserDirectory(session))
                    assert [row.value for row in options.lines] == [line.id]
                    assert [(row.value, row.line_id, row.label) for row in options.stations] == [(station.id, line.id, '筛选产线 / 装配')]
                    assert options.staff == []
            with EsopTenantUnitOfWork(session, tenants[0]) as uow:
                options = report_filter_options(uow, SqlUserDirectory(session))
                assert ids[1][0] not in [row.value for row in options.lines]
                assert ids[1][1] not in [row.value for row in options.stations]
        finally:
            session.rollback()


def test_line_filter_uses_release_line_and_combines_station_and_staff():
    tenant, line_a, line_b, station, staff = [uuid.uuid4() for _ in range(5)]
    with Session(engine) as session:
        try:
            with EsopTenantUnitOfWork(session, tenant):
                ids = []
                for line in [line_a, line_b]:
                    release = WorkRelease(tenant_id=tenant, plan_id=uuid.uuid4(), order_id=uuid.uuid4(), line_id=line, product_id=uuid.uuid4(), quantity=1, due_date=date.today(), published_by=staff)
                    report = ProductionReport(tenant_id=tenant, terminal_id=uuid.uuid4(), request_id=str(uuid.uuid4()), request_hash='x' * 64, staff_user_id=staff, staff_name='test', release_id=release.id, order_id=release.order_id, order_code='FILTER', station_id=station, station_position=1, operation_id=uuid.uuid4(), sop_id=uuid.uuid4(), sop_version=1, sop_title='test')
                    session.add_all([release, report])
                    ids.append(report.id)
                session.flush()
                filters = {'order_id': None, 'station_id': station, 'sop_id': None, 'staff_user_id': staff, 'start_at': None, 'end_at': None}
                assert [row.id for row in session.exec(_report_statement(line_id=line_a, **filters)).all()] == ids[:1]
                assert session.exec(_report_statement(line_id=uuid.uuid4(), **filters)).all() == []
                assert len(session.exec(_report_statement(**filters)).all()) == 2
        finally:
            session.rollback()


def test_employee_options_only_include_requested_tenant_members():
    with Session(engine) as session:
        membership = session.exec(select(TenantMembership).where(TenantMembership.is_active)).first()
        assert membership is not None
        expected = session.exec(select(User.id).join(TenantMembership, TenantMembership.user_id == User.id).where(TenantMembership.tenant_id == membership.tenant_id, TenantMembership.is_active)).all()
        assert {row.id for row in SqlUserDirectory(session).list_tenant_options(membership.tenant_id)} == set(expected)
        assert SqlUserDirectory(session).list_tenant_options(uuid.uuid4()) == []
