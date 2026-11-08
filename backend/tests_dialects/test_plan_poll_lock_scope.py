"""Terminal polling must not lock historical or future production plans."""
import uuid
from datetime import timedelta

from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import ProductionPlan, ProductionPlanGroup
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.plan_scheduler import advance_due_plans


def test_completed_and_future_plans_are_never_locked_by_polling():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[ProductionPlan.__table__, ProductionPlanGroup.__table__])
    tenant = uuid.uuid4()
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant):
        for code, status, start in [("HISTORY", "completed", None),
                                    ("FUTURE", "draft", get_datetime_utc() + timedelta(days=1))]:
            session.add(ProductionPlan(tenant_id=tenant, code=code, order_id=uuid.uuid4(),
                                       line_id=uuid.uuid4(), quantity=1, status=status, start_at=start))
        session.commit()
        locks = []
        def observe(state):
            if getattr(state.statement, "_for_update_arg", None) is not None:
                locks.append(state.statement)
        event.listen(session, "do_orm_execute", observe)
        advance_due_plans(session)
        assert locks == []
    engine.dispose()
