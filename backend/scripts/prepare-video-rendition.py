"""Generate a playback copy for one existing video; never alter SOP snapshots.

Run inside the configured backend environment. Without --apply this only validates
scope and reports the existing rendition. Requires an active tenant administrator.
"""
import argparse
import json
import sys
import uuid
from types import SimpleNamespace

from sqlmodel import Session

from app.core.database import engine
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.operation_media import (
    prepare_video_rendition,
    resolve_operation_attachment,
)
from app.platform.tenant_uow import PlatformTenantUnitOfWork
from app.platform.web_api import get_file_asset_directory, get_user_directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=uuid.UUID, required=True)
    parser.add_argument("--file-id", type=uuid.UUID, required=True)
    parser.add_argument("--administrator-id", type=uuid.UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rebuild", action="store_true", help="生成成功后切换播放副本，保留旧副本与原件")
    args = parser.parse_args()
    with (Session(engine) as session,
          PlatformTenantUnitOfWork(session, args.tenant_id),
          EsopTenantUnitOfWork(session, args.tenant_id) as uow):
        users = get_user_directory(session)
        users.validate_active_users([args.administrator_id])
        if not users.is_tenant_administrator(args.administrator_id, args.tenant_id):
            parser.error("指定账号不是该租户的启用管理员")
        files = get_file_asset_directory(session)
        asset = files.get_accessible_file(tenant_id=args.tenant_id, file_id=args.file_id)
        if asset is None or asset.original_name.rsplit(".", 1)[-1].lower() not in {"mp4", "webm", "mov"}:
            parser.error("该租户内不存在指定视频原件")
        if args.apply:
            result = prepare_video_rendition(uow, SimpleNamespace(id=args.administrator_id), files, args.file_id, rebuild=args.rebuild)
        else:
            result = resolve_operation_attachment(uow, files, asset)
        sys.stdout.write(json.dumps({"applied": args.apply, "original_file_id": str(result.file_id),
                          "display_file_id": str(result.display_file_id) if result.display_file_id else None,
                          "original_bytes": result.size}) + "\n")


if __name__ == "__main__":
    main()
