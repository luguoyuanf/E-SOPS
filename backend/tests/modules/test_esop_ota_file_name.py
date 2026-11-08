import uuid
from unittest.mock import patch

from app.modules.esop.infrastructure.models import OtaPackage
from app.modules.esop.ota_routes import _package_public
from app.platform.public_api.files import FileAssetSummary


def test_ota_package_reads_original_file_name_from_owning_tenant():
    package = OtaPackage(
        channel_id=uuid.uuid4(), hardware_model_id=uuid.uuid4(),
        file_owner_tenant_id=uuid.uuid4(), file_id=uuid.uuid4(),
        file_size=123, version="1.0.0", checksum_sha256="a" * 64,
    )
    session = object()
    with patch("app.modules.esop.ota_routes.get_authorized_file", return_value=FileAssetSummary(
        id=package.file_id, original_name="终端安装包.apk", size=123, sha256="a" * 64,
    )) as lookup:
        assert _package_public(package, session).file_name == "终端安装包.apk"
        lookup.assert_called_once_with(
            session=session, tenant_id=package.file_owner_tenant_id, file_id=package.file_id,
        )
