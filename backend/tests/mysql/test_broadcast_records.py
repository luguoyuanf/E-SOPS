"""Publication record behavior against the fixed MySQL DB, all fixtures rolled back."""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.core.database import engine
from app.modules.esop.broadcast_routes import (
    create_advertisement,
    create_broadcast_record,
    delete_broadcast_record,
    list_advertisements,
    list_broadcast_records,
    list_broadcasts,
    save_broadcast,
    update_broadcast_record,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.broadcast_dto import AdvertisementInput, BroadcastInput


def body(content, active=True):
    return BroadcastInput(
        content=content,
        font_size=24,
        background_color="#12304A",
        font_color="#FFFFFF",
        is_active=active,
    )


def test_records_replace_active_pause_resume_edit_delete_and_isolate():
    assert settings.MYSQL_DB == "esop_fva_test_20261024"
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
                    first = create_broadcast_record(uow, "top", body("甲安全广播"))
                    second = create_broadcast_record(uow, "top", body("乙生产广播"))
                    create_broadcast_record(uow, "bottom", body("底部提示"))
                    assert list_broadcast_records(uow, "top").total == 2
                    assert (
                        list_broadcast_records(uow, "top", status="active").items[0].id
                        == second.id
                    )
                    assert (
                        list_broadcast_records(uow, "top", status="paused").items[0].id
                        == first.id
                    )
                    assert list_broadcast_records(uow, "top", keyword="安全").total == 1
                    assert (
                        len(list_broadcast_records(uow, "top", page_size=1).items) == 1
                    )
                    assert (
                        list_broadcast_records(
                            uow,
                            "top",
                            created_from=get_datetime_utc() + timedelta(days=1),
                        ).total
                        == 0
                    )
                    update_broadcast_record(uow, "top", first.id, body("甲已修改"))
                    active = list_broadcast_records(uow, "top", status="active")
                    assert active.total == 1 and active.items[0].content == "甲已修改"
                    slots = {r.position: r for r in list_broadcasts(uow).items}
                    assert (
                        slots["top"].content == "甲已修改" and slots["bottom"].is_active
                    )
                    update_broadcast_record(
                        uow, "top", first.id, body("甲已修改", False)
                    )
                    assert (
                        list_broadcast_records(uow, "top", status="active").total == 0
                    )
                    assert not next(
                        r for r in list_broadcasts(uow).items if r.position == "top"
                    ).is_active
                    update_broadcast_record(uow, "top", second.id, body("乙生产广播"))
                    delete_broadcast_record(uow, "top", second.id)
                    assert list_broadcast_records(uow, "top").total == 1
                    assert not next(
                        r for r in list_broadcasts(uow).items if r.position == "top"
                    ).is_active
                    with pytest.raises(HTTPException) as error:
                        update_broadcast_record(uow, "bottom", first.id, body("越位置"))
                    assert error.value.status_code == 404
                with EsopTenantUnitOfWork(session, tenant_b) as uow:
                    assert list_broadcast_records(uow, "top").total == 0
                    for action in (
                        lambda: update_broadcast_record(
                            uow, "top", first.id, body("越租户")
                        ),
                        lambda: delete_broadcast_record(uow, "top", first.id),
                    ):
                        with pytest.raises(HTTPException) as error:
                            action()
                        assert error.value.status_code == 404
        finally:
            transaction.rollback()


def test_legacy_slot_api_remains_stable_and_pauses_active_record():
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with (
                Session(
                    bind=connection, join_transaction_mode="create_savepoint"
                ) as session,
                EsopTenantUnitOfWork(session, uuid.uuid4()) as uow,
            ):
                first = save_broadcast(uow, "top", body("原接口"))
                changed = save_broadcast(uow, "top", body("已暂停", False))
                assert first.id == changed.id and not changed.is_active
                assert list_broadcast_records(uow, "top").total == 1
                assert not list_broadcast_records(uow, "top").items[0].is_active
        finally:
            transaction.rollback()


def test_advertisement_record_keyword_status_pagination_and_time_filters(monkeypatch):
    monkeypatch.setattr(
        "app.modules.esop.broadcast_routes.get_file_asset_directory",
        lambda _: SimpleNamespace(),
    )
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with (
                Session(
                    bind=connection, join_transaction_mode="create_savepoint"
                ) as session,
                EsopTenantUnitOfWork(session, uuid.uuid4()) as uow,
            ):
                for title, active, future in [
                    ("安全广告", True, False),
                    ("车间广告", False, False),
                    ("未来广告", True, True),
                ]:
                    create_advertisement(
                        uow,
                        AdvertisementInput(
                            title=title,
                            is_active=active,
                            starts_at=get_datetime_utc() + timedelta(days=1)
                            if future
                            else None,
                            media=[{"kind": "text", "content": "验收"}],
                        ),
                    )
                assert list_advertisements(uow, keyword="安全").total == 1
                assert list_advertisements(uow, status="active").total == 1
                assert list_advertisements(uow, status="paused").total == 1
                assert list_advertisements(uow, status="scheduled").total == 1
                result = list_advertisements(uow, page=2, page_size=1)
                assert result.total == 3 and len(result.items) == 1
                assert (
                    list_advertisements(
                        uow, created_to=get_datetime_utc() - timedelta(days=1)
                    ).total
                    == 0
                )
        finally:
            transaction.rollback()
