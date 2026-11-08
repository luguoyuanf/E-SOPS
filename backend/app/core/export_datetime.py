"""Render exported timestamps in the same timezone and format as Web tables."""

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Header, HTTPException

ExportTimezoneHeader = Annotated[str | None, Header(alias="X-Export-Timezone")]


def export_timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Taipei")
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(status_code=422, detail="导出时区无效") from exc


def export_datetime(value: datetime | None, timezone: ZoneInfo) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
