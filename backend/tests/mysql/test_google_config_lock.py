"""Verify Google configuration updates and callbacks share a real MySQL lock."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from sqlmodel import Session

from app.core.config import settings
from app.core.database import engine
from app.platform.infra.google_oauth_config import lock_google_config_anchor


def test_google_config_anchor_serializes_concurrent_transactions():
    assert settings.DATABASE_TYPE == "mysql" and settings.MYSQL_DB == "esop_fva_test_20261024"
    started = Event()
    acquired = Event()

    def contender():
        with Session(engine) as second:
            started.set()
            lock_google_config_anchor(second)
            acquired.set()
            second.rollback()

    with Session(engine) as first, ThreadPoolExecutor(max_workers=1) as executor:
        lock_google_config_anchor(first)
        future = executor.submit(contender)
        try:
            assert started.wait(5)
            assert not acquired.wait(0.5)
        finally:
            first.rollback()
        future.result(timeout=10)
        assert acquired.is_set()
