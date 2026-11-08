import base64
import json
from io import BytesIO

import pytest
from PIL import Image

from app.api.routes.login import (
    _aes_encrypt,
    _build_slider_images,
    _slider_get,
    check_slider_captcha,
    get_slider_captcha,
    validate_slider_captcha_verification,
)
from app.core.config import settings


@pytest.fixture(autouse=True)
def enable_slider_captcha(
    disable_slider_captcha: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert disable_slider_captcha is None
    monkeypatch.setattr(settings, "LOGIN_SLIDER_CAPTCHA_ENABLED", True)


def test_slider_captcha_protocol_round_trip() -> None:
    response = get_slider_captcha({"captchaType": "blockPuzzle"})
    assert response["repCode"] == "0000"
    data = response["repData"]
    assert data is not None

    original = Image.open(
        BytesIO(base64.b64decode(data["originalImageBase64"]))
    )
    assert original.size == (400, 200)

    payload = _slider_get(data["token"])
    assert payload is not None
    point = json.dumps({"x": payload["expected_x"], "y": 5})
    checked = check_slider_captcha(
        {
            "captchaType": "blockPuzzle",
            "pointJson": _aes_encrypt(point, data["secretKey"]),
            "token": data["token"],
        }
    )
    assert checked["repCode"] == "0000"

    verification = _aes_encrypt(
        f'{data["token"]}---{point}', data["secretKey"]
    )
    assert validate_slider_captcha_verification(verification)
    assert not validate_slider_captcha_verification(verification)


def test_slider_captcha_rejects_wrong_position() -> None:
    response = get_slider_captcha({"captchaType": "blockPuzzle"})
    data = response["repData"]
    assert data is not None
    checked = check_slider_captcha(
        {
            "captchaType": "blockPuzzle",
            "pointJson": _aes_encrypt('{"x":0,"y":5}', data["secretKey"]),
            "token": data["token"],
        }
    )
    assert checked["repCode"] != "0000"


@pytest.mark.parametrize("edition", ["esop", "base"])
def test_captcha_branding_preserves_image_and_piece_geometry(monkeypatch, edition):
    monkeypatch.setattr(settings, "APP_EDITION", edition)
    background, block = _build_slider_images(180)
    image = Image.open(BytesIO(base64.b64decode(background)))
    piece = Image.open(BytesIO(base64.b64decode(block)))
    assert image.size == (400, 200)
    assert piece.size == (52, 52)
    assert piece.mode == "RGBA"
    assert piece.getchannel("A").getextrema() == (0, 255)
    red, green, blue, _alpha = image.getpixel((399, 199))
    if edition == "esop":
        assert green > red >= 200 and blue >= 220
    else:
        assert blue > green > red
