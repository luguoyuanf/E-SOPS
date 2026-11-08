"""Reference checks against the fixed test MySQL; fixtures roll back in full."""

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.modules.esop.infrastructure.models import (
    AlarmEvent,
    ProductionLine,
    ProductionPlan,
    ProductionReport,
    Station,
    Terminal,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.production_routes import create_line, create_workshop, delete_line
from app.modules.esop.public_api.production_dto import LineInput, WorkshopInput


@pytest.mark.parametrize(
    "kind",
    [
        "unused",
        "plan",
        "completed",
        "cross_plan",
        "release",
        "cross_release",
        "terminal",
        "disabled_terminal",
        "report",
        "alarm",
    ],
)
def test_line_delete_preserves_live_and_history_data(kind):
    assert settings.MYSQL_DB == "esop_fva_test_20261024"
    tenant_id = uuid.uuid4()
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            ) as session:
                with EsopTenantUnitOfWork(session, tenant_id) as uow:
                    workshop = create_workshop(
                        uow, WorkshopInput(code="DEL-WS", name="删除验收车间")
                    )
                    line = create_line(
                        uow,
                        LineInput(
                            workshop_id=workshop.id,
                            code="DEL-LINE",
                            name="删除验收线",
                            layout="double",
                            station_count=2,
                        ),
                    )
                    station_id = line.stations[0].id
                    reference = None
                    if kind in ("plan", "completed", "cross_plan"):
                        reference = ProductionPlan(
                            tenant_id=tenant_id,
                            line_id=uuid.uuid4() if kind == "cross_plan" else line.id,
                            order_id=uuid.uuid4(),
                            code="DEL-PLAN",
                            status="completed" if kind == "completed" else "draft",
                            assignments=[{"station_id": str(station_id)}],
                        )
                    elif kind in ("release", "cross_release"):
                        reference = WorkRelease(
                            tenant_id=tenant_id,
                            line_id=uuid.uuid4()
                            if kind == "cross_release"
                            else line.id,
                            plan_id=uuid.uuid4(),
                            order_id=uuid.uuid4(),
                            product_id=uuid.uuid4(),
                            quantity=1,
                            due_date=date.today(),
                            published_by=uuid.uuid4(),
                            is_active=False,
                            assignments=[{"station_id": str(station_id)}],
                        )
                    elif kind in ("terminal", "disabled_terminal"):
                        reference = Terminal(
                            tenant_id=tenant_id,
                            device_code="DEL-DEVICE",
                            station_id=station_id,
                            is_active=kind == "terminal",
                        )
                    elif kind == "report":
                        reference = ProductionReport(
                            tenant_id=tenant_id,
                            terminal_id=uuid.uuid4(),
                            request_id="DEL-REPORT",
                            request_hash="0" * 64,
                            staff_user_id=uuid.uuid4(),
                            staff_name="测试员工",
                            release_id=uuid.uuid4(),
                            order_id=uuid.uuid4(),
                            order_code="DEL-ORDER",
                            station_id=station_id,
                            station_position=1,
                            operation_id=uuid.uuid4(),
                            sop_id=uuid.uuid4(),
                            sop_version=1,
                            sop_title="测试SOP",
                        )
                    elif kind == "alarm":
                        reference = AlarmEvent(
                            tenant_id=tenant_id,
                            terminal_id=uuid.uuid4(),
                            station_id=station_id,
                            request_id="DEL-ALARM",
                            request_hash="0" * 64,
                            level="warning",
                            reason="删除引用测试",
                        )
                    if reference:
                        session.add(reference)
                        session.commit()
                        with pytest.raises(HTTPException) as error:
                            delete_line(uow, line.id)
                        assert error.value.status_code == 409
                        assert session.get(ProductionLine, line.id) is not None
                        assert (
                            len(
                                session.exec(
                                    select(Station).where(Station.line_id == line.id)
                                ).all()
                            )
                            == 2
                        )
                        assert session.get(type(reference), reference.id) is not None
                        session.delete(reference)
                        session.commit()
                    delete_line(uow, line.id)
                    assert session.get(ProductionLine, line.id) is None
                    assert (
                        session.exec(
                            select(Station).where(Station.line_id == line.id)
                        ).all()
                        == []
                    )
                with EsopTenantUnitOfWork(session, uuid.uuid4()) as uow:
                    with pytest.raises(HTTPException) as error:
                        delete_line(uow, line.id)
                    assert error.value.status_code == 404
        finally:
            outer.rollback()
