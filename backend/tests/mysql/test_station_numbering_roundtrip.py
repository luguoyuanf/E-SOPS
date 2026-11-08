"""Fixed-test-DB roundtrip; all fixtures are rolled back by the outer transaction."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.core.config import settings
from app.core.database import engine
from app.modules.esop.infrastructure.models import ProductionPlan, Terminal
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.production_routes import (
    create_line,
    create_workshop,
    list_lines,
    update_line,
)
from app.modules.esop.public_api.production_dto import LineInput, WorkshopInput
from app.modules.esop.terminal_routes import terminal_profile


def test_bound_station_and_plan_survive_renaming_and_numbering():
    assert settings.MYSQL_DB == 'esop_fva_test_20261024'
    tenant_id = uuid.uuid4()
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
                with EsopTenantUnitOfWork(session, tenant_id) as uow:
                    workshop = create_workshop(uow, WorkshopInput(code='ACCEPT-NUM-WS', name='验收车间'))
                    body = LineInput(workshop_id=workshop.id, code='ACCEPT-NUM-LINE', name='验收线', layout='double', station_count=20)
                    line = create_line(uow, body)
                    original = [s.id for s in line.stations]
                    terminal = Terminal(tenant_id=tenant_id, station_id=original[1], device_code='ACCEPT-NUM-DEVICE')
                    plan = ProductionPlan(tenant_id=tenant_id, line_id=line.id, order_id=uuid.uuid4(), assignments=[{'station_id': str(original[1])}])
                    session.add_all([terminal, plan])
                    session.commit()
                    changed = update_line(uow, line.id, body.model_copy(update={'numbering_mode': 'sequential', 'station_names': {2: '  装配工位  '}}))
                    assert [s.id for s in changed.stations] == original
                    assert [(s.row, s.column) for s in changed.stations[:11]] == [(1, p) for p in range(1, 11)] + [(2, 1)]
                    assert changed.stations[1].name == '装配工位'
                    assert changed.stations[1].terminal_code == 'ACCEPT-NUM-DEVICE'
                    session.refresh(terminal)
                    session.refresh(plan)
                    assert terminal.station_id == original[1] and plan.assignments == [{'station_id': str(original[1])}]
                    profile = terminal_profile(session, SimpleNamespace(tenant_id=tenant_id, terminal_id=terminal.id))
                    assert profile['siteName'] == '装配工位'
                    assert list_lines(uow).items[0].numbering_mode == 'sequential'
                    with pytest.raises(HTTPException) as error:
                        update_line(uow, line.id, body.model_copy(update={'station_count': 19}))
                    assert error.value.status_code == 409
                with EsopTenantUnitOfWork(session, uuid.uuid4()) as uow:
                    with pytest.raises(HTTPException) as error:
                        update_line(uow, line.id, body)
                    assert error.value.status_code == 404
        finally:
            outer.rollback()
