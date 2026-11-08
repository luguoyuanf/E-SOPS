from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.core.export_datetime import export_datetime, export_timezone
from app.modules.erp.export_routes import _csv_value


def test_export_datetime_matches_page_timezone_and_keeps_date_only() -> None:
    instant = datetime(2026, 10, 29, 16, 1, 2, tzinfo=UTC)
    taipei = export_timezone(None)
    assert export_datetime(instant, taipei) == "2026-10-30 00:01:02"
    assert export_datetime(instant.replace(tzinfo=None), taipei) == "2026-10-30 00:01:02"
    assert export_datetime(instant, ZoneInfo("America/New_York")) == "2026-10-29 12:01:02"
    assert export_datetime(None, taipei) == ""
    assert _csv_value(instant, taipei) == "2026-10-30 00:01:02"
    assert _csv_value(date(2026, 10, 30), taipei) == "2026-10-30"
    assert _csv_value(None, taipei) == ""


def test_export_rejects_invalid_timezone() -> None:
    with pytest.raises(HTTPException) as exc:
        export_timezone("invalid/timezone")
    assert exc.value.status_code == 422
