import base64
import hashlib
import hmac
import json
import random
import re
import secrets
import time
import uuid
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs, urlencode, urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, select

from app import crud
from app.api.deps import (
    CurrentTenant,
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
    has_backoffice_menu,
)
from app.core import security
from app.core.cache import CacheNamespace, redis_cache
from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.core.enterprise_oidc import (
    OIDC_PROVIDER,
    build_pkce_challenge,
    exchange_authorization_code,
    external_identity_is_active,
    generate_oidc_value,
    get_oidc_provider_metadata,
    hash_oidc_value,
    role_codes_from_claims,
    validate_identity_token,
)
from app.core.mfa import consume_recovery_code, decrypt_totp_secret, verify_totp_code
from app.core.tenancy import DEFAULT_TENANT_CODE, get_active_tenant_membership
from app.models import (
    LoginCaptchaChallenge,
    Message,
    NewPassword,
    SmsTemplate,
    Token,
)
from app.platform.bootstrap_rbac import provision_tenant_roles
from app.platform.core.authorization_models import Role, UserRole
from app.platform.core.configuration_models import SystemSetting
from app.platform.core.identity_models import (
    EnterpriseOidcAuthorizationState,
    EnterpriseOidcIdentity,
    EnterpriseOidcLoginTicket,
    EnterpriseOidcStatus,
    EnterpriseOidcTicketExchange,
    PasswordRecoveryProof,
    PasswordRecoveryReset,
    PasswordRecoverySend,
    PasswordRecoveryVerify,
    QrCodeLoginChallenge,
    QrCodeLoginConfirmRequest,
    QrCodeLoginConfirmResult,
    QrCodeLoginCreate,
    QrCodeLoginExchangeRequest,
    QrCodeLoginStatus,
    QrCodeLoginStatusRequest,
    RegistrationEmailCodeRequest,
    RegistrationEmailCodeSent,
    RegistrationStatus,
    RegistrationTenantCodeAvailability,
    SmsCodeRequest,
    SmsCodeSent,
    SmsLoginRequest,
    User,
    UserPublic,
    UserSession,
    UserUpdate,
)
from app.platform.core.tenancy_models import (
    Tenant,
    TenantInitializationTemplate,
    TenantMembership,
    TenantPlan,
    TenantRegistrationRequest,
)
from app.platform.infra.audit import create_login_log, get_client_ip, get_user_agent
from app.platform.infra.password_recovery import (
    complete_recovery,
    send_recovery_code,
    verify_recovery_code,
)
from app.platform.infra.registration_email import (
    email_verification_enabled,
    send_registration_code,
    validate_registration_code,
)
from app.platform.infra.sms_router import create_sms_log, get_template_channel
from app.platform.tenant_uow import activate_platform_tenant_scope
from app.utils import (
    generate_password_reset_token,
    generate_reset_password_email,
    send_email,
    verify_password_reset_token,
)

router = APIRouter(tags=["login"])

LOGIN_RATE_LIMIT_MESSAGE = "Too many failed login attempts. Please try again later."
LOGIN_CAPTCHA_REQUIRED_MESSAGE = "Captcha verification required."
LOGIN_CAPTCHA_INVALID_MESSAGE = "Captcha is invalid or expired."
LOGIN_SLIDER_CAPTCHA_INVALID_MESSAGE = (
    "Slider captcha verification is invalid or expired."
)
LOGIN_MFA_REQUIRED_MESSAGE = "MFA verification required."
LOGIN_MFA_INVALID_MESSAGE = "MFA verification code is invalid."
LOGIN_MFA_SETUP_INVALID_MESSAGE = "MFA setup is invalid. Please restart MFA setup."
SMS_CODE_INVALID_MESSAGE = "SMS verification code is invalid or expired."
SMS_VERIFICATION_UNAVAILABLE_MESSAGE = "SMS verification is unavailable."
SMS_LOGIN_INVALID_MESSAGE = "Incorrect mobile or verification code"
QR_LOGIN_UNAVAILABLE_MESSAGE = "QR code login is unavailable."
QR_LOGIN_EXPIRED_MESSAGE = "QR code login challenge is invalid or expired."
QR_LOGIN_INVALID_MESSAGE = "QR code login credential is invalid."
QR_LOGIN_PENDING_MESSAGE = "QR code login has not been confirmed."
QR_LOGIN_ALREADY_CONFIRMED_MESSAGE = "QR code login has already been confirmed."
QR_LOGIN_TENANT_MISMATCH_MESSAGE = (
    "QR code login tenant does not match the current tenant."
)
MOBILE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
TENANT_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,31}$")


def normalize_login_identifier(username: str) -> str:
    return username.strip().lower()


def normalize_mobile(mobile: str) -> str:
    normalized = re.sub(r"[\s()-]", "", mobile)
    if normalized.startswith("+86"):
        normalized = normalized[3:]
    if MOBILE_PATTERN.fullmatch(normalized):
        return normalized
    if not re.fullmatch(r"\+[1-9]\d{7,14}", normalized):
        raise HTTPException(status_code=400, detail="Invalid mobile number")
    return normalized


def get_login_tenant(*, session: SessionDep, tenant_code: str) -> Tenant:
    tenant = session.exec(
        select(Tenant).where(
            Tenant.code == tenant_code.strip().lower(),
            Tenant.is_active,
        )
    ).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def get_sms_verification_keys(
    *, tenant_id: uuid.UUID, mobile: str, scene: str
) -> tuple[str, str, str]:
    prefix = (CacheNamespace.SMS_VERIFICATION, tenant_id, scene, mobile)
    return (
        redis_cache.build_key(*prefix, "code"),
        redis_cache.build_key(*prefix, "attempts"),
        redis_cache.build_key(*prefix, "cooldown"),
    )


def hash_sms_code(*, tenant_id: uuid.UUID, mobile: str, scene: str, code: str) -> str:
    payload = f"{tenant_id}:{scene}:{mobile}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()


def validate_sms_verification_code(
    *,
    tenant_id: uuid.UUID,
    mobile: str,
    scene: str,
    code: str,
) -> tuple[str, str]:
    code_key, attempts_key, _ = get_sms_verification_keys(
        tenant_id=tenant_id,
        mobile=mobile,
        scene=scene,
    )
    expected_hash = redis_cache.get(code_key)
    submitted_hash = hash_sms_code(
        tenant_id=tenant_id,
        mobile=mobile,
        scene=scene,
        code=code,
    )
    if expected_hash is not None and hmac.compare_digest(
        expected_hash,
        submitted_hash,
    ):
        return code_key, attempts_key

    attempts = redis_cache.incr(
        attempts_key,
        ttl_seconds=settings.SMS_CODE_TTL_SECONDS,
    )
    if attempts is None:
        raise HTTPException(
            status_code=503,
            detail=SMS_VERIFICATION_UNAVAILABLE_MESSAGE,
        )
    if attempts >= settings.SMS_CODE_MAX_ATTEMPTS:
        redis_cache.delete(code_key, attempts_key)
    raise HTTPException(status_code=400, detail=SMS_CODE_INVALID_MESSAGE)


def is_public_registration_enabled(*, session: SessionDep) -> bool:
    platform_tenant = session.exec(
        select(Tenant).where(Tenant.code == DEFAULT_TENANT_CODE)
    ).first()
    if platform_tenant is None:
        return False
    activate_platform_tenant_scope(session, platform_tenant.id)
    setting = session.exec(
        select(SystemSetting).where(
            SystemSetting.tenant_id == platform_tenant.id,
            SystemSetting.key == "auth.allow_register",
            SystemSetting.is_public,
        )
    ).first()
    return setting is not None and setting.value.strip().lower() == "true"


class LoginFormData(BaseModel):
    username: str
    password: str
    tenant_code: str | None = None
    captcha_code: str | None = None
    captcha_id: str | None = None
    captcha_verification: str | None = None
    mfa_code: str | None = None


class TenantRegistrationToken(Token):
    free_activation_key: str | None = None


def get_login_form_data(
    username: Annotated[str, Form(...)],
    password: Annotated[str, Form(...)],
    tenant_code: Annotated[str | None, Form()] = None,
    captcha_code: Annotated[str | None, Form()] = None,
    captcha_id: Annotated[str | None, Form()] = None,
    captcha_verification: Annotated[str | None, Form()] = None,
    mfa_code: Annotated[str | None, Form()] = None,
) -> LoginFormData:
    return LoginFormData(
        username=username,
        password=password,
        tenant_code=tenant_code,
        captcha_code=captcha_code,
        captcha_id=captcha_id,
        captcha_verification=captcha_verification,
        mfa_code=mfa_code,
    )


def get_login_rate_limit_keys(request: Request, username: str) -> tuple[str, str]:
    client_ip = get_client_ip(request) or "unknown"
    identifier = normalize_login_identifier(username)
    attempt_key = redis_cache.build_key(
        CacheNamespace.LOGIN_RATE_LIMIT,
        "attempts",
        client_ip,
        identifier,
    )
    block_key = redis_cache.build_key(
        CacheNamespace.LOGIN_RATE_LIMIT,
        "blocked",
        client_ip,
        identifier,
    )
    return attempt_key, block_key


def get_login_captcha_key(captcha_id: str) -> str:
    return redis_cache.build_key(CacheNamespace.LOGIN_CAPTCHA, captcha_id)


def get_login_captcha_payload(captcha_id: str) -> dict[str, Any] | None:
    return redis_cache.get_json(get_login_captcha_key(captcha_id))


def requires_login_captcha(request: Request, username: str) -> bool:
    if not settings.LOGIN_CAPTCHA_ENABLED:
        return False
    attempt_key, _ = get_login_rate_limit_keys(request, username)
    attempts_raw = redis_cache.get(attempt_key)
    if attempts_raw is None:
        return False
    try:
        attempts = int(attempts_raw)
    except ValueError:
        return False
    return attempts >= settings.LOGIN_CAPTCHA_THRESHOLD


def create_login_captcha(
    request: Request, username: str
) -> LoginCaptchaChallenge | None:
    if not settings.LOGIN_CAPTCHA_ENABLED:
        return None
    client_ip = get_client_ip(request) or "unknown"
    identifier = normalize_login_identifier(username)
    captcha_id = str(uuid.uuid4())
    left = random.randint(1, 9)
    right = random.randint(1, 9)
    answer = str(left + right)
    redis_cache.set_json(
        get_login_captcha_key(captcha_id),
        {
            "answer": answer,
            "identifier": identifier,
            "ip": client_ip,
        },
        ttl_seconds=settings.LOGIN_CAPTCHA_TTL_SECONDS,
    )
    return LoginCaptchaChallenge(
        captcha_id=captcha_id,
        challenge_text=f"{left} + {right} = ?",
        expires_in=settings.LOGIN_CAPTCHA_TTL_SECONDS,
    )


def validate_login_captcha(
    request: Request,
    username: str,
    *,
    captcha_id: str | None,
    captcha_code: str | None,
) -> bool:
    if not captcha_id or not captcha_code:
        return False
    payload = get_login_captcha_payload(captcha_id)
    if payload is None:
        return False
    redis_cache.delete(get_login_captcha_key(captcha_id))
    identifier = normalize_login_identifier(username)
    client_ip = get_client_ip(request) or "unknown"
    expected_answer = str(payload.get("answer", "")).strip()
    expected_identifier = str(payload.get("identifier", "")).strip().lower()
    expected_ip = str(payload.get("ip", "")).strip()
    return (
        captcha_code.strip() == expected_answer
        and identifier == expected_identifier
        and client_ip == expected_ip
    )


SLIDER_IMAGE_WIDTH = 400
SLIDER_IMAGE_HEIGHT = 200
SLIDER_BAR_WIDTH = 310
SLIDER_PIECE_SIZE = 52
SLIDER_PIECE_Y = 72
_slider_memory: dict[str, dict[str, Any]] = {}


def get_slider_captcha_key(token: str) -> str:
    return redis_cache.build_key(CacheNamespace.LOGIN_SLIDER_CAPTCHA, token)


def get_slider_verification_key(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return redis_cache.build_key(
        CacheNamespace.LOGIN_SLIDER_CAPTCHA, "verification", digest
    )


def _slider_memory_cleanup() -> None:
    now = time.time()
    for token, payload in list(_slider_memory.items()):
        if float(payload.get("expires_at", 0)) <= now:
            _slider_memory.pop(token, None)


def _slider_get(token: str) -> dict[str, Any] | None:
    payload = redis_cache.get_json(get_slider_captcha_key(token))
    if isinstance(payload, dict):
        return payload
    _slider_memory_cleanup()
    payload = _slider_memory.get(token)
    return payload if isinstance(payload, dict) else None


def _slider_set(token: str, payload: dict[str, Any]) -> bool:
    ttl = settings.LOGIN_SLIDER_CAPTCHA_TTL_SECONDS
    stored = redis_cache.set_json(
        get_slider_captcha_key(token), payload, ttl_seconds=ttl
    )
    if stored:
        return True
    _slider_memory[token] = {**payload, "expires_at": time.time() + ttl}
    return True


def _slider_delete(token: str) -> None:
    redis_cache.delete(get_slider_captcha_key(token))
    _slider_memory.pop(token, None)


def _slider_store_verification(value: str, token: str) -> None:
    key = get_slider_verification_key(value)
    ttl = settings.LOGIN_SLIDER_CAPTCHA_TTL_SECONDS
    if not redis_cache.set_json(key, {"token": token}, ttl_seconds=ttl):
        _slider_memory[key] = {"token": token, "expires_at": time.time() + ttl}


def _slider_token_for_verification(value: str) -> str | None:
    payload = redis_cache.get_json(get_slider_verification_key(value))
    if isinstance(payload, dict) and isinstance(payload.get("token"), str):
        return payload["token"]
    _slider_memory_cleanup()
    payload = _slider_memory.get(get_slider_verification_key(value))
    token = payload.get("token") if isinstance(payload, dict) else None
    return token if isinstance(token, str) else None


def _aes_key(secret_key: str) -> bytes:
    raw = secret_key.encode("utf-8")
    if len(raw) not in {16, 24, 32}:
        raise ValueError("AES key must be 16, 24, or 32 bytes")
    return raw


def _aes_encrypt(value: str, secret_key: str) -> str:
    raw = value.encode("utf-8")
    padding = 16 - len(raw) % 16
    padded = raw + bytes([padding]) * padding
    encryptor = Cipher(algorithms.AES(_aes_key(secret_key)), modes.ECB()).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("ascii")


def _aes_decrypt(value: str, secret_key: str) -> str | None:
    try:
        decryptor = Cipher(
            algorithms.AES(_aes_key(secret_key)), modes.ECB()
        ).decryptor()
        decrypted = decryptor.update(base64.b64decode(value)) + decryptor.finalize()
        padding = decrypted[-1]
        if (
            padding < 1
            or padding > 16
            or decrypted[-padding:] != bytes([padding]) * padding
        ):
            return None
        return decrypted[:-padding].decode("utf-8")
    except ValueError, UnicodeDecodeError, base64.binascii.Error:
        return None


def _image_base64(image: Image.Image) -> str:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def _piece_mask() -> Image.Image:
    mask = Image.new("L", (SLIDER_PIECE_SIZE, SLIDER_PIECE_SIZE), 0)
    draw = ImageDraw.Draw(mask)
    margin = 4
    draw.rounded_rectangle(
        (margin, margin, SLIDER_PIECE_SIZE - margin, SLIDER_PIECE_SIZE - margin),
        radius=9,
        fill=255,
    )
    draw.ellipse((SLIDER_PIECE_SIZE - 3, 15, SLIDER_PIECE_SIZE + 13, 33), fill=255)
    return mask


def _build_slider_images(target_x: int) -> tuple[str, str]:
    esops_theme = settings.APP_EDITION == "esop"
    image = Image.new("RGB", (SLIDER_IMAGE_WIDTH, SLIDER_IMAGE_HEIGHT))
    pixels = image.load()
    for y in range(SLIDER_IMAGE_HEIGHT):
        for x in range(SLIDER_IMAGE_WIDTH):
            pixels[x, y] = (
                (
                    241 - int(13 * x / SLIDER_IMAGE_WIDTH),
                    247 + int(5 * y / SLIDER_IMAGE_HEIGHT),
                    239 + int(5 * x / SLIDER_IMAGE_WIDTH),
                )
                if esops_theme
                else (
                    20 + int(45 * x / SLIDER_IMAGE_WIDTH),
                    100 + int(65 * y / SLIDER_IMAGE_HEIGHT),
                    180 + int(45 * (1 - x / SLIDER_IMAGE_WIDTH)),
                )
            )
    draw = ImageDraw.Draw(image, "RGBA")
    for index in range(12):
        x = (index * 73 + 29) % SLIDER_IMAGE_WIDTH
        y = (index * 47 + 17) % SLIDER_IMAGE_HEIGHT
        radius = 14 + (index % 4) * 7
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=(5, 150, 105, 12) if esops_theme else (255, 255, 255, 18),
            outline=(5, 150, 105, 65) if esops_theme else (255, 255, 255, 85),
            width=2,
        )
    if esops_theme:
        with Image.open(Path(__file__).resolve().parents[2] / "assets/esops-logo.png") as source:
            brand = source.convert("RGBA")
            brand = brand.crop(brand.getchannel("A").getbbox())
            brand.thumbnail((190, 54), Image.Resampling.LANCZOS)
            image.paste(brand, (22, 12), brand)
        draw.line((22, 166, 378, 166), fill=(5, 150, 105, 60), width=2)
        for x in range(30, 380, 48):
            draw.line((x, 154, x, 178), fill=(5, 150, 105, 45), width=2)
    mask = _piece_mask()
    piece = image.crop(
        (
            target_x,
            SLIDER_PIECE_Y,
            target_x + SLIDER_PIECE_SIZE,
            SLIDER_PIECE_Y + SLIDER_PIECE_SIZE,
        )
    ).convert("RGBA")
    piece.putalpha(mask)
    gap = Image.new("RGBA", image.size, (0, 0, 0, 0))
    gap_mask = Image.new("L", image.size, 0)
    gap_mask.paste(mask, (target_x, SLIDER_PIECE_Y))
    gap_draw = ImageDraw.Draw(gap)
    gap_draw.bitmap((0, 0), gap_mask, fill=(4, 120, 87, 120) if esops_theme else (22, 35, 63, 110))
    image = Image.alpha_composite(image.convert("RGBA"), gap)
    gap_outline = ImageDraw.Draw(image)
    gap_outline.rounded_rectangle(
        (
            target_x + 4,
            SLIDER_PIECE_Y + 4,
            target_x + SLIDER_PIECE_SIZE - 4,
            SLIDER_PIECE_Y + SLIDER_PIECE_SIZE - 4,
        ),
        radius=9,
        outline=(255, 255, 255, 210),
        width=2,
    )
    return _image_base64(image), _image_base64(piece)


def _slider_error(message: str) -> dict[str, Any]:
    return {"repCode": "6110", "repMsg": message, "repData": None}


def validate_slider_captcha_verification(value: str | None) -> bool:
    if not value:
        return False
    token = _slider_token_for_verification(value)
    if not token:
        return False
    payload = _slider_get(token)
    if not payload or payload.get("verified") is not True:
        return False
    valid = hmac.compare_digest(str(payload.get("verification", "")), value)
    _slider_delete(token)
    redis_cache.delete(get_slider_verification_key(value))
    _slider_memory.pop(get_slider_verification_key(value), None)
    return valid


def is_login_rate_limited(request: Request, username: str) -> bool:
    if not settings.LOGIN_RATE_LIMIT_ENABLED:
        return False
    _, block_key = get_login_rate_limit_keys(request, username)
    return redis_cache.get(block_key) is not None


def record_failed_login_attempt(request: Request, username: str) -> bool:
    if not settings.LOGIN_RATE_LIMIT_ENABLED:
        return False
    attempt_key, block_key = get_login_rate_limit_keys(request, username)
    attempts = redis_cache.incr(
        attempt_key,
        ttl_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )
    if attempts is None:
        return False
    if attempts >= settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
        redis_cache.set(
            block_key,
            "1",
            ttl_seconds=settings.LOGIN_RATE_LIMIT_BLOCK_SECONDS,
        )
        return True
    return False


def clear_failed_login_attempts(request: Request, username: str) -> None:
    if not settings.LOGIN_RATE_LIMIT_ENABLED:
        return
    attempt_key, block_key = get_login_rate_limit_keys(request, username)
    redis_cache.delete(attempt_key, block_key)


def create_login_token(
    *,
    session: SessionDep,
    request: Request,
    user: User,
    tenant_id: uuid.UUID | None = None,
    allow_tenant_switch: bool = False,
    client_kind: Literal["backoffice", "terminal"] = "backoffice",
) -> Token:
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_id = str(uuid.uuid4())
    tenant_membership = get_active_tenant_membership(
        session=session,
        user_id=user.id,
        tenant_id=tenant_id,
    )
    if tenant_membership is None:
        raise HTTPException(status_code=403, detail="User has no active tenant")
    _, tenant = tenant_membership
    activate_platform_tenant_scope(session, tenant.id, privileged=allow_tenant_switch)
    if client_kind == "backoffice" and not has_backoffice_menu(session, user, tenant.id):
        create_login_log(
            session=session, request=request, email=user.email or user.username,
            status="fail", user=user, tenant_id=tenant.id,
            failure_reason="Back-office menu permission required",
        )
        raise HTTPException(status_code=403, detail="Back-office menu permission required")
    session.add(
        UserSession(
            user_id=user.id,
            tenant_id=tenant.id,
            token_jti=token_id,
            ip=get_client_ip(request),
            user_agent=get_user_agent(request),
            expires_at=get_datetime_utc() + access_token_expires,
        )
    )
    session.commit()
    return Token(
        access_token=security.create_access_token(
            user.id,
            expires_delta=access_token_expires,
            token_id=token_id,
            tenant_id=tenant.id,
            client_kind=client_kind,
        ),
        tenant_id=tenant.id,
    )


def get_qr_login_key(challenge_id: uuid.UUID) -> str:
    return redis_cache.build_key(CacheNamespace.QR_CODE_LOGIN, challenge_id)


def hash_qr_login_token(*, challenge_id: uuid.UUID, purpose: str, token: str) -> str:
    payload = f"{challenge_id}:{purpose}:{token}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()


def get_qr_login_payload(challenge_id: uuid.UUID) -> dict[str, Any]:
    payload = redis_cache.get_json(get_qr_login_key(challenge_id))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=410, detail=QR_LOGIN_EXPIRED_MESSAGE)
    return payload


def qr_login_token_matches(
    *, challenge_id: uuid.UUID, purpose: str, token: str, expected_hash: object
) -> bool:
    if not isinstance(expected_hash, str):
        return False
    actual_hash = hash_qr_login_token(
        challenge_id=challenge_id,
        purpose=purpose,
        token=token,
    )
    return hmac.compare_digest(actual_hash, expected_hash)


@router.post("/login/qr-code", response_model=QrCodeLoginChallenge)
def create_qr_code_login(
    *, session: SessionDep, body: QrCodeLoginCreate
) -> QrCodeLoginChallenge:
    if not redis_cache.is_enabled():
        raise HTTPException(status_code=503, detail=QR_LOGIN_UNAVAILABLE_MESSAGE)
    tenant = get_login_tenant(session=session, tenant_code=body.tenant_code)
    challenge_id = uuid.uuid4()
    scan_token = secrets.token_urlsafe(32)
    poll_token = secrets.token_urlsafe(32)
    stored = redis_cache.set_json(
        get_qr_login_key(challenge_id),
        {
            "status": "pending",
            "tenant_id": str(tenant.id),
            "scan_token_hash": hash_qr_login_token(
                challenge_id=challenge_id,
                purpose="scan",
                token=scan_token,
            ),
            "poll_token_hash": hash_qr_login_token(
                challenge_id=challenge_id,
                purpose="poll",
                token=poll_token,
            ),
        },
        ttl_seconds=settings.QR_CODE_LOGIN_TTL_SECONDS,
    )
    if not stored:
        raise HTTPException(status_code=503, detail=QR_LOGIN_UNAVAILABLE_MESSAGE)
    return QrCodeLoginChallenge(
        challenge_id=challenge_id,
        scan_token=scan_token,
        poll_token=poll_token,
        expires_in=settings.QR_CODE_LOGIN_TTL_SECONDS,
    )


@router.post("/login/qr-code/status", response_model=QrCodeLoginStatus)
def read_qr_code_login_status(body: QrCodeLoginStatusRequest) -> QrCodeLoginStatus:
    payload = get_qr_login_payload(body.challenge_id)
    if not qr_login_token_matches(
        challenge_id=body.challenge_id,
        purpose="poll",
        token=body.poll_token,
        expected_hash=payload.get("poll_token_hash"),
    ):
        raise HTTPException(status_code=400, detail=QR_LOGIN_INVALID_MESSAGE)
    status_value = payload.get("status")
    if status_value not in {"pending", "confirmed"}:
        raise HTTPException(status_code=410, detail=QR_LOGIN_EXPIRED_MESSAGE)
    return QrCodeLoginStatus(
        status=status_value,
        expires_in=settings.QR_CODE_LOGIN_TTL_SECONDS,
    )


@router.post("/login/qr-code/confirm", response_model=QrCodeLoginConfirmResult)
def confirm_qr_code_login(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    tenant_context: CurrentTenant,
    body: QrCodeLoginConfirmRequest,
) -> QrCodeLoginConfirmResult:
    payload = get_qr_login_payload(body.challenge_id)
    if not qr_login_token_matches(
        challenge_id=body.challenge_id,
        purpose="scan",
        token=body.scan_token,
        expected_hash=payload.get("scan_token_hash"),
    ):
        raise HTTPException(status_code=400, detail=QR_LOGIN_INVALID_MESSAGE)
    if payload.get("tenant_id") != str(tenant_context.tenant_id):
        raise HTTPException(status_code=403, detail=QR_LOGIN_TENANT_MISMATCH_MESSAGE)
    if payload.get("status") != "pending":
        raise HTTPException(status_code=409, detail=QR_LOGIN_ALREADY_CONFIRMED_MESSAGE)

    confirmed_payload = {
        **payload,
        "status": "confirmed",
        "user_id": str(current_user.id),
    }
    updated = redis_cache.compare_and_set_json(
        get_qr_login_key(body.challenge_id),
        expected={
            "status": "pending",
            "scan_token_hash": payload["scan_token_hash"],
        },
        value=confirmed_payload,
    )
    if not updated:
        raise HTTPException(status_code=409, detail=QR_LOGIN_ALREADY_CONFIRMED_MESSAGE)
    tenant = session.get(Tenant, tenant_context.tenant_id)
    return QrCodeLoginConfirmResult(
        message="QR code login confirmed.",
        tenant_name=tenant.name if tenant else tenant_context.tenant_code,
        user_name=current_user.full_name
        or current_user.username
        or current_user.email
        or str(current_user.id),
    )


@router.post("/login/qr-code/exchange", response_model=Token)
def exchange_qr_code_login(
    *, request: Request, session: SessionDep, body: QrCodeLoginExchangeRequest
) -> Token:
    poll_token_hash = hash_qr_login_token(
        challenge_id=body.challenge_id,
        purpose="poll",
        token=body.poll_token,
    )
    key = get_qr_login_key(body.challenge_id)
    payload = redis_cache.consume_json_if(
        key,
        expected={
            "status": "confirmed",
            "poll_token_hash": poll_token_hash,
        },
    )
    if not isinstance(payload, dict):
        current = redis_cache.get_json(key)
        if not isinstance(current, dict):
            raise HTTPException(status_code=410, detail=QR_LOGIN_EXPIRED_MESSAGE)
        if not hmac.compare_digest(
            str(current.get("poll_token_hash", "")), poll_token_hash
        ):
            raise HTTPException(status_code=400, detail=QR_LOGIN_INVALID_MESSAGE)
        raise HTTPException(status_code=409, detail=QR_LOGIN_PENDING_MESSAGE)

    try:
        user_id = uuid.UUID(str(payload["user_id"]))
        tenant_id = uuid.UUID(str(payload["tenant_id"]))
    except KeyError, ValueError:
        raise HTTPException(status_code=410, detail=QR_LOGIN_EXPIRED_MESSAGE)
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    token = create_login_token(
        session=session,
        request=request,
        user=user,
        tenant_id=tenant_id,
    )
    create_login_log(
        session=session,
        request=request,
        email=user.email,
        status="success",
        user=user,
        tenant_id=token.tenant_id,
    )
    return token


@router.post("/login/sms-code", response_model=SmsCodeSent)
def send_login_sms_code(
    *,
    request: Request,
    session: SessionDep,
    body: SmsCodeRequest,
) -> SmsCodeSent:
    if not redis_cache.is_enabled():
        raise HTTPException(
            status_code=503,
            detail=SMS_VERIFICATION_UNAVAILABLE_MESSAGE,
        )

    tenant = get_login_tenant(session=session, tenant_code=body.tenant_code)
    activate_platform_tenant_scope(session, tenant.id, privileged=True)
    mobile = normalize_mobile(body.mobile)
    code_key, attempts_key, cooldown_key = get_sms_verification_keys(
        tenant_id=tenant.id,
        mobile=mobile,
        scene=body.scene,
    )
    if redis_cache.get(cooldown_key):
        raise HTTPException(
            status_code=429,
            detail="SMS verification code was sent recently.",
        )

    client_ip = get_client_ip(request) or "unknown"
    ip_limit_key = redis_cache.build_key(
        CacheNamespace.SMS_VERIFICATION,
        "send-ip",
        client_ip,
    )
    ip_send_count = redis_cache.incr(
        ip_limit_key,
        ttl_seconds=settings.SMS_CODE_TTL_SECONDS,
    )
    if ip_send_count is None:
        raise HTTPException(
            status_code=503,
            detail=SMS_VERIFICATION_UNAVAILABLE_MESSAGE,
        )
    if ip_send_count > settings.SMS_CODE_SEND_MAX_PER_IP:
        raise HTTPException(
            status_code=429,
            detail="Too many SMS verification requests.",
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = hash_sms_code(
        tenant_id=tenant.id,
        mobile=mobile,
        scene=body.scene,
        code=code,
    )
    code_saved = redis_cache.set(
        code_key,
        code_hash,
        ttl_seconds=settings.SMS_CODE_TTL_SECONDS,
    )
    cooldown_saved = redis_cache.set(
        cooldown_key,
        "1",
        ttl_seconds=settings.SMS_CODE_RESEND_SECONDS,
    )
    if not code_saved or not cooldown_saved:
        redis_cache.delete(code_key, attempts_key, cooldown_key)
        raise HTTPException(
            status_code=503,
            detail=SMS_VERIFICATION_UNAVAILABLE_MESSAGE,
        )

    template = session.exec(
        select(SmsTemplate).where(
            SmsTemplate.tenant_id == tenant.id,
            SmsTemplate.code == "verify_code",
            SmsTemplate.is_active,
        )
    ).first()
    if template is None:
        redis_cache.delete(code_key, attempts_key, cooldown_key)
        raise HTTPException(
            status_code=503,
            detail=SMS_VERIFICATION_UNAVAILABLE_MESSAGE,
        )
    channel = get_template_channel(session=session, template=template)
    content = template.content.replace("{code}", code)
    if channel is None or not channel.is_active:
        create_sms_log(
            session=session,
            channel=channel,
            template=template,
            mobile=mobile,
            content=content,
            params={"code": code},
            status="failed",
            code="CHANNEL_UNAVAILABLE",
            message="No active SMS channel is available.",
        )
        redis_cache.delete(code_key, attempts_key, cooldown_key)
        raise HTTPException(
            status_code=503,
            detail=SMS_VERIFICATION_UNAVAILABLE_MESSAGE,
        )
    if channel.provider != "debug":
        create_sms_log(
            session=session,
            channel=channel,
            template=template,
            mobile=mobile,
            content=content,
            params={"code": code},
            status="failed",
            code="PROVIDER_NOT_CONNECTED",
            message=f"{channel.provider} delivery is not connected.",
        )
        redis_cache.delete(code_key, attempts_key, cooldown_key)
        raise HTTPException(
            status_code=503,
            detail=SMS_VERIFICATION_UNAVAILABLE_MESSAGE,
        )

    create_sms_log(
        session=session,
        channel=channel,
        template=template,
        mobile=mobile,
        content=content,
        params={"code": code},
        status="success",
        code="DEBUG_ACCEPTED",
        message="Debug channel accepted the SMS.",
    )
    return SmsCodeSent(
        message="SMS verification code sent",
        retry_after_seconds=settings.SMS_CODE_RESEND_SECONDS,
        debug_code=code if settings.ENVIRONMENT == "local" else None,
    )


@router.post("/login/sms", response_model=Token)
def login_with_sms_code(
    *,
    request: Request,
    session: SessionDep,
    body: SmsLoginRequest,
) -> Token:
    if not redis_cache.is_enabled():
        raise HTTPException(
            status_code=503,
            detail=SMS_VERIFICATION_UNAVAILABLE_MESSAGE,
        )

    tenant = get_login_tenant(session=session, tenant_code=body.tenant_code)
    mobile = normalize_mobile(body.mobile)
    code_key, attempts_key = validate_sms_verification_code(
        tenant_id=tenant.id,
        mobile=mobile,
        scene="login",
        code=body.code,
    )

    user = session.exec(select(User).where(User.mobile == mobile)).first()
    tenant_membership = (
        get_active_tenant_membership(
            session=session,
            user_id=user.id,
            tenant_id=tenant.id,
        )
        if user is not None
        else None
    )
    if user is None or not user.is_active or tenant_membership is None:
        redis_cache.delete(code_key, attempts_key)
        raise HTTPException(status_code=401, detail=SMS_LOGIN_INVALID_MESSAGE)

    redis_cache.delete(code_key, attempts_key)
    token = create_login_token(
        session=session,
        request=request,
        user=user,
        tenant_id=tenant.id,
    )
    create_login_log(
        session=session,
        request=request,
        email=user.email,
        status="success",
        user=user,
        tenant_id=token.tenant_id,
    )
    return token


@router.get("/login/registration/status", response_model=RegistrationStatus)
def read_registration_status(session: SessionDep) -> RegistrationStatus:
    return RegistrationStatus(
        enabled=is_public_registration_enabled(session=session),
        email_verification_enabled=email_verification_enabled(),
    )


@router.get("/login/registration/tenant-code-availability", response_model=RegistrationTenantCodeAvailability)
def check_registration_tenant_code(
    *, session: SessionDep,
    tenant_code: Annotated[str, Query(min_length=5, max_length=32, pattern=r"^[a-z][a-z0-9-]{4,31}$")],
) -> RegistrationTenantCodeAvailability:
    if not is_public_registration_enabled(session=session):
        raise HTTPException(status_code=403, detail="Public registration is disabled")
    exists = session.exec(select(Tenant.id).where(Tenant.code == tenant_code)).first()
    return RegistrationTenantCodeAvailability(available=exists is None)


@router.post("/login/registration/email-code", response_model=RegistrationEmailCodeSent)
def send_registration_email_code(
    *, request: Request, session: SessionDep, body: RegistrationEmailCodeRequest,
) -> RegistrationEmailCodeSent:
    if not is_public_registration_enabled(session=session):
        raise HTTPException(status_code=403, detail="Public registration is disabled")
    if not validate_slider_captcha_verification(body.captcha_verification):
        raise HTTPException(status_code=400, detail=LOGIN_SLIDER_CAPTCHA_INVALID_MESSAGE)
    send_registration_code(
        email=str(body.email).strip().lower(),
        client_ip=get_client_ip(request) or "unknown",
    )
    return RegistrationEmailCodeSent()


@router.post("/login/register-tenant", response_model=TenantRegistrationToken)
def register_tenant(
    *,
    request: Request,
    session: SessionDep,
    body: TenantRegistrationRequest,
) -> TenantRegistrationToken:
    if not is_public_registration_enabled(session=session):
        raise HTTPException(status_code=403, detail="Public registration is disabled")
    if not redis_cache.is_enabled():
        raise HTTPException(
            status_code=503,
            detail=SMS_VERIFICATION_UNAVAILABLE_MESSAGE,
        )

    tenant_code = body.tenant_code.strip().lower()
    if not TENANT_CODE_PATTERN.fullmatch(tenant_code):
        raise HTTPException(status_code=400, detail="Invalid tenant code")
    mobile = normalize_mobile(body.mobile) if body.mobile else None
    platform_tenant = get_login_tenant(
        session=session,
        tenant_code=DEFAULT_TENANT_CODE,
    )
    email = body.email.strip().lower()
    if body.email_code:
        code_key, attempts_key = validate_registration_code(email=email, code=body.email_code)
    elif settings.APP_EDITION == "esop":
        raise HTTPException(status_code=400, detail="Email verification code is required")
    else:
        code_key, attempts_key = validate_sms_verification_code(
            tenant_id=platform_tenant.id,
            mobile=mobile or "",
            scene="register",
            code=body.sms_code or "",
        )
    if session.exec(select(Tenant).where(Tenant.code == tenant_code)).first():
        raise HTTPException(status_code=409, detail="Tenant code already exists")
    if crud.get_user_by_email(session=session, email=email):
        raise HTTPException(status_code=409, detail="Email already exists")
    if mobile and session.exec(select(User).where(User.mobile == mobile)).first():
        raise HTTPException(status_code=409, detail="Mobile already exists")

    plan = session.exec(
        select(TenantPlan).where(TenantPlan.is_default, TenantPlan.is_active)
    ).first()
    template = session.exec(
        select(TenantInitializationTemplate).where(
            TenantInitializationTemplate.is_default,
            TenantInitializationTemplate.is_active,
        )
    ).first()
    if plan is None or template is None:
        raise HTTPException(
            status_code=503,
            detail="Tenant registration is not configured",
        )

    owner = User(
        email=email,
        mobile=mobile,
        full_name=body.full_name.strip(),
        hashed_password=security.get_password_hash(body.password),
        is_active=True,
        is_superuser=False,
    )
    tenant = Tenant(
        code=tenant_code,
        name=body.tenant_name.strip(),
        plan_id=plan.id,
        initialization_template_id=template.id,
        is_active=True,
    )
    free_activation_key: str | None = None
    try:
        from app.modules.tenant_initialization import (
            initialize_tenant_modules,
            prepare_tenant_creation,
        )

        prepare_tenant_creation(session=session)
        session.add(owner)
        session.add(tenant)
        session.flush()
        activate_platform_tenant_scope(session, tenant.id, privileged=True)
        if settings.APP_EDITION == "esop":
            from app.modules.tenant_activation import (
                bind_official_tenant,
                issue_free_key,
            )
            from app.platform.web_api import ensure_esop_storage_account

            ensure_esop_storage_account(session=session, tenant_id=tenant.id)
            bind_official_tenant(session, tenant.id, owner.id)
            _, free_activation_key = issue_free_key(session, tenant.id)
        provision_tenant_roles(
            session=session,
            tenant=tenant,
            template=template,
            owner=owner,
        )
        membership = session.exec(
            select(TenantMembership).where(
                TenantMembership.user_id == owner.id,
                TenantMembership.tenant_id == tenant.id,
            )
        ).one()
        membership.is_default = True
        session.add(membership)
        session.flush()
        initialize_tenant_modules(session=session, tenant_id=tenant.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Tenant registration conflicts with existing data",
        ) from exc

    redis_cache.delete(code_key, attempts_key)
    token = create_login_token(
        session=session,
        request=request,
        user=owner,
        tenant_id=tenant.id,
    )
    create_login_log(
        session=session,
        request=request,
        email=owner.email,
        status="success",
        user=owner,
        tenant_id=tenant.id,
    )
    return TenantRegistrationToken(
        **token.model_dump(), free_activation_key=free_activation_key
    )


def consume_enterprise_oidc_state(
    *, session: SessionDep, state_value: str
) -> EnterpriseOidcAuthorizationState:
    state = session.exec(
        select(EnterpriseOidcAuthorizationState).where(
            EnterpriseOidcAuthorizationState.state_hash == hash_oidc_value(state_value)
        ).with_for_update()
    ).first()
    now = get_datetime_utc()
    if not state or state.consumed_at or state.expires_at <= now:
        raise HTTPException(
            status_code=400, detail="Enterprise OIDC state is invalid or expired"
        )
    state.consumed_at = now
    session.add(state)
    session.commit()
    return state


def current_oidc_provider() -> str:
    return "google" if settings.APP_EDITION == "esop" else OIDC_PROVIDER


def create_google_tenant(*, session: SessionDep, subject: str, email: str, full_name: str) -> User:
    """Create an ESOPS tenant and bind its administrator in one transaction."""
    if not is_public_registration_enabled(session=session):
        raise HTTPException(status_code=403, detail="Public registration is disabled")
    if session.exec(select(EnterpriseOidcIdentity).where(
        EnterpriseOidcIdentity.provider == OIDC_PROVIDER,
        EnterpriseOidcIdentity.subject == subject,
    )).first():
        raise HTTPException(status_code=409, detail="Existing identity requires explicit binding")
    email = email.strip().lower()
    if crud.get_user_by_email(session=session, email=email):
        raise HTTPException(status_code=409, detail="Email already exists; sign in and bind Google in profile")
    plan = session.exec(select(TenantPlan).where(TenantPlan.is_default, TenantPlan.is_active)).first()
    template = session.exec(
        select(TenantInitializationTemplate).where(
            TenantInitializationTemplate.is_default, TenantInitializationTemplate.is_active
        )
    ).first()
    if plan is None or template is None:
        raise HTTPException(status_code=503, detail="Tenant registration is not configured")
    from app.modules.tenant_activation import bind_official_tenant, issue_free_key
    from app.modules.tenant_initialization import (
        initialize_tenant_modules,
        prepare_tenant_creation,
    )
    from app.platform.web_api import ensure_esop_storage_account

    owner = User(
        email=email,
        full_name=full_name.strip()[:255] or email.split("@", 1)[0],
        hashed_password=security.get_password_hash(secrets.token_urlsafe(48)),
        is_active=True,
        is_superuser=False,
    )
    tenant = Tenant(
        code=f"g-{uuid.uuid4().hex[:20]}",
        name=(full_name.strip() or email.split("@", 1)[0])[:100],
        plan_id=plan.id,
        initialization_template_id=template.id,
        is_active=True,
    )
    try:
        prepare_tenant_creation(session=session)
        session.add(owner)
        session.add(tenant)
        session.flush()
        session.add(EnterpriseOidcIdentity(provider="google", subject=subject, user_id=owner.id, tenant_id=tenant.id))
        session.flush()
        activate_platform_tenant_scope(session, tenant.id, privileged=True)
        ensure_esop_storage_account(session=session, tenant_id=tenant.id)
        bind_official_tenant(session, tenant.id, owner.id)
        issue_free_key(session, tenant.id)
        provision_tenant_roles(session=session, tenant=tenant, template=template, owner=owner)
        membership = session.exec(select(TenantMembership).where(
            TenantMembership.user_id == owner.id, TenantMembership.tenant_id == tenant.id
        )).one()
        membership.is_default = True
        session.add(membership)
        initialize_tenant_modules(session=session, tenant_id=tenant.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Google account or tenant registration already exists") from exc
    return owner


def resolve_enterprise_oidc_user(
    *, session: SessionDep, claims: dict[str, Any]
) -> User:
    subject = claims.get("sub")
    email = claims.get("email")
    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(email, str)
        or not email
    ):
        raise HTTPException(
            status_code=403,
            detail="Enterprise OIDC identity is not linked to an active local user",
        )
    if (
        settings.ENTERPRISE_OIDC_REQUIRE_VERIFIED_EMAIL
        and claims.get("email_verified") is not True
    ):
        raise HTTPException(
            status_code=403,
            detail="Enterprise OIDC identity is not linked to an active local user",
        )

    identity = session.exec(
        select(EnterpriseOidcIdentity).where(
            EnterpriseOidcIdentity.provider == current_oidc_provider(),
            EnterpriseOidcIdentity.subject == subject,
        )
    ).first()
    if settings.APP_EDITION == "esop" and identity is None:
        if claims.get("email_verified") is not True:
            raise HTTPException(status_code=403, detail="Google email must be verified")
        domain = email.rsplit("@", 1)[-1].lower()
        hosted_domain = claims.get("hd")
        if domain != "gmail.com" and not (
            isinstance(hosted_domain, str) and hosted_domain.lower() == domain
        ):
            raise HTTPException(status_code=403, detail="Use email registration and bind this Google account in profile")
        full_name = claims.get("name")
        return create_google_tenant(session=session, subject=subject, email=email, full_name=full_name if isinstance(full_name, str) else "")
    if settings.APP_EDITION == "esop" and identity.tenant_id is None:
        # Existing ESOPS accounts require explicit binding in an authenticated flow.
        raise HTTPException(
            status_code=403,
            detail="Enterprise OIDC identity is not linked to an active local user",
        )
    user = (
        session.get(User, identity.user_id)
        if identity
        else crud.get_user_by_email(session=session, email=email.strip().lower())
    )
    if not user:
        raise HTTPException(
            status_code=403,
            detail="Enterprise OIDC identity is not linked to an active local user",
        )

    tenant_membership = get_active_tenant_membership(
        session=session,
        user_id=user.id,
        tenant_id=identity.tenant_id if identity and settings.APP_EDITION == "esop" else None,
    )
    if tenant_membership is None:
        raise HTTPException(
            status_code=403,
            detail="Enterprise OIDC identity is not linked to an active local user",
        )
    _, tenant = tenant_membership
    activate_platform_tenant_scope(session, tenant.id)
    if settings.APP_EDITION == "esop":
        from app.platform.user_directory import SqlUserDirectory

        if not SqlUserDirectory(session).is_tenant_administrator(user.id, tenant.id):
            raise HTTPException(status_code=403, detail="Enterprise OIDC requires a tenant administrator")

    role_codes = role_codes_from_claims(claims)
    roles: list[Role] = []
    if settings.APP_EDITION != "esop" and settings.ENTERPRISE_OIDC_ROLE_SYNC_MODE == "replace" and not user.is_superuser:
        if role_codes:
            roles = session.exec(
                select(Role).where(
                    Role.tenant_id == tenant.id,
                    Role.code.in_(role_codes),
                )
            ).all()
            if len(roles) != len(role_codes):
                raise HTTPException(
                    status_code=503, detail="Enterprise OIDC is not configured"
                )
        session.exec(
            delete(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.tenant_id == tenant.id,
            )
        )
        for role in roles:
            session.add(
                UserRole(
                    user_id=user.id,
                    role_id=role.id,
                    tenant_id=tenant.id,
                )
            )
        redis_cache.bump_namespace(CacheNamespace.RBAC)

    if settings.APP_EDITION != "esop" and settings.ENTERPRISE_OIDC_SYNC_ACTIVE_STATUS:
        external_active = external_identity_is_active(claims)
        if user.is_active != external_active:
            user.is_active = external_active
            user.updated_at = get_datetime_utc()
            if not external_active:
                crud.revoke_user_sessions(session=session, user_id=user.id)
            session.add(user)

    if not identity:
        session.add(
            EnterpriseOidcIdentity(
                provider=OIDC_PROVIDER,
                subject=subject,
                user_id=user.id,
            )
        )
    session.commit()
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Enterprise OIDC identity is not linked to an active local user",
        )
    return user


@router.get("/login/captcha", response_model=LoginCaptchaChallenge)
def get_login_captcha(request: Request, username: str) -> LoginCaptchaChallenge:
    captcha = create_login_captcha(request, username)
    if captcha is None:
        raise HTTPException(status_code=404, detail="Captcha verification is disabled")
    return captcha


@router.post("/system/captcha/get")
def get_slider_captcha(body: dict[str, Any]) -> dict[str, Any]:
    if not settings.LOGIN_SLIDER_CAPTCHA_ENABLED:
        return _slider_error("Slider captcha is disabled")
    if body.get("captchaType") not in {None, "blockPuzzle"}:
        return _slider_error("Unsupported captcha type")
    target_x = random.randint(150, SLIDER_IMAGE_WIDTH - SLIDER_PIECE_SIZE - 18)
    original_image, jigsaw_image = _build_slider_images(target_x)
    token = secrets.token_urlsafe(32)
    secret_key = secrets.token_urlsafe(12)[:16]
    expected_x = target_x * SLIDER_BAR_WIDTH / SLIDER_IMAGE_WIDTH
    _slider_set(
        token,
        {
            "target_x": target_x,
            "expected_x": expected_x,
            "secret_key": secret_key,
            "verified": False,
        },
    )
    return {
        "repCode": "0000",
        "repMsg": "success",
        "repData": {
            "originalImageBase64": original_image,
            "jigsawImageBase64": jigsaw_image,
            "token": token,
            "secretKey": secret_key,
            "imageWidth": SLIDER_IMAGE_WIDTH,
            "imageHeight": SLIDER_IMAGE_HEIGHT,
            "pieceWidth": SLIDER_PIECE_SIZE,
            "pieceY": SLIDER_PIECE_Y,
        },
    }


@router.post("/system/captcha/check")
def check_slider_captcha(body: dict[str, Any]) -> dict[str, Any]:
    if not settings.LOGIN_SLIDER_CAPTCHA_ENABLED:
        return _slider_error("Slider captcha is disabled")
    token = str(body.get("token") or "")
    point_json = str(body.get("pointJson") or "")
    payload = _slider_get(token)
    if not payload or not point_json:
        return _slider_error("Captcha is invalid or expired")
    point_text = _aes_decrypt(point_json, str(payload.get("secret_key", "")))
    if point_text is None:
        return _slider_error("Captcha coordinates are invalid")
    try:
        point = json.loads(point_text)
        valid = (
            abs(float(point["x"]) - float(payload["expected_x"])) <= 6
            and abs(float(point.get("y", 5)) - 5) <= 5
        )
    except KeyError, TypeError, ValueError, json.JSONDecodeError:
        valid = False
    if not valid:
        return _slider_error("Captcha coordinates are invalid")
    payload["verified"] = True
    verification = _aes_encrypt(f"{token}---{point_text}", str(payload["secret_key"]))
    payload["verification"] = verification
    _slider_set(token, payload)
    _slider_store_verification(verification, token)
    return {"repCode": "0000", "repMsg": "success", "repData": None}


@router.post("/login/access-token")
def login_access_token(
    request: Request,
    session: SessionDep,
    form_data: Annotated[LoginFormData, Depends(get_login_form_data)],
) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    login_identifier = normalize_login_identifier(form_data.username)
    if is_login_rate_limited(request, login_identifier):
        create_login_log(
            session=session,
            request=request,
            email=login_identifier,
            status="fail",
            failure_reason=LOGIN_RATE_LIMIT_MESSAGE,
        )
        raise HTTPException(status_code=429, detail=LOGIN_RATE_LIMIT_MESSAGE)
    if (
        settings.LOGIN_SLIDER_CAPTCHA_ENABLED
        and not validate_slider_captcha_verification(form_data.captcha_verification)
    ):
        create_login_log(
            session=session,
            request=request,
            email=login_identifier,
            status="fail",
            failure_reason=LOGIN_SLIDER_CAPTCHA_INVALID_MESSAGE,
        )
        raise HTTPException(
            status_code=400, detail=LOGIN_SLIDER_CAPTCHA_INVALID_MESSAGE
        )
    if requires_login_captcha(request, login_identifier) and not validate_login_captcha(
        request,
        login_identifier,
        captcha_id=form_data.captcha_id,
        captcha_code=form_data.captcha_code,
    ):
        create_login_log(
            session=session,
            request=request,
            email=login_identifier,
            status="fail",
            failure_reason=(
                LOGIN_CAPTCHA_INVALID_MESSAGE
                if form_data.captcha_id or form_data.captcha_code
                else LOGIN_CAPTCHA_REQUIRED_MESSAGE
            ),
        )
        raise HTTPException(
            status_code=400,
            detail=(
                LOGIN_CAPTCHA_INVALID_MESSAGE
                if form_data.captcha_id or form_data.captcha_code
                else LOGIN_CAPTCHA_REQUIRED_MESSAGE
            ),
        )

    tenant_id: uuid.UUID | None = None
    if form_data.tenant_code:
        tenant_code = form_data.tenant_code.strip().lower()
        tenant = session.exec(
            select(Tenant).where(Tenant.code == tenant_code, Tenant.is_active)
        ).first()
        if tenant is None:
            raise HTTPException(status_code=403, detail="User has no active tenant")
        tenant_id = tenant.id
    user = crud.authenticate(
        session=session, email=login_identifier, password=form_data.password, tenant_id=tenant_id
    )
    if not user:
        rate_limited = record_failed_login_attempt(request, login_identifier)
        create_login_log(
            session=session,
            request=request,
            email=login_identifier,
            status="fail",
            failure_reason=(
                LOGIN_RATE_LIMIT_MESSAGE
                if rate_limited
                else "Incorrect email or password"
            ),
        )
        if rate_limited:
            raise HTTPException(status_code=429, detail=LOGIN_RATE_LIMIT_MESSAGE)
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    elif not user.is_active:
        rate_limited = record_failed_login_attempt(request, login_identifier)
        create_login_log(
            session=session,
            request=request,
            email=login_identifier,
            status="fail",
            user=user,
            failure_reason=(
                LOGIN_RATE_LIMIT_MESSAGE if rate_limited else "Inactive user"
            ),
        )
        if rate_limited:
            raise HTTPException(status_code=429, detail=LOGIN_RATE_LIMIT_MESSAGE)
        raise HTTPException(status_code=403, detail="Inactive user")

    if user.mfa_enabled:
        if not user.mfa_secret_encrypted:
            create_login_log(
                session=session,
                request=request,
                email=login_identifier,
                status="fail",
                user=user,
                failure_reason=LOGIN_MFA_SETUP_INVALID_MESSAGE,
            )
            raise HTTPException(status_code=400, detail=LOGIN_MFA_SETUP_INVALID_MESSAGE)
        if not form_data.mfa_code:
            create_login_log(
                session=session,
                request=request,
                email=login_identifier,
                status="fail",
                user=user,
                failure_reason=LOGIN_MFA_REQUIRED_MESSAGE,
            )
            raise HTTPException(status_code=400, detail=LOGIN_MFA_REQUIRED_MESSAGE)
        try:
            mfa_secret = decrypt_totp_secret(user.mfa_secret_encrypted)
        except ValueError:
            create_login_log(
                session=session,
                request=request,
                email=login_identifier,
                status="fail",
                user=user,
                failure_reason=LOGIN_MFA_SETUP_INVALID_MESSAGE,
            )
            raise HTTPException(status_code=400, detail=LOGIN_MFA_SETUP_INVALID_MESSAGE)
        mfa_verified = verify_totp_code(secret=mfa_secret, code=form_data.mfa_code)
        if not mfa_verified:
            remaining_recovery_codes = consume_recovery_code(
                user.mfa_recovery_code_hashes,
                form_data.mfa_code,
            )
            if remaining_recovery_codes is not None:
                user.mfa_recovery_code_hashes = remaining_recovery_codes
                session.add(user)
                mfa_verified = True
        if not mfa_verified:
            rate_limited = record_failed_login_attempt(request, login_identifier)
            create_login_log(
                session=session,
                request=request,
                email=login_identifier,
                status="fail",
                user=user,
                failure_reason=(
                    LOGIN_RATE_LIMIT_MESSAGE
                    if rate_limited
                    else LOGIN_MFA_INVALID_MESSAGE
                ),
            )
            if rate_limited:
                raise HTTPException(status_code=429, detail=LOGIN_RATE_LIMIT_MESSAGE)
            raise HTTPException(status_code=400, detail=LOGIN_MFA_INVALID_MESSAGE)

    clear_failed_login_attempts(request, login_identifier)
    token = create_login_token(
        session=session,
        request=request,
        user=user,
        tenant_id=tenant_id,
    )
    create_login_log(
        session=session,
        request=request,
        email=login_identifier,
        status="success",
        user=user,
        tenant_id=token.tenant_id,
    )
    return token


@router.get("/login/enterprise-oidc/status", response_model=EnterpriseOidcStatus)
def read_enterprise_oidc_status() -> EnterpriseOidcStatus:
    if settings.APP_EDITION == "esop":
        from app.platform.infra.google_oauth_config import load_google_oauth_config

        try:
            config = load_google_oauth_config()
            enabled = config.enabled and bool(config.client_id and config.client_secret and config.redirect_uri)
        except HTTPException:
            enabled = False
        return EnterpriseOidcStatus(enabled=enabled, login_url=f"{settings.API_V1_STR}/login/enterprise-oidc" if enabled else None)
    configured = all(
        (
            settings.ENTERPRISE_OIDC_CLIENT_ID,
            settings.ENTERPRISE_OIDC_CLIENT_SECRET,
            settings.ENTERPRISE_OIDC_ISSUER,
            settings.ENTERPRISE_OIDC_REDIRECT_URI,
        )
    )
    enabled = settings.ENTERPRISE_OIDC_ENABLED and configured
    return EnterpriseOidcStatus(
        enabled=enabled,
        login_url=f"{settings.API_V1_STR}/login/enterprise-oidc" if enabled else None,
    )


@router.get("/login/enterprise-oidc", response_model=None)
def start_enterprise_oidc_login(
    session: SessionDep,
) -> RedirectResponse:
    google_config = None
    if settings.APP_EDITION == "esop":
        from app.platform.infra.google_oauth_config import (
            google_oauth_fingerprint,
            load_google_oauth_config,
        )

        google_config = load_google_oauth_config()
        metadata = get_oidc_provider_metadata(google_config=google_config)
    else:
        metadata = get_oidc_provider_metadata()
    state_value = generate_oidc_value()
    if google_config is not None:
        digest = google_oauth_fingerprint(google_config)
        state_value = f"{state_value}.{digest}"
    code_verifier = generate_oidc_value()
    nonce = generate_oidc_value()
    session.add(
        EnterpriseOidcAuthorizationState(
            state_hash=hash_oidc_value(state_value),
            code_verifier=code_verifier,
            nonce=nonce,
            expires_at=get_datetime_utc()
            + timedelta(seconds=settings.ENTERPRISE_OIDC_STATE_TTL_SECONDS),
        )
    )
    session.commit()
    query = urlencode(
        {
            "client_id": google_config.client_id if google_config is not None else settings.ENTERPRISE_OIDC_CLIENT_ID,
            "code_challenge": build_pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
            "nonce": nonce,
            "redirect_uri": google_config.redirect_uri if google_config is not None else settings.ENTERPRISE_OIDC_REDIRECT_URI,
            "response_type": "code",
            "scope": settings.ENTERPRISE_OIDC_SCOPES,
            "state": state_value,
        }
    )
    return RedirectResponse(
        url=f"{metadata['authorization_endpoint']}?{query}", status_code=302,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


class GoogleBindingStart(BaseModel):
    current_password: str
    mfa_code: str | None = Field(default=None, max_length=32)


@router.get("/users/me/google-binding")
def google_binding_status(session: SessionDep, current_user: CurrentUser, tenant: CurrentTenant) -> dict[str, Any]:
    from app.platform.user_directory import SqlUserDirectory

    if settings.APP_EDITION != "esop":
        raise HTTPException(status_code=404, detail="Google binding unavailable")
    eligible = SqlUserDirectory(session).is_tenant_administrator(current_user.id, tenant.tenant_id)
    identity = session.exec(select(EnterpriseOidcIdentity).where(
        EnterpriseOidcIdentity.provider == "google",
        EnterpriseOidcIdentity.user_id == current_user.id,
        EnterpriseOidcIdentity.tenant_id == tenant.tenant_id,
    )).first() if eligible else None
    return {"eligible": eligible, "bound": identity is not None, "email": None}


@router.post("/users/me/google-binding/start")
def google_binding_start(session: SessionDep, current_user: CurrentUser, tenant: CurrentTenant, body: GoogleBindingStart) -> dict[str, str]:
    from app.platform.user_directory import SqlUserDirectory

    if settings.APP_EDITION != "esop":
        raise HTTPException(status_code=404, detail="Google binding unavailable")
    if not SqlUserDirectory(session).is_tenant_administrator(current_user.id, tenant.tenant_id):
        raise HTTPException(status_code=403, detail="Google binding requires a tenant administrator")
    attempts = redis_cache.incr(
        redis_cache.build_key("google-binding", "password-attempts", str(current_user.id)),
        ttl_seconds=300,
    )
    if attempts is None:
        raise HTTPException(status_code=503, detail="Google binding verification unavailable")
    if attempts > 5:
        raise HTTPException(status_code=429, detail="Too many Google binding attempts")
    password_ok, _ = security.verify_password(body.current_password, current_user.hashed_password)
    if not password_ok:
        raise HTTPException(status_code=403, detail="Invalid current password")
    if current_user.mfa_enabled:
        try:
            secret = decrypt_totp_secret(current_user.mfa_secret_encrypted or "")
        except ValueError:
            raise HTTPException(status_code=403, detail="MFA verification required") from None
        if not body.mfa_code or not verify_totp_code(secret=secret, code=body.mfa_code):
            raise HTTPException(status_code=403, detail="MFA verification required")
    existing_identity = session.exec(select(EnterpriseOidcIdentity).where(
        EnterpriseOidcIdentity.provider.in_(["google", OIDC_PROVIDER]),
        EnterpriseOidcIdentity.user_id == current_user.id,
    )).first()
    if existing_identity is not None and (existing_identity.provider == "google" or (existing_identity.tenant_id is not None and existing_identity.tenant_id != tenant.tenant_id)):
        raise HTTPException(status_code=409, detail="Google identity already bound")
    verified = session.info.get("verified_request_session")
    if not verified or verified[0] != current_user.id or verified[2] != tenant.tenant_id:
        raise HTTPException(status_code=403, detail="Session invalid")
    response = start_enterprise_oidc_login(session=session)
    url = response.headers["location"]
    state = parse_qs(urlparse(url).query)["state"][0]
    state_row = session.exec(select(EnterpriseOidcAuthorizationState).where(
        EnterpriseOidcAuthorizationState.state_hash == hash_oidc_value(state)
    ).with_for_update()).one()
    state_row.purpose = "bind"
    state_row.binding_user_id = current_user.id
    state_row.binding_tenant_id = tenant.tenant_id
    state_row.binding_session_jti = verified[1]
    session.add(state_row)
    session.commit()
    return {"authorization_url": url}


@router.get("/login/enterprise-oidc/callback", response_model=None)
def complete_enterprise_oidc_login(
    request: Request,
    session: SessionDep,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    if not state:
        create_login_log(
            session=session,
            request=request,
            email="enterprise-oidc",
            status="fail",
            failure_reason="Enterprise OIDC state is invalid or expired",
        )
        raise HTTPException(
            status_code=400, detail="Enterprise OIDC state is invalid or expired"
        )
    claims: dict[str, Any] | None = None
    try:
        authorization_state = consume_enterprise_oidc_state(
            session=session, state_value=state
        )
        if error or not code:
            raise HTTPException(
                status_code=400, detail="Enterprise OIDC identity token is invalid"
            )
        google_config = None
        if settings.APP_EDITION == "esop":
            from app.platform.infra.google_oauth_config import (
                google_oauth_fingerprint,
                load_google_oauth_config,
            )

            google_config = load_google_oauth_config()
            digest = google_oauth_fingerprint(google_config)
            if not google_config.enabled or "." not in state or not hmac.compare_digest(state.rsplit(".", 1)[1], digest):
                raise HTTPException(status_code=400, detail="Enterprise OIDC state is invalid or expired")
            metadata = get_oidc_provider_metadata(google_config=google_config)
            id_token = exchange_authorization_code(metadata=metadata, code=code, code_verifier=authorization_state.code_verifier, google_config=google_config)
            claims = validate_identity_token(id_token=id_token, metadata=metadata, expected_nonce=authorization_state.nonce, google_config=google_config)
            from app.platform.infra.google_oauth_config import (
                lock_and_load_google_oauth_config,
            )

            current_config = lock_and_load_google_oauth_config(session)
            if not current_config.enabled or not hmac.compare_digest(google_oauth_fingerprint(current_config), digest):
                raise HTTPException(status_code=400, detail="Enterprise OIDC state is invalid or expired")
        else:
            metadata = get_oidc_provider_metadata()
            id_token = exchange_authorization_code(metadata=metadata, code=code, code_verifier=authorization_state.code_verifier)
            claims = validate_identity_token(id_token=id_token, metadata=metadata, expected_nonce=authorization_state.nonce)
        if authorization_state.purpose == "bind":
            from app.platform.user_directory import SqlUserDirectory

            binding_user = authorization_state.binding_user_id
            binding_tenant = authorization_state.binding_tenant_id
            binding_jti = authorization_state.binding_session_jti
            subject = claims.get("sub")
            if not binding_user or not binding_tenant or not binding_jti or not isinstance(subject, str) or not subject or claims.get("email_verified") is not True:
                raise HTTPException(status_code=403, detail="Google binding invalid")
            activate_platform_tenant_scope(session, binding_tenant)
            user_session = session.exec(select(UserSession).where(
                UserSession.user_id == binding_user, UserSession.tenant_id == binding_tenant,
                UserSession.token_jti == binding_jti, UserSession.revoked_at.is_(None),
                UserSession.expires_at > get_datetime_utc(),
            ).with_for_update()).first()
            user = session.exec(select(User).where(User.id == binding_user).with_for_update()).first()
            if not user_session or not user or not user.is_active or not get_active_tenant_membership(session=session, user_id=binding_user, tenant_id=binding_tenant) or not SqlUserDirectory(session).is_tenant_administrator(binding_user, binding_tenant):
                raise HTTPException(status_code=403, detail="Google binding session invalid")
            matching_identities = session.exec(select(EnterpriseOidcIdentity).where(
                EnterpriseOidcIdentity.provider.in_(["google", OIDC_PROVIDER]),
                ((EnterpriseOidcIdentity.subject == subject) | (EnterpriseOidcIdentity.user_id == binding_user)),
            ).with_for_update()).all()
            if matching_identities:
                if len(matching_identities) != 1:
                    raise HTTPException(status_code=409, detail="Google identity already bound")
                existing_identity = matching_identities[0]
                if existing_identity.subject != subject or existing_identity.user_id != binding_user or existing_identity.provider == "google" or (existing_identity.tenant_id is not None and existing_identity.tenant_id != binding_tenant):
                    raise HTTPException(status_code=409, detail="Google identity already bound")
                # Legacy identities require explicit authenticated binding to choose a tenant.
                existing_identity.tenant_id = binding_tenant
                existing_identity.provider = "google"
                session.add(existing_identity)
            else:
                session.add(EnterpriseOidcIdentity(provider="google", subject=subject, user_id=binding_user, tenant_id=binding_tenant))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise HTTPException(status_code=409, detail="Google identity already bound") from exc
            return RedirectResponse(url="/profile?google_binding=success", status_code=302, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        user = resolve_enterprise_oidc_user(session=session, claims=claims)
    except HTTPException as exc:
        if 'authorization_state' in locals() and authorization_state.purpose == "bind":
            return RedirectResponse(url="/profile?google_binding=error", status_code=302, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        claimed_email = claims.get("email") if claims else None
        create_login_log(
            session=session,
            request=request,
            email=claimed_email
            if isinstance(claimed_email, str)
            else "enterprise-oidc",
            status="fail",
            failure_reason=str(exc.detail),
        )
        if settings.APP_EDITION == "esop":
            return RedirectResponse(
                url="/auth/login?google_error=login_failed",
                status_code=302,
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        raise
    ticket_tenant_id = None
    if settings.APP_EDITION == "esop":
        from app.platform.infra.google_oauth_config import (
            lock_and_load_google_oauth_config,
        )

        ticket_config = lock_and_load_google_oauth_config(session)
        if not ticket_config.enabled or not hmac.compare_digest(google_oauth_fingerprint(ticket_config), digest):
            return RedirectResponse(url="/auth/login?google_error=login_failed", status_code=302, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        identity = session.exec(
            select(EnterpriseOidcIdentity).where(
                EnterpriseOidcIdentity.provider == current_oidc_provider(),
                EnterpriseOidcIdentity.subject == claims["sub"],
            )
        ).first()
        if identity is None or identity.tenant_id is None:
            return RedirectResponse(
                url="/auth/login?google_error=login_failed",
                status_code=302,
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        ticket_tenant_id = identity.tenant_id
    ticket_value = generate_oidc_value()
    session.add(
        EnterpriseOidcLoginTicket(
            ticket_hash=hash_oidc_value(f"{ticket_value}.{digest}" if settings.APP_EDITION == "esop" else ticket_value),
            user_id=user.id,
            tenant_id=ticket_tenant_id,
            expires_at=get_datetime_utc()
            + timedelta(seconds=settings.ENTERPRISE_OIDC_TICKET_TTL_SECONDS),
        )
    )
    session.commit()
    frontend_login_url = (
        settings.ENTERPRISE_OIDC_FRONTEND_LOGIN_URL
        or f"{settings.FRONTEND_HOST.rstrip('/')}/auth/login"
    )
    separator = "&" if "?" in frontend_login_url else "?"
    return RedirectResponse(
        url=f"{frontend_login_url}{separator}enterprise_ticket={ticket_value}",
        status_code=302,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.post("/login/enterprise-oidc/exchange", response_model=Token)
def exchange_enterprise_oidc_ticket(
    *,
    request: Request,
    session: SessionDep,
    body: EnterpriseOidcTicketExchange,
) -> Token:
    ticket_digest = None
    if settings.APP_EDITION == "esop":
        from app.platform.infra.google_oauth_config import (
            google_oauth_fingerprint,
            lock_and_load_google_oauth_config,
        )

        ticket_config = lock_and_load_google_oauth_config(session)
        if not ticket_config.enabled:
            raise HTTPException(status_code=400, detail="Enterprise OIDC login ticket is invalid or expired")
        ticket_digest = google_oauth_fingerprint(ticket_config)
    ticket = session.exec(
        select(EnterpriseOidcLoginTicket).where(
            EnterpriseOidcLoginTicket.ticket_hash == hash_oidc_value(f"{body.ticket}.{ticket_digest}" if ticket_digest is not None else body.ticket)
        ).with_for_update()
    ).first()
    now = get_datetime_utc()
    if not ticket or ticket.consumed_at or ticket.expires_at <= now:
        raise HTTPException(
            status_code=400,
            detail="Enterprise OIDC login ticket is invalid or expired",
        )
    ticket.consumed_at = now
    session.add(ticket)
    session.commit()
    user = session.get(User, ticket.user_id)
    if not user or not user.is_active:
        create_login_log(
            session=session,
            request=request,
            email=user.email if user else "enterprise-oidc",
            status="fail",
            user=user,
            failure_reason="Enterprise OIDC identity is not linked to an active local user",
        )
        raise HTTPException(
            status_code=403,
            detail="Enterprise OIDC identity is not linked to an active local user",
        )
    if settings.APP_EDITION == "esop" and user.mfa_enabled:
        raise HTTPException(
            status_code=403,
            detail="Google login is unavailable while MFA is enabled; use password login",
        )
    if settings.APP_EDITION == "esop":
        from app.platform.user_directory import SqlUserDirectory

        if ticket.tenant_id is None:
            raise HTTPException(status_code=403, detail="Enterprise OIDC tenant is unavailable")
        activate_platform_tenant_scope(session, ticket.tenant_id)
        if not SqlUserDirectory(session).is_tenant_administrator(user.id, ticket.tenant_id):
            raise HTTPException(status_code=403, detail="Enterprise OIDC requires a tenant administrator")
        current_config = lock_and_load_google_oauth_config(session)
        if not current_config.enabled or not hmac.compare_digest(google_oauth_fingerprint(current_config), ticket_digest):
            raise HTTPException(status_code=400, detail="Enterprise OIDC login ticket is invalid or expired")
    token = create_login_token(session=session, request=request, user=user, tenant_id=ticket.tenant_id)
    create_login_log(
        session=session,
        request=request,
        email=user.email,
        status="success",
        user=user,
        tenant_id=token.tenant_id,
    )
    return token


@router.post("/login/test-token", response_model=UserPublic)
def test_token(current_user: CurrentUser) -> Any:
    """
    Test access token
    """
    return current_user


@router.post("/password-recovery/email-code", response_model=RegistrationEmailCodeSent)
def send_password_recovery_code(request: Request, session: SessionDep, body: PasswordRecoverySend) -> RegistrationEmailCodeSent:
    if not validate_slider_captcha_verification(body.captcha_verification):
        raise HTTPException(status_code=400, detail=LOGIN_SLIDER_CAPTCHA_INVALID_MESSAGE)
    send_recovery_code(session=session, tenant_code=body.tenant_code, email=str(body.email), client_ip=get_client_ip(request) or "unknown")
    return RegistrationEmailCodeSent()


@router.post("/password-recovery/verify-code", response_model=PasswordRecoveryProof)
def verify_password_recovery_code(session: SessionDep, body: PasswordRecoveryVerify) -> PasswordRecoveryProof:
    return PasswordRecoveryProof(reset_token=verify_recovery_code(session=session, tenant_code=body.tenant_code, email=str(body.email), code=body.code))


@router.post("/password-recovery/reset", response_model=Message)
def reset_password_by_email_code(session: SessionDep, body: PasswordRecoveryReset) -> Message:
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    complete_recovery(session=session, reset_token=body.reset_token, new_password=body.new_password)
    return Message(message="Password updated successfully")


@router.post("/password-recovery/{email}")
def recover_password(email: str, session: SessionDep) -> Message:
    """
    Password Recovery
    """
    user = crud.get_user_by_email(session=session, email=email)

    # Always return the same response to prevent email enumeration attacks
    # Only send email if user actually exists
    if user:
        password_reset_token = generate_password_reset_token(email=email)
        email_data = generate_reset_password_email(
            email_to=user.email, email=email, token=password_reset_token
        )
        send_email(
            email_to=user.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return Message(
        message="If that email is registered, we sent a password recovery link"
    )


@router.post("/reset-password")
def reset_password(session: SessionDep, body: NewPassword) -> Message:
    """
    Reset password
    """
    email = verify_password_reset_token(token=body.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")
    user = crud.get_user_by_email(session=session, email=email)
    if not user:
        # Don't reveal that the user doesn't exist - use same error as invalid token
        raise HTTPException(status_code=400, detail="Invalid token")
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    user_in_update = UserUpdate(password=body.new_password)
    crud.update_user(
        session=session,
        db_user=user,
        user_in=user_in_update,
    )
    crud.revoke_user_sessions_across_tenants(session=session, user_id=user.id)
    return Message(message="Password updated successfully")


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_active_superuser)],
    response_class=HTMLResponse,
)
def recover_password_html_content(email: str, session: SessionDep) -> Any:
    """
    HTML Content for Password Recovery
    """
    user = crud.get_user_by_email(session=session, email=email)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system.",
        )
    password_reset_token = generate_password_reset_token(email=email)
    email_data = generate_reset_password_email(
        email_to=user.email, email=email, token=password_reset_token
    )

    return HTMLResponse(
        content=email_data.html_content, headers={"subject:": email_data.subject}
    )
