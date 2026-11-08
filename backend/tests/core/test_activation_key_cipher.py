"""Old ciphertext must not prevent listing the rest of the key inventory."""

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.core.config import settings
from app.modules.esop.infrastructure.key_cipher import decrypt_key, encrypt_key


def test_current_and_historical_ciphertext(monkeypatch):
    monkeypatch.setattr(settings, "ESOP_ACTIVATION_CIPHER_KEY", Fernet.generate_key().decode())
    assert decrypt_key(encrypt_key("12345678")) == "12345678"
    assert decrypt_key(None) is None
    assert decrypt_key(Fernet(Fernet.generate_key()).encrypt(b"12345678").decode()) is None


def test_missing_cipher_configuration_still_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "ESOP_ACTIVATION_CIPHER_KEY", "")
    with pytest.raises(HTTPException) as error:
        encrypt_key("12345678")
    assert error.value.status_code == 503
