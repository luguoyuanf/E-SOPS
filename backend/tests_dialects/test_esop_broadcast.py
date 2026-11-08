"""Broadcast settings are tenant-local and only active entries reach terminals."""

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.modules.esop import terminal_routes
from app.modules.esop.broadcast_routes import list_broadcasts, save_broadcast
from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import ALL_MODELS, Terminal
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.broadcast_dto import BroadcastInput


def test_broadcast_upsert_tenant_scope_and_active_terminal_feed(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS])
    a, b = uuid.uuid4(), uuid.uuid4()
    terminals = [Terminal(tenant_id=a, device_code="A133-A"), Terminal(tenant_id=b, device_code="A133-B")]
    terminal_ids = [terminal.id for terminal in terminals]
    monkeypatch.setattr(terminal_routes, "product_directory_for_tenant", lambda session, tenant_id: object())
    top = BroadcastInput(
        content="安全第一", font_size=24, background_color="#112233",
        font_color="#FFFFFF", is_active=True,
    )
    bottom = BroadcastInput(
        content="停机检查", font_size=18, background_color="#000000",
        font_color="#FFFF00", is_active=False,
    )
    with Session(engine) as session:
        with EsopTenantUnitOfWork(session, a) as uow:
            session.add(terminals[0])
            session.commit()
            first = save_broadcast(uow, "top", top)
            save_broadcast(uow, "bottom", bottom)
            changed = save_broadcast(uow, "top", top.model_copy(update={"content": "今日目标"}))
            assert first.id == changed.id
            assert list_broadcasts(uow).total == 2
        with EsopTenantUnitOfWork(session, b) as uow:
            session.add(terminals[1])
            session.commit()
            assert list_broadcasts(uow).total == 0
            save_broadcast(uow, "top", top.model_copy(update={"content": "B租户"}))
            assert list_broadcasts(uow).total == 1
        feed_a = terminal_routes.terminal_tasks(session, DeviceIdentity(a, terminal_ids[0]))
        feed_b = terminal_routes.terminal_tasks(session, DeviceIdentity(b, terminal_ids[1]))
        assert feed_a["list"] == []
        assert [(row["position"], row["content"]) for row in feed_a["broadcasts"]] == [
            ("top", "今日目标")
        ]
        assert feed_b["broadcasts"][0]["content"] == "B租户"
    with pytest.raises(ValidationError):
        BroadcastInput(
            content="bad", font_size=9, background_color="red",
            font_color="#FFFFFF", is_active=True,
        )
