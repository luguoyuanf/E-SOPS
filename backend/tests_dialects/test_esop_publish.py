"""Publish only complete tenant-local plans with approved SOP snapshots."""

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.modules.esop.infrastructure.models import (
    OWNED_MODELS,
    ProductionOrder,
    ProductSopVersion,
    Terminal,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.production_routes import (
    confirm_order_operations,
    create_line,
    create_order,
    create_plan,
    create_workshop,
    publish_plan,
    update_order,
    update_plan,
)
from app.modules.esop.public_api.dto import (
    OperationInput,
    RouteInput,
    SopCreate,
    SopPage,
)
from app.modules.esop.public_api.production_dto import (
    Assignment,
    LineInput,
    OrderInput,
    OrderOperationsInput,
    PlanInput,
    WorkshopInput,
)
from app.modules.esop.routes import (
    approve_sop,
    create_operation,
    create_route,
    create_sop,
    new_sop_version,
    submit_sop,
)
from app.platform.public_api.files import FileAssetSummary
from app.platform.web_api import Principal


class Products:
    def __init__(self, product_id: uuid.UUID) -> None:
        self.product_id = product_id

    def exists(self, product_id: uuid.UUID) -> bool:
        return product_id == self.product_id


class Files:
    def __init__(self, file_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        self.file_id, self.tenant_id = file_id, tenant_id

    def get_accessible_file(
        self, *, tenant_id: uuid.UUID, file_id: uuid.UUID
    ) -> FileAssetSummary | None:
        if tenant_id != self.tenant_id or file_id != self.file_id:
            return None
        return FileAssetSummary(id=file_id, original_name="test.pdf", content_type="application/pdf", size=12, sha256="0" * 64)


def test_publish_accepts_staffed_operations_and_rejects_invalid_assignments():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in OWNED_MODELS])
    tenant_a, tenant_b, product_id, file_id = (uuid.uuid4() for _ in range(4))
    principal = Principal(id=uuid.uuid4(), is_superuser=False)
    products, files = Products(product_id), Files(file_id, tenant_a)
    with Session(engine) as session:
        with EsopTenantUnitOfWork(session, tenant_a) as uow:
            workshop = create_workshop(uow, WorkshopInput(code="W1", name="一车间"))
            line = create_line(uow, LineInput(
                workshop_id=workshop.id, code="L1", name="一号线",
                layout="double", station_count=3,
            ))
            assert [(station.row, station.column) for station in line.stations] == [
                (1, 1), (2, 1), (1, 2)
            ]
            session.add_all([
                Terminal(tenant_id=tenant_a, device_code="T1", station_id=line.stations[0].id),
                Terminal(tenant_id=tenant_a, device_code="T2", station_id=line.stations[1].id),
            ])
            session.commit()
            order = ProductionOrder(tenant_id=tenant_a, code="PO1", product_id=product_id,
                                    quantity=300, due_date=date(2026, 10, 30))
            session.add(order)
            session.commit()
            op1 = create_operation(uow, OperationInput(code="P1", name="装配"), None, None)
            op2 = create_operation(uow, OperationInput(code="P2", name="检查"), None, None)
            route = create_route(uow, RouteInput(
                code="R1", name="主流程", operation_ids=[op1.id, op2.id],
            ))
            sop_ids = []
            for operation_id in (op1.id, op2.id):
                sop = create_sop(uow, principal, products, files, SopCreate(
                    product_id=product_id, operation_id=operation_id,
                    title="作业指导", pages=[SopPage(file_id=file_id, sort=0)],
                ))
                submit_sop(uow, sop.id)
                approve_sop(uow, principal, sop.id)
                sop_ids.append(sop.id)
            session.add(ProductSopVersion(
                tenant_id=tenant_a, product_id=product_id, product_name="产品", version=1,
                status="approved", created_by=principal.id,
                operations=[
                    {"id": str(op1.id), "code": "P1", "name": "装配", "sop_id": str(sop_ids[0])},
                    {"id": str(op2.id), "code": "P2", "name": "检查", "sop_id": str(sop_ids[1])},
                ],
            ))
            session.commit()
            version = session.exec(select(ProductSopVersion)).first()
            selected_order = create_order(uow, products, OrderInput(
                code="PO-SELECTED", product_id=product_id, quantity=30,
                due_date=date(2026, 10, 30), product_sop_version_id=version.id,
                operation_ids=[op1.id, op2.id],
            ))
            assert selected_order.product_sop_version_id == version.id
            assert selected_order.operation_ids == [op1.id, op2.id]
            session.add(ProductSopVersion(
                tenant_id=tenant_a, product_id=product_id, product_name="产品", version=2,
                status="approved", created_by=principal.id, operations=version.operations,
            ))
            session.commit()
            selected_plan = create_plan(uow, PlanInput(
                order_id=selected_order.id, line_id=line.id, quantity=30,
                assignments=[Assignment(operation_id=op1.id, station_id=line.stations[0].id, sop_id=sop_ids[0])],
            ), principal)
            assert selected_plan.product_sop_version_id == version.id
            assert selected_plan.status == "draft"
            first = Assignment(
                operation_id=op1.id, station_id=line.stations[0].id, sop_id=sop_ids[0]
            )
            plan = create_plan(uow, PlanInput(
                code="PLAN-SHIFT-A",
                order_id=order.id, line_id=line.id, route_id=route.id, quantity=100,
                assignments=[first],
            ), principal)
            assert plan.code == "PLAN-SHIFT-A"
            wrong = Assignment(
                operation_id=op2.id, station_id=line.stations[1].id, sop_id=sop_ids[0]
            )
            with pytest.raises(HTTPException) as mismatch:
                update_plan(uow, plan.id, PlanInput(
                    order_id=order.id, line_id=line.id, route_id=route.id,
                    assignments=[first, wrong],
                ))
            assert mismatch.value.status_code == 422
            second = Assignment(
                operation_id=op2.id, station_id=line.stations[1].id, sop_id=sop_ids[1]
            )
            release = publish_plan(uow, principal, plan.id)
            assert release.product_id == product_id
            assert release.quantity == 100
            assert [(item.sop_id, item.sop_version) for item in release.assignments] == [
                (sop_ids[0], 1)
            ]
            updated_sop = new_sop_version(uow, principal, sop_ids[0])
            submit_sop(uow, updated_sop.id)
            approve_sop(uow, principal, updated_sop.id)
            assert session.get(WorkRelease, release.id).assignments[0]["sop_id"] == str(sop_ids[0])
            draft_after_review = create_plan(uow, PlanInput(
                order_id=order.id, line_id=line.id, route_id=route.id, quantity=100,
                assignments=[first],
            ), principal)
            assert draft_after_review.status == "draft"
            with pytest.raises(HTTPException) as duplicate:
                publish_plan(uow, principal, plan.id)
            assert duplicate.value.status_code == 409
            with pytest.raises(HTTPException) as edit_published:
                update_plan(uow, plan.id, PlanInput(
                    order_id=order.id, line_id=line.id, route_id=route.id,
                ))
            assert edit_published.value.status_code == 409
            with pytest.raises(HTTPException) as edit_order:
                update_order(uow, products, order.id, OrderInput(
                    code="PO1", product_id=product_id, quantity=200,
                    due_date=date(2026, 11, 1),
                ))
            assert edit_order.value.status_code == 409
            direct = create_plan(uow, PlanInput(
                order_id=order.id, line_id=line.id, quantity=100,
                assignments=[
                    Assignment(operation_id=op1.id, station_id=line.stations[0].id, sop_id=updated_sop.id),
                    second,
                ],
            ), principal)
            assert direct.route_id is None
            with pytest.raises(HTTPException) as line_busy:
                publish_plan(uow, principal, direct.id)
            assert line_busy.value.status_code == 409
            assert session.get(WorkRelease, release.id).is_active is True
            with pytest.raises(HTTPException) as mismatched_history:
                confirm_order_operations(uow, order.id, OrderOperationsInput(
                    product_sop_version_id=version.id, operation_ids=[op1.id, op2.id],
                ))
            assert mismatched_history.value.status_code == 409
            confirmed = confirm_order_operations(uow, order.id, OrderOperationsInput(
                product_sop_version_id=version.id, operation_ids=[op1.id],
            ))
            assert confirmed.operation_ids == [op1.id]
        with EsopTenantUnitOfWork(session, tenant_b):
            assert session.exec(select(WorkRelease)).all() == []
