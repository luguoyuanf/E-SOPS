"""Code generation for user-maintained entity records."""

import secrets
from typing import Any

from pydantic import model_validator


def generate_entity_code(prefix: str) -> str:
    return f"{prefix}{secrets.randbelow(100_000_000):08d}"


class EntityCodeUpdateMixin:
    @model_validator(mode="before")
    @classmethod
    def keep_existing_code_if_blank(cls, value: Any) -> Any:
        if isinstance(value, dict) and "code" in value and (
            value["code"] is None or isinstance(value["code"], str) and not value["code"].strip()
        ):
            value = {key: item for key, item in value.items() if key != "code"}
        return value
