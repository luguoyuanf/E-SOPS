"""Public registration email challenges; no plaintext codes are persisted or returned."""

import hashlib
import hmac
import secrets

import httpx
from fastapi import HTTPException

from app.core.cache import redis_cache
from app.core.config import settings

CODE_TTL = 300
RESEND_SECONDS = 60
MAX_ATTEMPTS = 5
UNAVAILABLE = "Email verification is unavailable."
INVALID_CODE = "Email verification code is invalid or expired."


def email_verification_enabled() -> bool:
    return bool(
        settings.RESEND_API_KEY
        and settings.RESEND_API_KEY.get_secret_value().strip()
        and redis_cache.is_enabled()
    )


def verification_keys(email: str, purpose: str = "register") -> tuple[str, str, str]:
    identity = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    prefix = (
        ("registration-email", identity)
        if purpose == "register"
        else ("recovery-email", purpose, identity)
    )
    return tuple(
        redis_cache.build_key(*prefix, suffix)
        for suffix in ("code", "attempts", "cooldown")
    )


def hash_code(email: str, code: str, purpose: str = "register") -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(),
        (
            f"registration-email:{email.strip().lower()}:{code}"
            if purpose == "register"
            else f"recovery-email:{purpose}:{email.strip().lower()}:{code}"
        ).encode(),
        hashlib.sha256,
    ).hexdigest()


def send_registration_code(
    *, email: str, client_ip: str, purpose: str = "register", deliver: bool = True
) -> None:
    if not email_verification_enabled():
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    code_key, _, cooldown_key = verification_keys(email, purpose)
    # INCR reserves the cooldown atomically, including concurrent send requests.
    cooldown = redis_cache.incr(cooldown_key, ttl_seconds=RESEND_SECONDS)
    if cooldown is None:
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    if cooldown > 1:
        raise HTTPException(
            status_code=429, detail="Email verification code was sent recently."
        )
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()
    count = redis_cache.incr(
        redis_cache.build_key("registration-email", "send-ip", ip_hash),
        ttl_seconds=CODE_TTL,
    )
    if count is None:
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    if count > 10:
        raise HTTPException(
            status_code=429, detail="Too many email verification requests."
        )
    # Count the whole day's attempts so resends cannot exhaust the free plan unchecked.
    daily = redis_cache.incr(
        redis_cache.build_key("registration-email", "daily-sends"),
        ttl_seconds=86400,
    )
    if daily is None:
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    if daily > 90:
        raise HTTPException(
            status_code=429, detail="Too many email verification requests."
        )
    if not deliver:
        return
    code = f"{secrets.randbelow(1_000_000):06d}"
    if not redis_cache.set(
        code_key, hash_code(email, code, purpose), ttl_seconds=CODE_TTL
    ):
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    action = "注册" if purpose == "register" else "密码重置"
    english_action = "registration" if purpose == "register" else "password reset"
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY.get_secret_value()}"
            },
            json={
                "from": f"ESOPS <{settings.REGISTRATION_FROM_EMAIL}>",
                "to": [email],
                "subject": f"ESOPS {action}验证码 / Verification code",
                "text": f"您的 ESOPS {action}验证码为 {code}，5 分钟内有效。请勿向他人提供验证码。\nYour ESOPS {english_action} code is {code}. It expires in 5 minutes. If you did not request this, ignore this email.",
            },
            timeout=10,
        )
        response.raise_for_status()
        if not response.json().get("id"):
            raise ValueError("Missing delivery ID")
    except httpx.HTTPError, ValueError:
        redis_cache.delete(code_key)
        # Keep rate limits on failure. Provider responses may contain personal data.
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None


def validate_registration_code(
    *, email: str, code: str, purpose: str = "register"
) -> tuple[str, str]:
    code_key, attempts_key, _ = verification_keys(email, purpose)
    # Count every verification atomically before comparing, including concurrent guesses.
    attempts = redis_cache.incr(attempts_key, ttl_seconds=CODE_TTL)
    if attempts is None:
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    if attempts > MAX_ATTEMPTS:
        redis_cache.delete(code_key)
        raise HTTPException(status_code=400, detail=INVALID_CODE)
    expected = redis_cache.get(code_key)
    if expected and hmac.compare_digest(expected, hash_code(email, code, purpose)):
        return code_key, attempts_key
    if attempts == MAX_ATTEMPTS:
        redis_cache.delete(code_key)
    raise HTTPException(status_code=400, detail=INVALID_CODE)
