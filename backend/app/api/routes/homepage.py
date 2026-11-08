"""Public homepage content and platform-only editing."""

import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlmodel import select

from app.api.deps import (
    PlatformConfigurationTenant,
    SessionDep,
    get_current_active_superuser,
    require_permission,
)
from app.api.routes.login import validate_slider_captcha_verification
from app.core.cache import CacheNamespace, redis_cache
from app.core.clock import get_datetime_utc
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.platform.core.configuration_models import SystemSetting
from app.platform.infra.storage import get_terminal_download_url
from app.platform.tenant_uow import PlatformTenantUnitOfWork

router = APIRouter(prefix="/homepage", tags=["homepage"])
DEFAULTS = json.loads(
    (Path(__file__).resolve().parents[2] / "platform/homepage_defaults.json").read_text()
)
LEGAL_DEFAULTS = json.loads(
    (Path(__file__).resolve().parents[2] / "platform/legal_defaults.json").read_text()
)
SETTING_PREFIX = "homepage."


class HomepagePublic(BaseModel):
    locales: dict[str, dict[str, str]]
    media: dict[str, str]


class HomepageLocaleUpdate(BaseModel):
    values: dict[str, str]


class HomepageMediaUpdate(BaseModel):
    backendImage: str = Field(max_length=500)
    terminalImage: str = Field(max_length=500)


class TerminalDownloadConfig(BaseModel):
    version: str = Field(max_length=32)
    arm64Key: str = Field(max_length=500)
    arm32Key: str = Field(max_length=500)
    windows64Key: str = Field(default="", max_length=500)
    ubuntuArm64Key: str = Field(default="", max_length=500)


class TerminalDownloadPublic(BaseModel):
    version: str
    arm64Available: bool
    arm32Available: bool
    windows64Available: bool
    ubuntuArm64Available: bool


class TerminalDownloadRequest(BaseModel):
    captchaVerification: str = Field(min_length=1, max_length=4096)


class TerminalDownloadLink(BaseModel):
    url: str


class LegalSection(BaseModel):
    heading: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)


class LegalDocument(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    effective: str = Field(min_length=1, max_length=200)
    intro: str = Field(min_length=1, max_length=2000)
    sections: list[LegalSection]


def _download_config(session: SessionDep) -> TerminalDownloadConfig:
    rows = session.exec(
        select(SystemSetting).where(
            SystemSetting.tenant_id == DEFAULT_TENANT_ID,
            SystemSetting.group == "homepage",
            SystemSetting.key.in_(
                [f"{SETTING_PREFIX}downloads.{key}" for key in ("version", "arm64Key", "arm32Key", "windows64Key", "ubuntuArm64Key")]
            ),
        )
    ).all()
    values = {row.key.removeprefix(f"{SETTING_PREFIX}downloads."): row.value for row in rows}
    return TerminalDownloadConfig(
        version=values.get("version", ""),
        arm64Key=values.get("arm64Key", ""),
        arm32Key=values.get("arm32Key", ""),
        windows64Key=values.get("windows64Key", ""),
        ubuntuArm64Key=values.get("ubuntuArm64Key", ""),
    )


def _legal_document(session: SessionDep, slug: str) -> LegalDocument:
    if slug not in LEGAL_DEFAULTS:
        raise HTTPException(status_code=404, detail="Legal page not found")
    document = deepcopy(LEGAL_DEFAULTS[slug])
    prefix = f"{SETTING_PREFIX}legal.{slug}."
    rows = session.exec(
        select(SystemSetting).where(
            SystemSetting.tenant_id == DEFAULT_TENANT_ID,
            SystemSetting.group == "homepage",
            SystemSetting.key.like(f"{prefix}%"),
        )
    ).all()
    for row in rows:
        field = row.key.removeprefix(prefix)
        if field in {"title", "effective", "intro"}:
            document[field] = row.value
        elif field.startswith("section."):
            _, index, part = field.split(".", 2)
            if index.isdigit() and int(index) < len(document["sections"]) and part in {"heading", "body"}:
                document["sections"][int(index)][part] = row.value
    return LegalDocument.model_validate(document)


def _content(session: SessionDep) -> HomepagePublic:
    content = deepcopy(DEFAULTS)
    rows = session.exec(
        select(SystemSetting).where(
            SystemSetting.tenant_id == DEFAULT_TENANT_ID,
            SystemSetting.group == "homepage",
        )
    ).all()
    for row in rows:
        name = row.key.removeprefix(SETTING_PREFIX)
        if name.startswith("media."):
            field = name.removeprefix("media.")
            if field in content["media"]:
                content["media"][field] = row.value
        else:
            locale, separator, field = name.partition(".")
            if separator and field in content["locales"].get(locale, {}):
                content["locales"][locale][field] = row.value
    return HomepagePublic.model_validate(content)


@router.get("/public", response_model=HomepagePublic)
def read_homepage(session: SessionDep) -> HomepagePublic:
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        cache_key = redis_cache.build_versioned_key(
            CacheNamespace.PUBLIC_SETTINGS, str(DEFAULT_TENANT_ID), "homepage"
        )
        cached = redis_cache.get_json(cache_key)
        if cached is not None:
            return HomepagePublic.model_validate(cached)
        content = _content(session)
        redis_cache.set_json(cache_key, content.model_dump())
        return content


def _save(session: SessionDep, key: str, value: str) -> None:
    setting_key = f"{SETTING_PREFIX}{key}"
    row = session.exec(
        select(SystemSetting).where(
            SystemSetting.tenant_id == DEFAULT_TENANT_ID,
            SystemSetting.key == setting_key,
        )
    ).first()
    if row is None:
        row = SystemSetting(
            tenant_id=DEFAULT_TENANT_ID,
            key=setting_key,
            name=setting_key,
            group="homepage",
            value=value,
            value_type="string",
            is_public=False,
        )
    else:
        row.value = value
        row.updated_at = get_datetime_utc()
    session.add(row)


@router.put(
    "/locales/{locale}",
    dependencies=[
        Depends(get_current_active_superuser),
        Depends(require_permission("system:setting:update")),
    ],
    response_model=HomepagePublic,
)
def update_homepage_locale(
    locale: str,
    body: HomepageLocaleUpdate,
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,  # noqa: ARG001
) -> HomepagePublic:
    if locale not in DEFAULTS["locales"]:
        raise HTTPException(status_code=404, detail="Unsupported locale")
    allowed = DEFAULTS["locales"][locale]
    if set(body.values) != set(allowed):
        raise HTTPException(status_code=422, detail="Homepage fields do not match")
    for key, value in body.values.items():
        if not value.strip() or len(value) > 2000:
            raise HTTPException(status_code=422, detail=f"Invalid homepage field: {key}")
        _save(session, f"{locale}.{key}", value.strip())
    session.commit()
    redis_cache.bump_namespace(CacheNamespace.PUBLIC_SETTINGS)
    return _content(session)


@router.put(
    "/media",
    dependencies=[
        Depends(get_current_active_superuser),
        Depends(require_permission("system:setting:update")),
    ],
    response_model=HomepagePublic,
)
def update_homepage_media(
    body: HomepageMediaUpdate,
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,  # noqa: ARG001
) -> HomepagePublic:
    for key, value in body.model_dump().items():
        value = value.strip()
        parsed = urlsplit(value)
        if not (
            (parsed.scheme == "https" and parsed.netloc)
            or (value.startswith("/") and not value.startswith("//"))
        ):
            raise HTTPException(status_code=422, detail=f"Invalid image URL: {key}")
        _save(session, f"media.{key}", value)
    session.commit()
    redis_cache.bump_namespace(CacheNamespace.PUBLIC_SETTINGS)
    return _content(session)


@router.get("/downloads/public", response_model=TerminalDownloadPublic)
def read_terminal_downloads(session: SessionDep) -> TerminalDownloadPublic:
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        config = _download_config(session)
        return TerminalDownloadPublic(
            version=config.version,
            arm64Available=bool(config.arm64Key),
            arm32Available=bool(config.arm32Key),
            windows64Available=bool(config.windows64Key),
            ubuntuArm64Available=bool(config.ubuntuArm64Key),
        )


@router.get(
    "/downloads/config",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=TerminalDownloadConfig,
)
def read_terminal_download_config(
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,  # noqa: ARG001
) -> TerminalDownloadConfig:
    return _download_config(session)


@router.put(
    "/downloads/config",
    dependencies=[
        Depends(get_current_active_superuser),
        Depends(require_permission("system:setting:update")),
    ],
    response_model=TerminalDownloadConfig,
)
def update_terminal_download_config(
    body: TerminalDownloadConfig,
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,  # noqa: ARG001
) -> TerminalDownloadConfig:
    version = body.version.strip()
    if not re.fullmatch(r"[A-Za-z0-9.+_-]{1,32}", version):
        raise HTTPException(status_code=422, detail="Invalid terminal version")
    extensions = {"arm64Key": ".apk", "arm32Key": ".apk", "windows64Key": ".exe", "ubuntuArm64Key": ".deb"}
    for field, extension in extensions.items():
        key = getattr(body, field).strip()
        if key and (
            key.startswith("/")
            or ".." in Path(key).parts
            or "?" in key
            or "#" in key
            or "://" in key
            or not key.lower().endswith(extension)
        ):
            raise HTTPException(status_code=422, detail=f"Invalid OSS object key: {field}")
        _save(session, f"downloads.{field}", key)
    _save(session, "downloads.version", version)
    session.commit()
    return _download_config(session)


@router.post("/downloads/{architecture}", deprecated=True)
def retired_terminal_download(architecture: str):  # noqa: ARG001
    raise HTTPException(status_code=410, detail="Please refresh the download page")


@router.post("/download-links/{architecture}", response_model=TerminalDownloadLink)
def download_terminal(
    architecture: str,
    body: TerminalDownloadRequest,
    session: SessionDep,
    response: Response,
):
    packages = {
        "arm64": "arm64Key", "arm32": "arm32Key",
        "windows64": "windows64Key", "ubuntuArm64": "ubuntuArm64Key",
    }
    if architecture not in packages:
        raise HTTPException(status_code=404, detail="Unsupported terminal architecture")
    field = packages[architecture]
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        config = _download_config(session)
        key = getattr(config, field)
        if not key:
            raise HTTPException(status_code=404, detail="Terminal package is not available")
        if not validate_slider_captcha_verification(body.captchaVerification):
            raise HTTPException(status_code=403, detail="Slider captcha is invalid or expired")
        url = get_terminal_download_url(
            storage_path=key,
        )
        response.headers["Cache-Control"] = "no-store"
        return TerminalDownloadLink(url=url)


@router.get("/legal/{slug}", response_model=LegalDocument)
def read_legal_document(slug: str, session: SessionDep) -> LegalDocument:
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        return _legal_document(session, slug)


@router.put(
    "/legal/{slug}",
    dependencies=[
        Depends(get_current_active_superuser),
        Depends(require_permission("system:setting:update")),
    ],
    response_model=LegalDocument,
)
def update_legal_document(
    slug: str,
    body: LegalDocument,
    session: SessionDep,
    tenant_context: PlatformConfigurationTenant,  # noqa: ARG001
) -> LegalDocument:
    if slug not in LEGAL_DEFAULTS:
        raise HTTPException(status_code=404, detail="Legal page not found")
    if len(body.sections) != len(LEGAL_DEFAULTS[slug]["sections"]):
        raise HTTPException(status_code=422, detail="Legal sections do not match")
    for field in ("title", "effective", "intro"):
        _save(session, f"legal.{slug}.{field}", getattr(body, field).strip())
    for index, section in enumerate(body.sections):
        _save(session, f"legal.{slug}.section.{index}.heading", section.heading.strip())
        _save(session, f"legal.{slug}.section.{index}.body", section.body.strip())
    session.commit()
    return _legal_document(session, slug)
