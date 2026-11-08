"""Fixed online test DB only; outer transaction rolls all fixtures back."""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session

from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.core.database import engine
from app.modules.esop import broadcast_routes, terminal_routes
from app.modules.esop.infrastructure.models import Station, Terminal
from app.modules.esop.infrastructure.tenant_uow import (
    EsopTenantUnitOfWork,
    TenantScopeError,
)
from app.modules.esop.public_api.broadcast_dto import AdvertisementInput


def payload(**changes):
    return AdvertisementInput.model_validate(
        {
            "title": "验收广告",
            "media": [{"kind": "text", "content": "安全第一", "duration_seconds": 1}],
            "is_active": True,
            **changes,
        }
    )


def test_schedule_validation():
    now = get_datetime_utc()
    for changes in (
        {"media": []},
        {"media": [{"kind": "image"}]},
        {"media": [{"kind": "text", "content": " "}]},
        {"interval_minutes": 0},
        {"daily_start": "12:00"},
        {"daily_start": "25:00", "daily_end": "13:00"},
        {"starts_at": now, "ends_at": now - timedelta(seconds=1)},
        {"starts_at": "2026-01-01T00:00:00"},
    ):
        with pytest.raises(ValidationError):
            payload(**changes)
    assert payload(daily_start="22:00", daily_end="06:00").daily_end == "06:00"


def test_advertisements_crud_tenant_scope_and_device_feed(monkeypatch):
    assert settings.MYSQL_DB == "esop_fva_test_20261024"
    monkeypatch.setattr(
        terminal_routes, "product_directory_for_tenant", lambda *args: object()
    )
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            ) as session:
                with EsopTenantUnitOfWork(session, tenant_a) as uow:
                    station = Station(
                        tenant_id=tenant_a,
                        line_id=uuid.uuid4(),
                        code="AD-ACCEPT",
                        position=1,
                        row=1,
                        column=1,
                    )
                    terminal = Terminal(
                        tenant_id=tenant_a,
                        station_id=station.id,
                        device_code="AD-ACCEPT",
                    )
                    session.add_all([station, terminal])
                    session.commit()
                    identity = SimpleNamespace(
                        tenant_id=tenant_a, terminal_id=terminal.id
                    )
                    ad = broadcast_routes.create_advertisement(
                        uow, payload(playback="interval", interval_minutes=2)
                    )
                    assert broadcast_routes.list_advertisements(uow).total == 1
                    feed = terminal_routes.terminal_tasks(session, identity)
                    assert feed["advertisements"][0]["id"] == str(ad.id)
                    assert feed["advertisements"][0]["intervalMinutes"] == 2
                    future = get_datetime_utc() + timedelta(days=1)
                    changed = broadcast_routes.update_advertisement(
                        uow, ad.id, payload(starts_at=future, layout="left")
                    )
                    assert changed.starts_at == future and changed.layout == "left"
                    broadcast_routes.update_advertisement(
                        uow, ad.id, payload(starts_at=future, is_active=False)
                    )
                    assert (
                        terminal_routes.terminal_tasks(session, identity)[
                            "advertisements"
                        ]
                        == []
                    )
                with EsopTenantUnitOfWork(session, tenant_b) as uow:
                    assert broadcast_routes.list_advertisements(uow).total == 0
                    for operation in (
                        lambda: broadcast_routes.update_advertisement(
                            uow, ad.id, payload()
                        ),
                        lambda: broadcast_routes.delete_advertisement(uow, ad.id),
                    ):
                        with pytest.raises(HTTPException) as error:
                            operation()
                        assert error.value.status_code == 404
                with EsopTenantUnitOfWork(session, tenant_a) as uow:
                    monkeypatch.setattr(
                        broadcast_routes,
                        "get_file_asset_directory",
                        lambda _: SimpleNamespace(
                            get_accessible_file=lambda **kwargs: None
                        ),
                    )
                    with pytest.raises(HTTPException) as error:
                        broadcast_routes.create_advertisement(
                            uow,
                            payload(
                                media=[{"kind": "image", "file_id": str(uuid.uuid4())}]
                            ),
                        )
                    assert error.value.status_code == 422
                    broadcast_routes.delete_advertisement(uow, ad.id)
                    assert broadcast_routes.list_advertisements(uow).total == 0
                with pytest.raises(TenantScopeError):
                    broadcast_routes.list_advertisements(
                        SimpleNamespace(session=session)
                    )
        finally:
            transaction.rollback()


def test_preview_only_reads_tenant_references_or_current_uploads(monkeypatch):
    from app.modules.esop.infrastructure.models import Advertisement
    from app.platform.public_api.files import FileDirectRead

    tenant_a, tenant_b, file_id, uploader = (uuid.uuid4() for _ in range(4))
    calls = []

    def uploaded(**kwargs):
        calls.append(kwargs)
        raise HTTPException(status_code=404, detail="Not uploaded by this user")

    monkeypatch.setattr(
        broadcast_routes,
        "get_file_asset_directory",
        lambda _: SimpleNamespace(
            direct_read_url=lambda **kwargs: FileDirectRead(
                url="https://example.invalid/preview", expires_at=get_datetime_utc()
            ),
            direct_uploaded_read_url=uploaded,
        ),
    )
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(
                bind=connection, join_transaction_mode="create_savepoint"
            ) as session:
                with EsopTenantUnitOfWork(session, tenant_a) as uow:
                    session.add(
                        Advertisement(
                            tenant_id=tenant_a,
                            title="预览验收",
                            layout="left",
                            playback="continuous",
                            starts_at=get_datetime_utc(),
                            media=[{"kind": "image", "file_id": str(file_id)}],
                        )
                    )
                    session.commit()
                    assert broadcast_routes.advertisement_file_access(
                        uow, SimpleNamespace(id=uploader), file_id
                    ).url.endswith("/preview")
                    assert calls == []
                with EsopTenantUnitOfWork(session, tenant_b) as uow:
                    with pytest.raises(HTTPException) as error:
                        broadcast_routes.advertisement_file_access(
                            uow, SimpleNamespace(id=uploader), file_id
                        )
                    assert error.value.status_code == 404
                    assert calls == [
                        {
                            "tenant_id": tenant_b,
                            "file_id": file_id,
                            "uploader_id": uploader,
                        }
                    ]
        finally:
            transaction.rollback()
