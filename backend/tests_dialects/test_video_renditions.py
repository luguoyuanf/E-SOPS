"""Compatible playback remains a derivative of an authorized, immutable source."""
import copy
import json
import shutil
import subprocess
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from PIL import Image, ImageChops, ImageStat
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.modules.esop import operation_media as media
from app.modules.esop import terminal_routes as routes
from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import (
    ALL_MODELS,
    OperationFileRendition,
    SopDocument,
    Terminal,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork


def test_video_upload_returns_before_conversion(monkeypatch):
    import io

    original = uuid.uuid4()
    files = Mock()
    files.get_accessible_file.return_value = SimpleNamespace(size=3, original_name="bad.mp4")
    files.read_file_bytes.return_value = b"bad"
    monkeypatch.setattr(media, "upload_authorized_file", Mock(return_value=original))
    convert = Mock(side_effect=HTTPException(422, "视频转换失败"))
    monkeypatch.setattr(media, "convert_video", convert)
    monkeypatch.setattr(media, "resolve_operation_attachment", lambda _uow, _files, _asset: media.OperationAttachment(file_id=original, name="bad.mp4", kind="video", size=3))
    uow, principal = SimpleNamespace(tenant_id=uuid.uuid4(), session=Mock()), SimpleNamespace(id=uuid.uuid4())
    result = media.upload_operation_media(uow, principal, files, SimpleNamespace(filename="bad.mp4", file=io.BytesIO(b"bad")))
    assert result.file_id == original
    assert uow.session.add.call_args.args[0].status == "queued"
    convert.assert_not_called()
    files.discard_upload.assert_not_called()


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires ffmpeg tools")
def test_real_conversion_preserves_input_and_outputs_seekable_baseline_aac(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "0.3", "-c:v", "libx264",
                    "-profile:v", "high", "-c:a", "aac", str(source)], check=True)
    original = source.read_bytes()
    output, pages = media.convert_video(original, "mp4")
    assert source.read_bytes() == original and pages == []
    target = tmp_path / "playback.mp4"
    target.write_bytes(output)
    streams = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(target)]))["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    audio = next(stream for stream in streams if stream["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (768, 1280, "25/1")
    assert "Baseline" in video["profile"] and video["pix_fmt"] == "yuv420p" and video["has_b_frames"] == 0
    assert audio["codec_name"] == "aac"
    assert output.index(b"moov") < output.index(b"mdat")
    def frame(path, size):
        pixels = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1",
                                          "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
        return Image.frombytes("RGB", size, pixels)
    source_frame, playback_frame = frame(source, (720, 1280)), frame(target, (768, 1280))
    # All 720 source columns remain at original scale, centered between 24px black margins.
    content = playback_frame.crop((24, 0, 744, 1280))
    assert max(ImageStat.Stat(ImageChops.difference(source_frame, content)).mean) < 15
    assert max(ImageStat.Stat(playback_frame.crop((0, 0, 22, 1280))).mean) < 2
    assert max(ImageStat.Stat(playback_frame.crop((746, 0, 768, 1280))).mean) < 2


def test_derived_video_is_authorized_only_through_approved_source(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None}})
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in ALL_MODELS])
    tenant, other, product, operation, station, actor = (uuid.uuid4() for _ in range(6))
    original, playback, unapproved, denied_playback, foreign_playback = (uuid.uuid4() for _ in range(5))
    snapshot = [{"file_id": str(original), "name": "原视频.mov", "kind": "video", "size": 100}]
    before = copy.deepcopy(snapshot)
    assets = {fid: SimpleNamespace(original_name="原视频.mov" if fid in {original, unapproved} else "播放副本.mp4",
                                  content_type="video/mp4", size=80)
              for fid in (original, playback, unapproved, denied_playback)}
    files = SimpleNamespace(get_accessible_file=lambda *, tenant_id, file_id: assets.get(file_id) if tenant_id == tenant else None)
    monkeypatch.setattr(routes, "get_file_asset_directory", lambda _: files)
    monkeypatch.setattr(routes, "preview_authorized_file", lambda **kwargs: kwargs["file_id"])
    monkeypatch.setattr(routes, "product_directory_for_tenant", lambda *_: SimpleNamespace(tree=lambda: ([], [])))
    monkeypatch.setattr(routes, "current_assignment", lambda _session, _release, assignment: assignment)
    with Session(engine) as session:
        with EsopTenantUnitOfWork(session, tenant):
            terminal = Terminal(tenant_id=tenant, device_code="playback-check", station_id=station)
            sop = SopDocument(tenant_id=tenant, family_id=uuid.uuid4(), product_id=product, operation_id=operation,
                              status="approved", title="视频", created_by=actor,
                              pages=[{"file_id": str(original), "sort": 0}])
            session.add_all([terminal, sop,
                             OperationFileRendition(tenant_id=tenant, original_file_id=original, display_file_id=playback),
                             OperationFileRendition(tenant_id=tenant, original_file_id=unapproved, display_file_id=denied_playback)])
            session.commit()
            terminal_id, sop_id = terminal.id, sop.id
        with EsopTenantUnitOfWork(session, other):
            session.add(OperationFileRendition(tenant_id=other, original_file_id=original, display_file_id=foreign_playback))
            session.commit()
        assignment = {"sop_id": str(sop_id), "_attachments": snapshot}
        monkeypatch.setattr(routes, "_active_tasks", lambda *_: [(SimpleNamespace(), assignment)])
        device = DeviceIdentity(tenant, terminal_id)
        assert routes.terminal_file(session, device, original) == original
        assert routes.terminal_file(session, device, playback) == playback
        for denied in (denied_playback, foreign_playback):
            with pytest.raises(HTTPException) as error:
                routes.terminal_file(session, device, denied)
            assert error.value.status_code == 404
        with EsopTenantUnitOfWork(session, tenant):
            payload, _ = routes._attachment_payload(assignment, session.get(SopDocument, sop_id), files, tenant, session)
        assert payload[0]["id"] == str(playback)
        assert payload[0]["url"].endswith(str(playback)) and payload[0]["mimeType"] == "video/mp4"
        with EsopTenantUnitOfWork(session, tenant):
            legacy = routes._legacy_attachment_payload(session, session.get(SopDocument, sop_id), files, tenant)
        assert legacy[0]["id"] == str(playback) and legacy[0]["url"].endswith(str(playback))
        assert snapshot == before
