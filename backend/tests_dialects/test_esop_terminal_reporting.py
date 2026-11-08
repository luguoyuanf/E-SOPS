"""Tenant activation and offline intake guardrails."""

import uuid
from types import SimpleNamespace
from datetime import date

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.modules.esop.infrastructure.device_auth import (
    activate_device,
    issue_key,
    resolve_device,
)
from app.modules.esop.infrastructure.models import (
    ALL_MODELS,
    ProductionOrder,
    ProductionReport,
    Station,
    Terminal,
    WorkRelease,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.terminal_dto import ReportInput
from app.modules.esop.report_routes import submit_report
from app.platform.public_api.users import UserSummary
from app.platform.web_api import Principal, TenantContext


class StaffDirectory:
    def __init__(self, id: uuid.UUID) -> None:
        self.id = id

    def get_users(self, ids):
        return [UserSummary(id=self.id, full_name="Operator", is_active=True)] if self.id in ids else []


@pytest.fixture(autouse=True)
def activation_cipher(monkeypatch):
    monkeypatch.setattr(settings, "ESOP_ACTIVATION_CIPHER_KEY", Fernet.generate_key().decode())


def test_free_key_activates_once_and_offline_report_is_idempotent(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS])
    tenant, other, staff_id, order_id, release_id, sop_id = (uuid.uuid4() for _ in range(6))
    principal = Principal(id=staff_id, is_superuser=False)
    monkeypatch.setattr("app.platform.web_api.resolve_channel_customer_code",
        lambda **kwargs: SimpleNamespace(id=tenant, code="test-tenant", name="Test"))
    with Session(engine) as session:
        key_row, key = issue_key(session, tenant, grant_type="free")
        session.commit()
        assert len(key) == 8 and key_row.grant_type == "free"
        identity, token = activate_device(session, key=key, device_code="A133-001", old_token=None, tenant_code="test-tenant")
        assert identity.tenant_id == tenant
        assert resolve_device(session, token) == identity
        same, same_token = activate_device(session, key=key, device_code="A133-001", old_token=token, tenant_code="test-tenant")
        assert same == identity and same_token == token
        with pytest.raises(HTTPException) as reused:
            activate_device(session, key=key, device_code="A133-002", old_token=None, tenant_code="test-tenant")
        assert reused.value.status_code == 409
        with EsopTenantUnitOfWork(session, tenant):
            station = Station(tenant_id=tenant, line_id=uuid.uuid4(), position=1, row=1, column=1)
            session.add(station)
            terminal = session.get(Terminal, identity.terminal_id)
            terminal.station_id = station.id
            session.add(terminal)
            session.add(ProductionOrder(
                id=order_id, tenant_id=tenant, code="PO-1", product_id=uuid.uuid4(),
                quantity=10, due_date=date(2026, 11, 1),
            ))
            session.add(WorkRelease(
                id=release_id, tenant_id=tenant, plan_id=uuid.uuid4(), order_id=order_id,
                line_id=station.line_id, product_id=uuid.uuid4(), quantity=10,
                due_date=date(2026, 11, 1), published_by=staff_id,
                assignments=[{
                    "station_id": str(station.id), "station_position": 1,
                    "operation_id": str(uuid.uuid4()), "sop_id": str(sop_id),
                    "sop_version": 1, "sop_title": "装配",
                }],
            ))
            session.commit()
        body = ReportInput(
            requestId="offline-1", releaseId=release_id, orderId=order_id,
            sopId=sop_id, inputQty=10, goodQty=9, defectQty=1,
        )
        context = TenantContext(tenant_id=tenant, tenant_code="T", user_id=staff_id)
        first = submit_report(session, identity, principal, context, StaffDirectory(staff_id), body)
        second = submit_report(session, identity, principal, context, StaffDirectory(staff_id), body)
        assert first.id == second.id and first.sop_version == 1
        with EsopTenantUnitOfWork(session, tenant):
            assert len(session.exec(select(ProductionReport)).all()) == 1
        with pytest.raises(HTTPException) as cross_tenant:
            submit_report(
                session, identity, principal,
                TenantContext(tenant_id=other, tenant_code="OTHER", user_id=staff_id),
                StaffDirectory(staff_id), body,
            )
        assert cross_tenant.value.status_code == 403
        with pytest.raises(HTTPException) as changed:
            submit_report(session, identity, principal, context, StaffDirectory(staff_id), body.model_copy(update={"goodQty": 8}))
        assert changed.value.status_code == 409
