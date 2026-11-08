"""OSS S3-compatibility configuration and signing without network/real credentials."""

from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.platform.infra.file_models import FileStorageChannel
from app.platform.infra.storage_impl import _ensure_s3_bucket, _get_s3_client


def oss_channel(**overrides):
    return FileStorageChannel(
        **{
            "name": "OSS test",
            "code": "oss-test",
            "provider": "oss",
            "endpoint_url": "https://oss-cn-hangzhou.aliyuncs.com",
            "bucket": "example-test-bucket",
            "access_key_id": "test-access-key",
            "secret_access_key": "test-secret-not-a-real-key",
            **overrides,
        }
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://oss-cn-hangzhou.aliyuncs.com",
        "https://s3.oss-cn-hangzhou.aliyuncs.com",
    ],
)
def test_oss_client_and_presigning(endpoint):
    client = _get_s3_client(oss_channel(endpoint_url=endpoint, addressing_style="path"))
    config = client.meta.config
    assert config.signature_version == "s3"
    assert config.s3["addressing_style"] == "virtual"
    assert config.request_checksum_calculation == "when_required"
    assert config.response_checksum_validation == "when_required"
    assert client.meta.endpoint_url == "https://s3.oss-cn-hangzhou.aliyuncs.com"
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": "example-test-bucket", "Key": "tenants/test/说明.pdf"},
        ExpiresIn=300,
    )
    parsed = urlsplit(url)
    assert parsed.hostname == "example-test-bucket.s3.oss-cn-hangzhou.aliyuncs.com"
    assert parsed.path.startswith("/tenants/test/")
    assert {"AWSAccessKeyId", "Signature", "Expires"} <= parse_qs(parsed.query).keys()
    client.close()


@pytest.mark.parametrize(
    "overrides,status",
    [
        ({"endpoint_url": None}, 503),
        ({"access_key_id": None}, 503),
        ({"secret_access_key": None}, 503),
        ({"endpoint_url": "http://oss-cn-hangzhou.aliyuncs.com"}, 400),
        ({"endpoint_url": "https://[broken"}, 400),
        ({"endpoint_url": "https://oss-cn-hangzhou.aliyuncs.com/bucket"}, 400),
        ({"endpoint_url": "https://oss-cn-hangzhou.aliyuncs.com?key=value"}, 400),
    ],
)
def test_invalid_oss_configuration_fails_without_network(overrides, status):
    with pytest.raises(HTTPException) as error:
        _get_s3_client(oss_channel(**overrides))
    assert error.value.status_code == status


def test_oss_bucket_failure_does_not_create_bucket():
    class DeniedBucket:
        def head_bucket(self, **_):
            raise ClientError({"Error": {"Code": "403"}}, "HeadBucket")

    with pytest.raises(HTTPException) as error:
        _ensure_s3_bucket(DeniedBucket(), oss_channel(auto_create_bucket=True))
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "path,content_type",
    [
        ("uploads/tenants/test/app.apk", None),
        ("uploads/tenants/test/app.IPA", None),
        ("uploads/tenants/test/package.bin", "application/vnd.android.package-archive"),
    ],
)
def test_oss_installers_use_authenticated_download(path, content_type):
    from app.platform.infra.storage_impl import get_presigned_download_url

    assert (
        get_presigned_download_url(
            storage_provider="oss",
            storage_path=path,
            content_type=content_type,
            fallback_url="/api/v1/files/test/download",
        )
        == "/api/v1/files/test/download"
    )
