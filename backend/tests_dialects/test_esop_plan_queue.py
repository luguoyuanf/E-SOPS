"""Plan queue changes display content without losing task or report identity."""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.modules.esop.infrastructure.models import (
    OWNED_MODELS,
    ProductionLine,
    ProductionOrder,
    ProductionPlan,
    ProductionPlanGroup,
    ProductionReport,
    ProductSopVersion,
    SopDocument,
    Station,
    Terminal,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.plan_scheduler import advance_due_plans
from app.modules.esop.production_routes import (
    _validate_assignments,
    delete_plan_group,
    list_plans,
    pause_plan,
    pause_plan_group,
    read_plan_release,
    read_plan_task,
    remove_unbound_plan_station,
    start_now_plan_group,
    update_plan_group,
)
from app.modules.esop.public_api.production_dto import (
    Assignment,
    PlanGroupInput,
    PlanInput,
)
from app.modules.esop.terminal_routes import _active_tasks, current_assignment


def test_completed_group_cannot_be_paused():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in OWNED_MODELS])
    tenant, actor = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant) as uow:
        group = ProductionPlanGroup(tenant_id=tenant, created_by=actor, name="已完成组")
        plan = ProductionPlan(tenant_id=tenant, created_by=actor, order_id=uuid.uuid4(),
                              line_id=uuid.uuid4(), quantity=1, group_id=group.id,
                              group_position=0, status="completed")
        session.add_all([group, plan])
        session.commit()
        with pytest.raises(HTTPException) as error:
            pause_plan_group(uow, group.id)
        assert error.value.status_code == 409
        assert group.is_paused is False
        plan.status = "draft"
        session.commit()
        assert pause_plan_group(uow, group.id).is_paused is True
        with pytest.raises(HTTPException) as already_paused:
            pause_plan_group(uow, group.id)
        assert already_paused.value.status_code == 409


def test_group_advances_after_all_reports_and_terminal_reads_new_approved_sop(monkeypatch):
    from app.modules.esop import production_routes

    monkeypatch.setattr(production_routes, "lock_product", lambda _uow, _id: None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in OWNED_MODELS])
    tenant, actor, product, operation = (uuid.uuid4() for _ in range(4))
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant) as uow:
        line_a = ProductionLine(tenant_id=tenant, workshop_id=uuid.uuid4(), code="A", name="A", station_count=1)
        line_b = ProductionLine(tenant_id=tenant, workshop_id=uuid.uuid4(), code="B", name="B", station_count=1)
        station_a = Station(tenant_id=tenant, line_id=line_a.id, position=1, row=1, column=1)
        station_b = Station(tenant_id=tenant, line_id=line_b.id, position=1, row=1, column=1)
        terminal_a = Terminal(tenant_id=tenant, device_code="A", station_id=station_a.id)
        terminal_b = Terminal(tenant_id=tenant, device_code="B", station_id=station_b.id)
        order = ProductionOrder(tenant_id=tenant, code="PO1", product_id=product, quantity=5, due_date=date(2026, 11, 1))
        old_sop = SopDocument(tenant_id=tenant, family_id=uuid.uuid4(), product_id=product,
                              operation_id=operation, status="approved", title="旧指导", created_by=actor)
        version = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品",
                                    version=1, status="approved", created_by=actor,
                                    operations=[{"id": str(operation), "code": "OP", "name": "工序", "sop_id": str(old_sop.id)}])
        group = ProductionPlanGroup(tenant_id=tenant, created_by=actor, name="早班", is_paused=False)
        assignments = [{"operation_id": str(operation), "station_id": str(station.id), "sop_id": str(old_sop.id)}
                       for station in (station_a, station_b)]
        first = ProductionPlan(tenant_id=tenant, created_by=actor, order_id=order.id, line_id=line_a.id,
                               quantity=3, group_id=group.id, group_position=0, assignments=assignments)
        second = ProductionPlan(tenant_id=tenant, created_by=actor, order_id=order.id, line_id=line_a.id,
                                quantity=2, group_id=group.id, group_position=1, assignments=assignments)
        session.add_all([line_a, line_b, station_a, station_b, terminal_a, terminal_b, order, old_sop, version, group, first, second])
        session.commit()

        terminal_b.station_id = None
        session.commit()
        with pytest.raises(HTTPException) as unbound:
            _validate_assignments(uow, PlanInput(
                order_id=order.id, line_id=line_a.id, product_sop_version_id=version.id,
                assignments=[Assignment.model_validate(item) for item in assignments],
            ), complete=True)
        assert unbound.value.status_code == 422
        terminal_b.station_id = station_b.id
        session.commit()

        reordered = update_plan_group(uow, group.id, PlanGroupInput(name="早班", plan_ids=[second.id, first.id]))
        assert reordered.plan_ids == [second.id, first.id]
        assert second.group_position == 0 and first.group_position == 1
        update_plan_group(uow, group.id, PlanGroupInput(name="早班", plan_ids=[first.id, second.id]))
        future = datetime.now(UTC) + timedelta(days=1)
        group.start_at = future
        first.start_at = future
        session.commit()
        page = list_plans(uow, page=1, page_size=1)
        assert page.total == 2 and len(page.items) == 1
        matching = list_plans(uow, page=1, page_size=20, keyword=first.code, status="draft")
        assert matching.total == 1 and matching.items[0].code == first.code
        advance_due_plans(session)
        assert first.status == "draft"
        started = start_now_plan_group(uow, group.id, SimpleNamespace(id=actor))
        assert started.start_at < future and started.plan_ids == [first.id, second.id]
        assert first.status == "published" and second.status == "draft"
        release = session.exec(select(WorkRelease).where(WorkRelease.plan_id == first.id)).one()
        assert read_plan_release(uow, first.id).id == release.id
        assert release.is_active and len(release.assignments) == 2

        pause_plan(uow, first.id)
        assert first.status == "paused" and release.is_active is False
        advance_due_plans(session)
        assert second.status == "draft"
        assert pause_plan_group(uow, group.id).is_paused is True
        assert start_now_plan_group(uow, group.id, SimpleNamespace(id=actor)).is_paused is False
        assert first.status == "published"
        assert release.is_active

        new_sop = SopDocument(tenant_id=tenant, family_id=old_sop.family_id, product_id=product,
                              operation_id=operation, version=2, status="approved", title="新指导", created_by=actor)
        latest = ProductSopVersion(tenant_id=tenant, product_id=product, product_name="产品",
                                   version=2, status="approved", created_by=actor,
                                   operations=[{"id": str(operation), "code": "OP", "name": "工序", "sop_id": str(new_sop.id)}])
        session.add_all([new_sop, latest])
        session.commit()
        visible = current_assignment(session, release, release.assignments[0])
        assert visible and visible["sop_id"] == str(new_sop.id) and visible["sop_title"] == "新指导"

        paused_group = pause_plan_group(uow, group.id)
        assert paused_group.is_paused is True
        assert first.status == "published" and release.is_active is True
        assert start_now_plan_group(uow, group.id, SimpleNamespace(id=actor)).is_paused is False
        assert first.status == "published" and second.status == "draft"
        assert pause_plan_group(uow, group.id).is_paused is True

        report = ProductionReport(
            tenant_id=tenant, terminal_id=uuid.uuid4(), request_id="r1", request_hash="x" * 64,
            staff_user_id=actor, staff_name="员工", release_id=release.id, order_id=order.id,
            order_code=order.code, station_id=station_a.id, station_position=1,
            operation_id=operation, sop_id=new_sop.id, sop_version=2, sop_title="新指导",
            input_qty=3, good_qty=3, defect_qty=0,
        )
        session.add(report)
        session.commit()
        advance_due_plans(session)
        assert first.status == "completed" and release.is_active is False
        assert second.status == "draft"
        assert start_now_plan_group(uow, group.id, SimpleNamespace(id=actor)).is_paused is False
        assert second.status == "published"
        second_release = session.exec(select(WorkRelease).where(WorkRelease.plan_id == second.id)).one()
        session.add(ProductionReport(
            tenant_id=tenant, terminal_id=terminal_b.id, request_id="r2", request_hash="y" * 64,
            staff_user_id=actor, staff_name="员工", release_id=second_release.id, order_id=order.id,
            order_code=order.code, station_id=station_b.id, station_position=1,
            operation_id=operation, sop_id=new_sop.id, sop_version=2, sop_title="新指导",
            input_qty=1, good_qty=1, defect_qty=0,
        ))
        session.commit()
        detail = read_plan_task(uow, second.id)
        assert detail.release.quantity == 2 and len(detail.operations[0].stations) == 2
        with pytest.raises(HTTPException) as still_bound:
            remove_unbound_plan_station(uow, second.id, station_b.id)
        assert still_bound.value.status_code == 409
        station_b.current_release_id = second_release.id
        terminal_b.station_id = None
        session.commit()
        removed = remove_unbound_plan_station(uow, second.id, station_b.id)
        assert len(removed.release.assignments) == 1
        assert len(second.assignments) == 1 and second.status == "published"
        assert station_b.current_release_id is None
        assert any(not station.is_assigned and station.good_total == 1 for station in removed.operations[0].stations)
        terminal_b.station_id = station_b.id
        session.commit()
        assert _active_tasks(session, terminal_b) == []
        updated_group = update_plan_group(uow, group.id, PlanGroupInput(name="早班", plan_ids=[first.id]))
        assert updated_group.is_paused is True
        assert second.group_id is None and second.status == "published"
        assert delete_plan_group(uow, group.id) == {"ok": True}
        assert session.get(ProductionPlan, first.id).group_id is None
        assert session.get(ProductionPlan, second.id).status == "published"
        assert session.get(ProductionPlanGroup, group.id) is None
        with pytest.raises(HTTPException) as duplicate_station:
            _validate_assignments(uow, PlanInput(
                order_id=order.id, line_id=line_a.id,
                assignments=[Assignment(operation_id=operation, station_id=station_a.id, sop_id=new_sop.id)] * 2,
            ), complete=True)
        assert duplicate_station.value.status_code == 422


def test_removing_last_unbound_station_pauses_plan_and_group():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in OWNED_MODELS])
    tenant, actor, product, operation, sop = (uuid.uuid4() for _ in range(5))
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant) as uow:
        line = ProductionLine(tenant_id=tenant, workshop_id=uuid.uuid4(), code="A", name="A", station_count=1)
        station = Station(tenant_id=tenant, line_id=line.id, position=1, row=1, column=1)
        order = ProductionOrder(tenant_id=tenant, code="PO1", product_id=product, quantity=10, due_date=date(2026, 11, 1))
        group = ProductionPlanGroup(tenant_id=tenant, created_by=actor, name="组")
        assignment = {"operation_id": str(operation), "station_id": str(station.id), "sop_id": str(sop)}
        plan = ProductionPlan(tenant_id=tenant, created_by=actor, order_id=order.id, line_id=line.id,
                              quantity=10, group_id=group.id, group_position=0, status="published", assignments=[assignment])
        release = WorkRelease(tenant_id=tenant, plan_id=plan.id, order_id=order.id, line_id=line.id,
                              product_id=product, quantity=10, due_date=order.due_date, published_by=actor,
                              assignments=[{**assignment, "operation_name": "工序", "station_position": 1,
                                            "station_row": 1, "station_column": 1, "sop_title": "指导书", "sop_version": 1}])
        session.add_all([line, station, order, group, plan, release])
        session.commit()
        detail = remove_unbound_plan_station(uow, plan.id, station.id)
        assert detail.plan.status == "paused" and detail.release.assignments == []
        assert release.is_active is False and group.is_paused is True
        assert session.get(ProductionPlan, plan.id).assignments == []
