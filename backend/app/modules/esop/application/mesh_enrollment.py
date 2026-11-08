"""Issue short-lived, terminal-only keys without storing enrollment secrets."""

import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from app.core.clock import get_datetime_utc
from app.modules.esop.public_api.mesh_dto import MeshEnrollmentPublic

_UNAVAILABLE = "Terminal mesh enrollment unavailable"
_INTERVAL_SECONDS = 60
_MAX_RECENT_DEVICES = 4096
_recent_devices: dict[tuple[uuid.UUID, uuid.UUID], float] = {}
_rate_lock = threading.Lock()


@dataclass(frozen=True)
class _Configuration:
    control_url: str
    headscale_url: str
    api_key: str = field(repr=False)
    user_id: str


def _configuration() -> _Configuration:
    control = os.environ.get("ESOPS_MESH_CONTROL_URL", "").strip().rstrip("/")
    headscale = os.environ.get("ESOPS_HEADSCALE_URL", "").strip().rstrip("/")
    api_key = os.environ.get("ESOPS_HEADSCALE_API_KEY", "").strip()
    user_id = os.environ.get("ESOPS_HEADSCALE_USER_ID", "").strip()
    try:
        public_url, api_url = urlsplit(control), urlsplit(headscale)
        ports_valid = all(url.port is None or 1 <= url.port <= 65535 for url in (public_url, api_url))
        valid = (
            ports_valid
            and public_url.scheme == "https"
            and bool(public_url.hostname)
            and public_url.path == ""
            and not public_url.query
            and not public_url.fragment
            and public_url.username is None
            and api_url.scheme in {"http", "https"}
            and bool(api_url.hostname)
            and api_url.path == ""
            and not api_url.query
            and not api_url.fragment
            and api_url.username is None
            and bool(api_key)
            and user_id.isascii()
            and user_id.isdigit()
            and int(user_id) > 0
        )
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    return _Configuration(control, headscale, api_key, user_id)


def _claim_window(tenant_id: uuid.UUID, terminal_id: uuid.UUID) -> None:
    # Bounded per-process metadata only; use a shared limiter if API worker count grows.
    now = time.monotonic()
    with _rate_lock:
        for key, at in list(_recent_devices.items()):
            if now - at >= _INTERVAL_SECONDS:
                del _recent_devices[key]
        key = (tenant_id, terminal_id)
        if key in _recent_devices:
            raise HTTPException(
                status_code=429, detail="Mesh enrollment requested too frequently",
                headers={"Retry-After": str(_INTERVAL_SECONDS)},
            )
        if len(_recent_devices) >= _MAX_RECENT_DEVICES:
            raise HTTPException(status_code=503, detail=_UNAVAILABLE)
        _recent_devices[key] = now


def issue_enrollment(tenant_id: uuid.UUID, terminal_id: uuid.UUID) -> MeshEnrollmentPublic:
    config = _configuration()
    _claim_window(tenant_id, terminal_id)
    now = get_datetime_utc()
    expiration = now + timedelta(minutes=10)
    try:
        with httpx.Client(timeout=httpx.Timeout(5, connect=2), trust_env=False) as client:
            response = client.post(
                f"{config.headscale_url}/api/v1/preauthkey",
                headers={"Authorization": f"Bearer {config.api_key}"},
                json={
                    "user": config.user_id,
                    "reusable": False,
                    "ephemeral": False,
                    "expiration": expiration.isoformat().replace("+00:00", "Z"),
                    "aclTags": ["tag:terminal"],
                },
            )
            response.raise_for_status()
            result = response.json()["preAuthKey"]
        key = result["key"]
        expires = datetime.fromisoformat(result["expiration"].replace("Z", "+00:00"))
        if (
            not isinstance(key, str)
            or re.fullmatch(r"hskey-auth-[A-Za-z0-9_-]+", key) is None
            or len(key) > 512
            or result.get("reusable", False) is not False
            or result.get("ephemeral", False) is not False
            or result.get("aclTags") != ["tag:terminal"]
            or expires.tzinfo is None
            or not now < expires <= expiration + timedelta(seconds=5)
        ):
            raise ValueError("Invalid enrollment response")
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        # Never expose the upstream response, administrator key, or issued auth key.
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    return MeshEnrollmentPublic(
        controlUrl=config.control_url, authKey=key, expiresAt=expires.astimezone(UTC),
    )
