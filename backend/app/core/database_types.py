"""Dialect-neutral persistence types; Python timestamps remain aware UTC."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMTEXT
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def __init__(self, timezone: bool = True) -> None:
        super().__init__(timezone=timezone)

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamp must include a timezone")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "mysql" else value

    def process_result_value(self, value: datetime | None, _dialect: Dialect):
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )


class LargeString(TypeDecorator[str]):
    """Keep PostgreSQL VARCHAR bounds while avoiding MySQL's 64 KiB row limit."""

    impl = String
    cache_ok = True

    def __init__(self, length: int) -> None:
        self.length = length
        super().__init__(length=length)

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(MEDIUMTEXT())
        return dialect.type_descriptor(String(self.length))
