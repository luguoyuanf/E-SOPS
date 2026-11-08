"""Shared validation for the optional global login username."""

import re
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_core import PydanticCustomError


def normalize_username(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PydanticCustomError("username_format", "Username must be text")
    value = value.strip().lower()
    if not value:
        return None
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,63}", value):
        raise PydanticCustomError(
            "username_format",
            "Username must be 1-64 letters, digits, dots, underscores or hyphens and start with a letter or digit",
        )
    return value


LoginUsername = Annotated[str | None, BeforeValidator(normalize_username)]
