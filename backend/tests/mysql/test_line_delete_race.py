"""Concurrent binding/deletion must not leave a terminal pointing at a deleted station."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.modules.esop.infrastructure.models import ProductionLine, Station, Terminal
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.production_routes import delete_line
from app.modules.esop.terminal_routes import bind_terminal_station


def test_deleted_line_cannot_be_bound_and_committed_binding_blocks_delete():
    assert settings.MYSQL_DB == "esop_fva_test_20261024"
    tenant = uuid.uuid4()
    line = ProductionLine(
        tenant_id=tenant,
        workshop_id=uuid.uuid4(),
        code="RACE-LINE",
        name="删除并发验收",
    )
    station = Station(tenant_id=tenant, line_id=line.id, position=1, row=1, column=1)
    terminal = Terminal(tenant_id=tenant, device_code="RACE-TERMINAL")
    lid, sid, did = line.id, station.id, terminal.id
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
        session.add_all([line, station, terminal])
        session.commit()

    def bind():
        with Session(engine) as session, EsopTenantUnitOfWork(session, tenant) as uow:
            try:
                bind_terminal_station(uow, did, SimpleNamespace(station_id=sid))
                return 200
            except HTTPException as error:
                return error.status_code

    def delete():
        with Session(engine) as session, EsopTenantUnitOfWork(session, tenant) as uow:
            try:
                delete_line(uow, lid)
                return 204
            except HTTPException as error:
                return error.status_code

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            # Hold the parent lock so binder waits, then remove the parent and station.
            with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
                parent = session.exec(
                    select(ProductionLine)
                    .where(ProductionLine.id == lid)
                    .with_for_update()
                ).one()
                future = pool.submit(bind)
                session.delete(session.get(Station, sid))
                session.delete(parent)
                session.commit()
            assert future.result(timeout=20) == 404
            with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
                assert session.get(Terminal, did).station_id is None
                session.add(
                    ProductionLine(
                        id=lid,
                        tenant_id=tenant,
                        workshop_id=uuid.uuid4(),
                        code="RACE-LINE",
                        name="删除并发验收",
                    )
                )
                session.add(
                    Station(
                        id=sid,
                        tenant_id=tenant,
                        line_id=lid,
                        position=1,
                        row=1,
                        column=1,
                    )
                )
                session.commit()
            # Bind under the same parent lock, release it only after commit.
            with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
                session.exec(
                    select(ProductionLine)
                    .where(ProductionLine.id == lid)
                    .with_for_update()
                ).one()
                bound = session.get(Terminal, did)
                bound.station_id = sid
                session.add(bound)
                session.flush()
                future = pool.submit(delete)
                session.commit()
            assert future.result(timeout=20) == 409
    finally:
        with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
            for model, ident in [
                (Terminal, did),
                (Station, sid),
                (ProductionLine, lid),
            ]:
                row = session.get(model, ident)
                if row:
                    session.delete(row)
            session.commit()
