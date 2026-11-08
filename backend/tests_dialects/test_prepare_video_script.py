"""Maintenance must use real Platform + ESOP scope, not mocked user adapters."""
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.modules.esop import operation_media
from app.modules.esop.infrastructure.models import OperationFileRendition
from app.platform.core.authorization_models import Role, UserRole
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import TenantMembership
from app.platform.infra import file_directory
from app.platform.infra.file_models import FileAsset
from app.platform.tenant_uow import PlatformTenantUnitOfWork


def test_script_dry_run_with_real_scoped_admin_and_file_queries(monkeypatch, capsys):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in (
        User, Role, UserRole, TenantMembership, FileAsset, OperationFileRendition)])
    tenant, admin, role, original = (uuid.uuid4() for _ in range(4))
    with Session(engine) as session, PlatformTenantUnitOfWork(session, tenant):
        session.add_all([
            User(id=admin, username="video-maintenance-admin", hashed_password="unused", is_active=True),
            Role(id=role, tenant_id=tenant, code="admin", name="管理员", is_system=True, is_active=True),
            UserRole(user_id=admin, role_id=role, tenant_id=tenant),
            TenantMembership(user_id=admin, tenant_id=tenant, is_active=True),
            FileAsset(id=original, tenant_id=tenant, original_name="source.mp4", stored_name="source.mp4",
                      storage_path="unused", content_type="video/mp4", size=123, sha256="0" * 64,
                      uploader_id=admin),
        ])
        session.commit()
    spec = importlib.util.spec_from_file_location("prepare_video_script", Path(__file__).parents[1] / "scripts/prepare-video-rendition.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(sys, "argv", ["prepare-video-rendition.py", "--tenant-id", str(tenant),
                                    "--file-id", str(original), "--administrator-id", str(admin)])
    module.main()
    result = json.loads(capsys.readouterr().out)
    assert result == {"applied": False, "original_file_id": str(original), "display_file_id": None, "original_bytes": 123}

    # Exercise the real prepare + Platform upload path while replacing only external storage/ffmpeg.
    saved = []
    def save_upload(file, *, session, tenant_id):
        assert tenant_id == tenant
        assert session.info["platform_tenant_id"] == session.info["esop_tenant_id"] == tenant
        saved.append(file.filename)
        return SimpleNamespace(original_name=file.filename, stored_name="playback.mp4", content_type="video/mp4",
                               extension="mp4", size=20, sha256="1" * 64, storage_provider="oss", storage_path="unused")
    monkeypatch.setattr(file_directory, "save_upload_file", save_upload)
    monkeypatch.setattr(file_directory, "read_stored_file_bytes", lambda **_: b"original bytes")
    monkeypatch.setattr(file_directory.direct_files, "lock_file_quota", lambda *_: None)
    monkeypatch.setattr(file_directory, "ensure_file_quota", lambda **_: None)
    monkeypatch.setattr(operation_media, "convert_video", lambda *_: (b"compatible bytes", []))
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--apply"])
    module.main()
    applied = json.loads(capsys.readouterr().out)
    assert applied["applied"] and applied["display_file_id"] != str(original)
    module.main()
    repeated = json.loads(capsys.readouterr().out)
    assert repeated == applied and len(saved) == 1

    monkeypatch.setattr(sys, "argv", [*sys.argv, "--rebuild"])
    module.main()
    rebuilt = json.loads(capsys.readouterr().out)
    assert rebuilt["display_file_id"] != applied["display_file_id"] and len(saved) == 2
    with Session(engine) as session, PlatformTenantUnitOfWork(session, tenant):
        # Neither the source nor the previous playback copy is removed by the mapping swap.
        assert session.get(FileAsset, original).sha256 == "0" * 64
        assert session.get(FileAsset, uuid.UUID(applied["display_file_id"])) is not None
        assert session.get(FileAsset, uuid.UUID(rebuilt["display_file_id"])) is not None

    monkeypatch.setattr(operation_media, "convert_video", lambda *_: (_ for _ in ()).throw(HTTPException(422, "失败")))
    with pytest.raises(HTTPException):
        module.main()
    monkeypatch.setattr(sys, "argv", sys.argv[:-1])
    module.main()
    assert json.loads(capsys.readouterr().out)["display_file_id"] == rebuilt["display_file_id"]

    # Another tenant cannot use that admin's role or access the original video.
    monkeypatch.setattr(sys, "argv", ["prepare-video-rendition.py", "--tenant-id", str(uuid.uuid4()),
                                    "--file-id", str(original), "--administrator-id", str(admin)])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
