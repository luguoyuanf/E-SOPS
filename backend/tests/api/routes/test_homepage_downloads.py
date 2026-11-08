from contextlib import nullcontext

import pytest
from fastapi import HTTPException, Response

from app.api.routes import homepage


@pytest.fixture
def download_config(monkeypatch):
    config = homepage.TerminalDownloadConfig(
        version="0.1.93",
        arm64Key="releases/android-arm64.apk",
        arm32Key="releases/android-arm32.apk",
        windows64Key="releases/windows-x64.exe",
        ubuntuArm64Key="releases/ubuntu-arm64.deb",
    )
    monkeypatch.setattr(
        homepage, "PlatformTenantUnitOfWork", lambda *args, **kwargs: nullcontext()
    )
    monkeypatch.setattr(homepage, "_download_config", lambda session: config)
    monkeypatch.setattr(
        homepage, "validate_slider_captcha_verification", lambda token: True
    )
    monkeypatch.setattr(
        homepage,
        "get_terminal_download_url",
        lambda **kwargs: "https://download.esops.cc/" + kwargs["storage_path"],
    )
    return config


def test_public_downloads_only_advertise_configured_packages(download_config):
    result = homepage.read_terminal_downloads(object())
    assert result.windows64Available is True
    assert result.ubuntuArm64Available is True
    download_config.windows64Key = ""
    assert homepage.read_terminal_downloads(object()).windows64Available is False


@pytest.mark.parametrize(
    ("architecture", "key"),
    [
        ("arm32", "releases/android-arm32.apk"),
        ("arm64", "releases/android-arm64.apk"),
        ("windows64", "releases/windows-x64.exe"),
        ("ubuntuArm64", "releases/ubuntu-arm64.deb"),
    ],
)
@pytest.mark.usefixtures("download_config")
def test_download_uses_matching_package(architecture, key):
    result = homepage.download_terminal(
        architecture,
        homepage.TerminalDownloadRequest(captchaVerification="valid"),
        object(),
        Response(),
    )
    assert result.url == f"https://download.esops.cc/{key}"


@pytest.mark.usefixtures("download_config")
def test_windows_x86_is_not_supported():
    with pytest.raises(HTTPException) as error:
        homepage.download_terminal(
            "windows32",
            homepage.TerminalDownloadRequest(captchaVerification="valid"),
            object(),
            Response(),
        )
    assert error.value.status_code == 404
