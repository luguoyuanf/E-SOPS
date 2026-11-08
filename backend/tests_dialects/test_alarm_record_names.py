"""Alarm list resolves tenant-local labels and known staff."""
import uuid
from types import SimpleNamespace

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.modules.esop.infrastructure.models import AlarmEvent, Station, Terminal
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.report_routes import list_alarms


def test_alarm_record_names_and_tenant_isolation():
    engine = create_engine('sqlite://', poolclass=StaticPool,
                           execution_options={'schema_translate_map': {'esop': None}})
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in (AlarmEvent, Station, Terminal)])
    first, second, staff_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    requested = []

    def get_users(ids):
        requested.append(ids)
        return [SimpleNamespace(id=staff_id, full_name='报警员工', email=None)]

    with Session(engine) as session:
        for tenant_id in (first, second):
            with EsopTenantUnitOfWork(session, tenant_id):
                station = Station(tenant_id=tenant_id, line_id=uuid.uuid4(), position=3,
                                  name='装配工位' if tenant_id == first else '其他租户工位', row=1, column=1)
                terminal = Terminal(tenant_id=tenant_id, device_code='TERM-003',
                                    serial_number='SN00000003' if tenant_id == first else 'SN00000004',
                                    device_name='装配屏' if tenant_id == first else None, station_id=station.id)
                session.add(station)
                session.add(terminal)
                for staff in (staff_id, None):
                    session.add(AlarmEvent(tenant_id=tenant_id, terminal_id=terminal.id,
                                           station_id=station.id, request_id=str(uuid.uuid4()),
                                           request_hash='test', level='yellow', reason='测试',
                                           staff_user_id=staff))
                other_station_id = station.id
                session.commit()
        with EsopTenantUnitOfWork(session, first) as uow:
            result = list_alarms(uow, SimpleNamespace(get_users=get_users))
            assert result.total == 2
            assert {row.terminal_name for row in result.items} == {'装配屏'}
            assert {row.station_name for row in result.items} == {'装配工位'}
            assert {row.staff_name for row in result.items} == {'报警员工', None}
            assert requested == [{staff_id}]
            assert session.get(Station, other_station_id) is None
            first_station = session.get(Station, result.items[0].station_id)
            first_station.name = ''
            session.add(first_station)
            first_terminal = session.get(Terminal, result.items[0].terminal_id)
            first_terminal.device_name = None
            session.add(first_terminal)
            session.flush()
            fallback = list_alarms(uow, SimpleNamespace(get_users=get_users)).items[0]
            assert fallback.station_name == '3 号工位'
            assert fallback.terminal_name == 'SN00000003'
