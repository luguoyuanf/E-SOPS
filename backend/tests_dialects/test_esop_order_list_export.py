"""Server-filtered production orders and selected CSV export share a tenant scope."""
import asyncio
import csv
import io
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.modules.esop.infrastructure.models import (
    ProductionOrder,
    ProductionPlan,
    ProductionReport,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.production_routes import export_orders, list_orders
from app.modules.esop.public_api.production_dto import OrderExportInput
from app.modules.esop.report_routes import _progress


class Products:
    def __init__(self, product_id):
        self.product_id = product_id

    def tree(self):
        return [], [SimpleNamespace(id=self.product_id, name="测试膜材")]


async def csv_text(response):
    return "".join([chunk.decode() if isinstance(chunk, bytes) else chunk async for chunk in response.body_iterator])


def test_order_filters_pagination_selected_export_and_tenant_scope():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[ProductionOrder.__table__, ProductionPlan.__table__, WorkRelease.__table__, ProductionReport.__table__])
    tenant, foreign, product = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    products = Products(product)
    with Session(engine) as session:
        with EsopTenantUnitOfWork(session, foreign):
            outsider = ProductionOrder(tenant_id=foreign, code="MO-FOREIGN", product_id=product, quantity=9,
                                       due_date=date(2026, 11, 3), created_at=datetime(2026, 10, 29, 0, tzinfo=UTC))
            outsider_id = outsider.id
            session.add(outsider)
            session.commit()
    with Session(engine) as session, EsopTenantUnitOfWork(session, tenant) as uow:
        old = ProductionOrder(tenant_id=tenant, code="MO-OLD", product_id=product, quantity=8,
                              due_date=date(2026, 11, 2), created_at=datetime(2026, 10, 28, 15, 59, tzinfo=UTC))
        first = ProductionOrder(tenant_id=tenant, code="MO-A", product_id=product, quantity=10,
                                due_date=date(2026, 11, 3), created_at=datetime(2026, 10, 28, 16, 0, tzinfo=UTC))
        last = ProductionOrder(tenant_id=tenant, code="MO-B", product_id=product, quantity=12,
                               due_date=date(2026, 11, 4), created_at=datetime(2026, 10, 29, 15, 59, tzinfo=UTC))
        operation_id, plan_id, release_id, actor_id = (uuid.uuid4() for _ in range(4))
        session.add_all([old, first, last,
                         ProductionPlan(tenant_id=tenant, code="PLAN-VOID", order_id=old.id,
                                        quantity=8, line_id=uuid.uuid4(), status="cancelled"),
                         ProductionPlan(id=plan_id, tenant_id=tenant, code="PLAN-A", order_id=first.id,
                                        quantity=10, line_id=uuid.uuid4(), status="completed"),
                         WorkRelease(id=release_id, tenant_id=tenant, plan_id=plan_id, order_id=first.id,
                                     line_id=uuid.uuid4(), product_id=product, quantity=10, due_date=first.due_date,
                                     assignments=[{"operation_id": str(operation_id)}], published_by=actor_id),
                         ProductionReport(tenant_id=tenant, request_id=uuid.uuid4().hex, request_hash="x" * 64,
                                          staff_user_id=actor_id, staff_name="测试", release_id=release_id,
                                          order_id=first.id, order_code=first.code, station_id=uuid.uuid4(),
                                          station_position=1, operation_id=operation_id, sop_id=uuid.uuid4(),
                                          sop_version=1, sop_title="测试", input_qty=12, good_qty=12)])
        session.commit()
        filters = {"keyword": "测试膜", "created_at_from": date(2026, 10, 29),
                   "created_at_to": date(2026, 10, 29), "due_date_from": date(2026, 11, 3)}
        result = list_orders(uow, products, **filters, page=1, page_size=1)
        assert result.total == 2
        assert len(result.items) == 1 and result.items[0].id == last.id
        assert list_orders(uow, products, **filters, is_published=True).items[0].id == first.id
        assert list_orders(uow, products, **filters, is_published=False).items[0].id == last.id
        assert list_orders(uow, products).total == 3  # No page remains unbounded for plan selector.
        assert not next(item for item in list_orders(uow, products).items if item.id == old.id).is_published
        body = OrderExportInput(ids=[first.id, last.id], **filters)
        exported = asyncio.run(csv_text(export_orders(uow, products, body)))
        lines = list(csv.reader(io.StringIO(exported.removeprefix("\ufeff"))))
        assert lines[0] == ["订单编号", "产品名称", "生产数量", "交期", "创建时间", "发布状态", "生产状态"]
        assert [row[0] for row in lines[1:]] == ["MO-A", "MO-B"]
        assert lines[1][4:] == ["2026-10-29 00:00:00", "已发布", "已完成"]
        assert lines[2][-2:] == ["待发布", "未排产"]
        shifted = asyncio.run(csv_text(export_orders(
            uow, products, body, x_export_timezone="America/New_York",
        )))
        shifted_rows = list(csv.reader(io.StringIO(shifted.removeprefix("\ufeff"))))
        assert shifted_rows[1][3:5] == ["2026-11-03", "2026-10-28 12:00:00"]
        with pytest.raises(HTTPException) as stale:
            export_orders(uow, products, OrderExportInput(ids=[old.id], **filters))
        assert stale.value.status_code == 422
        with pytest.raises(HTTPException) as forbidden:
            export_orders(uow, products, OrderExportInput(ids=[outsider_id]))
        assert forbidden.value.status_code == 422
        with pytest.raises(HTTPException) as reversed_dates:
            list_orders(uow, products, created_at_from=date(2026, 10, 30), created_at_to=date(2026, 10, 29))
        assert reversed_dates.value.status_code == 422
        special = ProductionOrder(tenant_id=tenant, code="MO_%", product_id=product, quantity=1,
                                  due_date=date(2026, 11, 5), created_at=datetime(2026, 10, 29, 3, tzinfo=UTC))
        session.add(special)
        session.commit()
        assert [item.id for item in list_orders(uow, products, keyword="%").items] == [special.id]
        assert [item.id for item in list_orders(uow, products, keyword="_").items] == [special.id]
        first_op, last_op = uuid.uuid4(), uuid.uuid4()
        selected = ProductionOrder(tenant_id=tenant, code="MO-SELECTED", product_id=product, quantity=10,
                                   due_date=date(2026, 11, 5), operation_ids=[str(first_op), str(last_op)])
        selected_plan = ProductionPlan(tenant_id=tenant, code="PLAN-SELECTED", order_id=selected.id,
                                       quantity=10, line_id=uuid.uuid4(), status="completed")
        selected_release = WorkRelease(tenant_id=tenant, plan_id=selected_plan.id, order_id=selected.id,
                                       line_id=selected_plan.line_id, product_id=product, quantity=10,
                                       due_date=selected.due_date, published_by=actor_id,
                                       assignments=[{"operation_id": str(first_op)}, {"operation_id": str(last_op)}])
        session.add_all([selected, selected_plan, selected_release,
                         ProductionReport(tenant_id=tenant, request_id=uuid.uuid4().hex, request_hash="y" * 64,
                                          staff_user_id=actor_id, staff_name="测试", release_id=selected_release.id,
                                          order_id=selected.id, order_code=selected.code, station_id=uuid.uuid4(),
                                          station_position=2, operation_id=last_op, sop_id=uuid.uuid4(),
                                          sop_version=1, sop_title="末道", input_qty=12, good_qty=10,
                                          defect_qty=2)])
        session.commit()
        selected_status = next(item for item in list_orders(uow, products).items if item.id == selected.id)
        assert selected_status.production_status == "in_progress"
        partial = _progress(session, selected)
        assert (partial.good_total, partial.bad_total, partial.completion_rate) == (0, 2, 50)
        assert [item.completion_rate for item in partial.operations] == [0, 100]
        assert [item.bad_total for item in partial.operations] == [0, 2]
        session.add(ProductionReport(tenant_id=tenant, request_id=uuid.uuid4().hex, request_hash="z" * 64,
                                     staff_user_id=actor_id, staff_name="测试", release_id=selected_release.id,
                                     order_id=selected.id, order_code=selected.code, station_id=uuid.uuid4(),
                                     station_position=1, operation_id=first_op, sop_id=uuid.uuid4(),
                                     sop_version=1, sop_title="首道", input_qty=11, good_qty=10,
                                     defect_qty=1))
        session.commit()
        selected_status = next(item for item in list_orders(uow, products).items if item.id == selected.id)
        assert selected_status.production_status == "completed"
        complete = _progress(session, selected)
        assert (complete.good_total, complete.bad_total, complete.completion_rate) == (10, 3, 100)
        assert [item.completed_total for item in complete.operations] == [11, 12]
        assert [item.bad_total for item in complete.operations] == [1, 2]
        split = ProductionOrder(tenant_id=tenant, code="MO-SPLIT-OPERATIONS", product_id=product,
                                quantity=10, due_date=date(2026, 11, 5),
                                operation_ids=[str(first_op), str(last_op)])
        session.add(split)
        for index, operation_id in enumerate((first_op, last_op)):
            plan = ProductionPlan(tenant_id=tenant, code=f"PLAN-SPLIT-{index}", order_id=split.id,
                                  quantity=10, line_id=uuid.uuid4(), status="completed")
            release = WorkRelease(tenant_id=tenant, plan_id=plan.id, order_id=split.id,
                                  line_id=plan.line_id, product_id=product, quantity=10,
                                  due_date=split.due_date, published_by=actor_id,
                                  assignments=[{"operation_id": str(operation_id)}])
            session.add_all([plan, release, ProductionReport(
                tenant_id=tenant, request_id=uuid.uuid4().hex, request_hash="s" * 64,
                staff_user_id=actor_id, staff_name="测试", release_id=release.id,
                order_id=split.id, order_code=split.code, station_id=uuid.uuid4(),
                station_position=index + 1, operation_id=operation_id, sop_id=uuid.uuid4(),
                sop_version=1, sop_title="工序", input_qty=10, good_qty=10,
            )])
        session.commit()
        assert _progress(session, split).good_total == 10
