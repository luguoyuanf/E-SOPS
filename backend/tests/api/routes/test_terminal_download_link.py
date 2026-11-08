from contextlib import nullcontext
from urllib.parse import urlsplit

import pytest
from fastapi import HTTPException, Response

from app.api.routes import homepage
from app.core.config import settings
from app.platform.infra import storage_impl


def test_fixed_r2_link_has_no_signature_or_expiry(monkeypatch):
    monkeypatch.setattr(
        settings, "TERMINAL_DOWNLOAD_ORIGIN", "https://download.esops.cc"
    )
    url = storage_impl.get_terminal_download_url(storage_path="releases/app.apk")
    parsed = urlsplit(url)
    assert parsed.hostname == "download.esops.cc"
    assert parsed.path == "/releases/app.apk"
    assert not parsed.query
    assert (
        storage_impl.get_terminal_download_url(storage_path="releases/app.apk") == url
    )


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "http://download.example.com",
        "https://example.com/path",
        "https://example.com/?x=1",
    ],
)
def test_missing_or_invalid_domain_does_not_fall_back_to_proxy(monkeypatch, origin):
    monkeypatch.setattr(settings, "TERMINAL_DOWNLOAD_ORIGIN", origin)
    with pytest.raises(HTTPException) as error:
        storage_impl.get_terminal_download_url(storage_path="app.apk")
    assert error.value.status_code == 503


def test_link_requires_captcha_and_is_not_cacheable(monkeypatch):
    monkeypatch.setattr(
        homepage, "PlatformTenantUnitOfWork", lambda *a, **kw: nullcontext()
    )
    monkeypatch.setattr(
        homepage,
        "_download_config",
        lambda s: homepage.TerminalDownloadConfig(
            version="1",
            arm64Key="releases/app.apk",
            arm32Key="",
        ),
    )
    calls = []
    monkeypatch.setattr(
        homepage,
        "get_terminal_download_url",
        lambda **kw: calls.append(kw) or "https://download.esops.cc/app.apk",
    )
    monkeypatch.setattr(
        homepage, "validate_slider_captcha_verification", lambda proof: proof == "valid"
    )
    with pytest.raises(HTTPException) as error:
        homepage.download_terminal(
            "arm64",
            homepage.TerminalDownloadRequest(captchaVerification="invalid"),
            None,
            Response(),
        )
    assert error.value.status_code == 403
    assert not calls
    response = Response()
    result = homepage.download_terminal(
        "arm64",
        homepage.TerminalDownloadRequest(captchaVerification="valid"),
        None,
        response,
    )
    assert result.url == "https://download.esops.cc/app.apk"
    assert response.headers["cache-control"] == "no-store"
    assert calls[0]["storage_path"] == "releases/app.apk"
    with pytest.raises(HTTPException) as error:
        homepage.retired_terminal_download("arm64")
    assert error.value.status_code == 410
