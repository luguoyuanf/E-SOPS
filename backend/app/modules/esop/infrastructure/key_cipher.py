"""Recoverable encryption for issued activation keys."""

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from app.core.config import settings


def _cipher() -> Fernet:
    configured = settings.ESOP_ACTIVATION_CIPHER_KEY
    if not configured:
        raise HTTPException(status_code=503, detail="Activation cipher key is not configured")
    try:
        return Fernet(configured.encode())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="Activation cipher key is invalid") from exc


def encrypt_key(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt_key(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        # Historical keys may use a retired cipher; keep the inventory readable.
        return None
