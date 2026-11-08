"""Channel recovery downloads: run against the configured dedicated online MySQL."""
import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session, create_engine

from app.core.config import settings
from app.modules.esop.infrastructure.models import (
    Channel,
    ChannelAdmin,
    ChannelCustomerTenant,
    HardwareModel,
    OtaPackage,
)
from app.modules.esop.ota_routes import (
    _admin,
    download_installation_package,
    list_channels,
    list_hardware_models,
    list_ota_packages,
)
from app.platform.web_api import Principal, TenantContext


def test_channel_recovery_scope(monkeypatch):
    assert settings.MYSQL_DB == 'esop_fva_test_20261024'
    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    with Session(engine) as session:
        try:
            ca, cb = uuid.uuid4(), uuid.uuid4()
            customer, outsider, owner = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            channel_user, normal_user = uuid.uuid4(), uuid.uuid4()
            root = Principal(id=uuid.uuid4(), is_superuser=True)
            agent = Principal(id=channel_user, is_superuser=False)
            user = Principal(id=normal_user, is_superuser=False)
            def ctx(tid):
                return TenantContext(tenant_id=tid, tenant_code='ota-test', user_id=normal_user)
            for cid in (ca, cb):
                session.add(Channel(id=cid, code=f'ota-{cid.hex[:12]}', name='OTA regression'))
            session.add(ChannelAdmin(channel_id=ca, user_id=channel_user))
            session.add(ChannelCustomerTenant(channel_id=ca, tenant_id=customer, created_by=root.id))
            ma, mb = uuid.uuid4(), uuid.uuid4()
            for mid, cid in ((ma, ca), (mb, cb)):
                session.add(HardwareModel(id=mid, channel_id=cid, code='A133', name='A133', abi='armeabi-v7a'))
            packages = []
            for mid, cid, status in ((ma, ca, 'published'), (ma, ca, 'draft'), (mb, cb, 'published')):
                row = OtaPackage(channel_id=cid, hardware_model_id=mid, file_owner_tenant_id=owner, file_id=uuid.uuid4(), file_size=123, version=uuid.uuid4().hex, checksum_sha256='a'*64, status=status)
                session.add(row)
                packages.append(row)
            session.flush()
            assert [p.id for p in list_ota_packages(session, user, ctx(customer))['items']] == [packages[0].id]
            assert [p.id for p in list_ota_packages(session, agent, ctx(outsider))['items']] == [packages[0].id]
            assert list_ota_packages(session, user, ctx(outsider))['items'] == []
            assert [c.id for c in list_channels(session, user, ctx(customer))['items']] == [ca]
            assert [h.id for h in list_hardware_models(session, user, ctx(customer))['items']] == [ma]
            assert {p.id for p in packages} <= {p.id for p in list_ota_packages(session, root, ctx(owner))['items']}
            calls = []
            monkeypatch.setattr('app.modules.esop.ota_routes.download_authorized_file', lambda **kw: calls.append(kw) or 'download')
            assert download_installation_package(session, user, ctx(customer), packages[0].id) == 'download'
            assert calls[-1]['tenant_id'] == owner
            assert download_installation_package(session, agent, ctx(outsider), packages[0].id) == 'download'
            for package_id in (packages[1].id, packages[2].id, uuid.uuid4()):
                with pytest.raises(HTTPException) as error:
                    download_installation_package(session, user, ctx(customer), package_id)
                assert error.value.status_code == 404
            with pytest.raises(HTTPException) as error:
                download_installation_package(session, user, ctx(outsider), packages[0].id)
            assert error.value.status_code == 404
            with pytest.raises(HTTPException) as error:
                _admin(user)
            assert error.value.status_code == 403
        finally:
            session.rollback()
    engine.dispose()


def test_download_reads_owner_file_and_restores_caller_scope(monkeypatch, tmp_path):
    from sqlmodel import select

    from app.platform.core.tenancy_models import Tenant
    from app.platform.infra.file_models import FileAsset
    from app.platform.tenant_uow import PlatformTenantUnitOfWork
    from app.platform.web_api import download_authorized_file

    assert settings.MYSQL_DB == 'esop_fva_test_20261024'
    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    monkeypatch.setattr('app.platform.infra.storage_impl.get_upload_root', lambda: tmp_path)
    content = b'ota-download-test-content'
    (tmp_path / 'recovery.exe').write_bytes(content)
    with Session(engine) as session:
        owner = session.exec(select(Tenant.id)).first()
        caller = uuid.uuid4()
        file_id = uuid.uuid4()
        try:
            with PlatformTenantUnitOfWork(session, owner):
                session.add(FileAsset(id=file_id, tenant_id=owner, original_name='恢复安装.exe', stored_name='recovery.exe', storage_path='recovery.exe', content_type='application/octet-stream', size=len(content), sha256='a'*64))
                session.flush()
            with PlatformTenantUnitOfWork(session, caller):
                assert session.get(FileAsset, file_id) is None
                response = download_authorized_file(session=session, tenant_id=owner, file_id=file_id)
                assert response.path.read_bytes() == content
                assert response.headers['content-disposition'].startswith('attachment; filename*=UTF-8')
                assert '.exe' in response.headers['content-disposition']
                assert session.info['platform_tenant_id'] == caller
                assert session.get(FileAsset, file_id) is None
        finally:
            session.rollback()
    engine.dispose()


def test_cloud_download_resolves_storage_before_scope_exits(monkeypatch):
    import io
    from types import SimpleNamespace

    from app.platform.infra import storage_impl

    scope = {'active': True}
    body = io.BytesIO(b'recovery-apk')

    def channel(*_args):
        assert scope['active']
        return SimpleNamespace(bucket='test')

    monkeypatch.setattr(storage_impl, 'get_default_storage_channel', channel)
    monkeypatch.setattr(storage_impl, '_get_s3_client', lambda _: SimpleNamespace(get_object=lambda **kw: {'Body': body}))
    chunks = storage_impl._stream_s3_object('recovery.apk')
    scope['active'] = False
    assert b''.join(chunks) == b'recovery-apk'
    assert body.closed
