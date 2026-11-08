"""Keep original guidance files and immutable PDF/image renditions in Platform OSS."""

import io
import json
import logging
import re
import shutil
import struct
import subprocess
import threading
import uuid
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageChops
from sqlmodel import col, select
from starlette.datastructures import Headers

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import (
    Operation,
    OperationFileRendition,
    OperationMediaJob,
)
from app.modules.esop.public_api.dto import OperationAttachment
from app.platform.web_api import upload_authorized_file

FILE_KINDS = {
    "png": "image", "jpg": "image", "jpeg": "image", "webp": "image", "gif": "image",
    "pdf": "pdf", "doc": "word", "docx": "word", "xls": "excel", "xlsx": "excel",
    "ppt": "ppt", "pptx": "ppt", "mp4": "video", "webm": "video", "mov": "video",
    "dxf": "cad", "step": "model3d", "stp": "model3d", "stl": "model3d",
    "obj": "model3d", "glb": "model3d", "gltf": "model3d",
    "bin": "model_resource", "mtl": "model_resource",
}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov"}
OFFICE_EXTENSIONS = {"doc", "docx", "xls", "xlsx", "ppt", "pptx"}
MODEL_EXTENSIONS = {extension for extension, kind in FILE_KINDS.items() if kind in {"cad", "model3d", "model_resource"}}
MAX_MODEL_BYTES = 50 * 1024 * 1024
MAX_CONVERSION_BYTES = 50 * 1024 * 1024
_CONVERTERS = threading.BoundedSemaphore(2)
logger = logging.getLogger(f"uvicorn.error.{__name__}")


@contextmanager
def _timed_stage(stage: str, kind: str):
    started = perf_counter()
    success = False
    try:
        yield
        success = True
    finally:
        # No original names, object keys, credentials or document content in logs.
        logger.info("operation_media stage=%s kind=%s duration_ms=%.1f success=%s",
                    stage, kind, (perf_counter() - started) * 1000, success)


def _run(command: list[str], timeout: int) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="文档转换服务暂不可用，请稍后重试") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=422, detail="文档转换超时，请精简文档后重试") from exc
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=422, detail="文档转换失败，请检查文件是否损坏或加密") from exc


def convert_document(data: bytes, extension: str) -> tuple[bytes, list[bytes]]:
    """Use isolated temporary files; persistent outputs always use Platform storage."""
    if not data or len(data) > MAX_CONVERSION_BYTES:
        raise HTTPException(status_code=422, detail="文档为空或超出转换大小限制")
    with _CONVERTERS, TemporaryDirectory(prefix="esop-document-") as temp:
        root = Path(temp)
        source = root / f"guidance.{extension}"
        source.write_bytes(data)
        if extension in OFFICE_EXTENSIONS:
            office = shutil.which("libreoffice") or shutil.which("soffice")
            if office is None:
                raise HTTPException(status_code=503, detail="Office 转换服务暂不可用")
            export = 'pdf:calc_pdf_Export:{"SinglePageSheets":{"type":"boolean","value":"true"}}' if extension in {"xls", "xlsx"} else "pdf"
            _run([
                office, f"-env:UserInstallation={(root / 'profile').as_uri()}",
                "--headless", "--nologo", "--nodefault", "--nofirststartwizard",
                "--convert-to", export, "--outdir", str(root), str(source),
            ], 120)
        pdf = root / "guidance.pdf"
        if not pdf.exists() or not pdf.read_bytes().startswith(b"%PDF-"):
            raise HTTPException(status_code=422, detail="文档无法转换为 PDF，请检查文件格式或密码保护")
        _run([
            "pdftoppm", "-png", "-r", "144", "-scale-to", "1600", "-f", "1", "-l", "101",
            str(pdf), str(root / "page"),
        ], 180)
        pages = sorted(root.glob("page-*.png"), key=lambda path: int(path.stem.split("-")[-1]))
        if not pages or len(pages) > 100:
            raise HTTPException(status_code=422, detail="文档必须包含 1 至 100 页，请拆分后上传")
        rendered = [page.read_bytes() for page in pages]
        if extension in {"xls", "xlsx"}:
            rendered = _spreadsheet_content_pages(rendered)
        return pdf.read_bytes(), rendered


def convert_video(data: bytes, extension: str) -> tuple[bytes, list[bytes]]:
    """Keep the source; make an Android-compatible, seekable playback rendition."""
    if not data:
        raise HTTPException(status_code=422, detail="视频文件为空")
    with _CONVERTERS, TemporaryDirectory(prefix="esop-video-") as temp:
        source, target = Path(temp) / f"source.{extension}", Path(temp) / "playback.mp4"
        source.write_bytes(data)
        try:
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
                "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264",
                "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-bf", "0",
                "-vf", "pad=ceil(iw/64)*64:ceil(ih/2)*2:(ow-iw)/2:(oh-ih)/2:color=black", "-preset", "veryfast", "-crf", "22", "-threads", "2",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(target),
            ], check=True, capture_output=True, timeout=300)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail="视频转换服务暂不可用，请稍后重试") from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=422, detail="视频转换超时，请缩短视频后重试") from exc
        except subprocess.CalledProcessError as exc:
            raise HTTPException(status_code=422, detail="视频转换失败，请检查视频是否损坏") from exc
        output = target.read_bytes()
        if not output:
            raise HTTPException(status_code=422, detail="视频未生成有效播放副本")
        return output, []


def _spreadsheet_content_pages(pages: list[bytes]) -> list[bytes]:
    """Trim only outer white paper; keep internal table spaces, drawings and borders."""
    cropped = []
    for data in pages:
        with Image.open(io.BytesIO(data)) as source:
            image = source.convert("RGB")
        bounds = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        # A small safety edge keeps antialiased table borders away from the frame.
        image = image.crop((max(0, left - 4), max(0, top - 4),
                            min(image.width, right + 4), min(image.height, bottom + 4)))
        output = io.BytesIO()
        image.save(output, format="PNG")
        cropped.append(output.getvalue())
    if not cropped:
        raise HTTPException(status_code=422, detail="Excel 没有可预览的非空白工作表")
    return cropped


def validate_model_file(data: bytes, extension: str) -> None:
    """Reject obviously invalid uploads; detailed geometry decoding belongs to the viewer."""
    if not data or len(data) > MAX_MODEL_BYTES:
        raise HTTPException(status_code=422, detail="CAD / 3D 文件为空或超出 50 MB 预览大小限制")
    valid = False
    text = data.decode("utf-8-sig", errors="replace").strip() if extension in {"step", "stp", "dxf", "obj", "mtl"} else ""
    if extension in {"step", "stp"}:
        valid = text.upper().startswith("ISO-10303-21;") and "END-ISO-10303-21;" in text.upper()
    elif extension == "dxf":
        valid = data.startswith(b"AutoCAD Binary DXF\r\n\x1a\x00") or (
            re.search(r"(?m)^\s*0\s*\r?\n\s*SECTION\s*$", text) is not None
            and re.search(r"(?m)^\s*0\s*\r?\n\s*EOF\s*$", text) is not None
        )
    elif extension == "stl":
        count = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else 0
        binary = count > 0 and len(data) == 84 + count * 50
        text = "" if binary else data.decode("utf-8-sig", errors="replace").strip()
        valid = binary or (text.lower().startswith("solid") and "endsolid" in text.lower()
                           and re.search(r"(?m)^\s*vertex\s+\S+\s+\S+\s+\S+", text) is not None)
    elif extension == "obj":
        valid = re.search(r"(?m)^\s*v\s+[-+.0-9eE]+\s+[-+.0-9eE]+\s+[-+.0-9eE]+", text) is not None
    elif extension == "glb":
        if len(data) >= 20 and data[:4] == b"glTF" and struct.unpack_from("<II", data, 4) == (2, len(data)):
            length, kind = struct.unpack_from("<II", data, 12)
            if kind == 0x4E4F534A and 0 < length <= len(data) - 20 and length % 4 == 0:
                try:
                    document = json.loads(data[20:20 + length])
                    valid = isinstance(document, dict) and isinstance(document.get("asset"), dict) and document["asset"].get("version") == "2.0"
                except (ValueError, UnicodeDecodeError):
                    pass
    elif extension == "gltf":
        try:
            document = json.loads(data)
            valid = (isinstance(document, dict) and isinstance(document.get("asset"), dict)
                     and document["asset"].get("version") == "2.0")
        except (ValueError, UnicodeDecodeError):
            pass
    elif extension == "mtl":
        valid = re.search(r"(?m)^\s*newmtl\s+\S", text) is not None
    elif extension == "bin":
        valid = True
    if not valid:
        raise HTTPException(status_code=422, detail="CAD / 3D 文件格式不正确或已损坏，请检查后重新上传")


def resolve_operation_attachment(uow, files, asset, *, sheet_index: int | None = None) -> OperationAttachment:
    extension = Path(asset.original_name).suffix.lower().lstrip(".")
    kind = FILE_KINDS.get(extension)
    if kind is None:
        raise HTTPException(status_code=422, detail="不支持的工序附件格式")
    data = {"file_id": asset.id, "name": asset.original_name, "original_name": asset.original_name, "kind": kind,
            "content_type": asset.content_type, "size": asset.size}
    if sheet_index is not None:
        if extension not in {"xls", "xlsx"}:
            raise HTTPException(status_code=422, detail="只有 Excel 附件支持按 sheet 预览")
        data["sheet_index"] = sheet_index
    if extension in OFFICE_EXTENSIONS or extension == "pdf" or extension in VIDEO_EXTENSIONS:
        rendition = uow.session.exec(select(OperationFileRendition).where(
            OperationFileRendition.original_file_id == asset.id,
            OperationFileRendition.tenant_id == uow.tenant_id,
        )).first()
        if rendition is not None:
            page_ids = rendition.page_file_ids
            if sheet_index is not None:
                if sheet_index >= len(page_ids):
                    raise HTTPException(status_code=422, detail="sheet 预览页不存在，请重新转换")
                page_ids = [page_ids[sheet_index]]
            for file_id in [rendition.display_file_id, *page_ids]:
                if files.get_accessible_file(tenant_id=uow.tenant_id, file_id=uuid.UUID(str(file_id))) is None:
                    raise HTTPException(status_code=422, detail="附件转换内容已失效，请重新上传原文件")
            data.update(display_file_id=rendition.display_file_id,
                        display_content_type="video/mp4" if extension in VIDEO_EXTENSIONS else "application/pdf",
                        display_pages=page_ids)
    return OperationAttachment.model_validate(data)


def _store(uow, principal, data: bytes, name: str, content_type: str):
    from app.platform.tenant_uow import PlatformTenantUnitOfWork

    file = UploadFile(file=io.BytesIO(data), filename=name,
                      headers=Headers({"content-type": content_type}))
    with PlatformTenantUnitOfWork(uow.session, uow.tenant_id):
        return upload_authorized_file(session=uow.session, tenant_id=uow.tenant_id,
                                      uploader_id=principal.id, file=file)


def _persist_rendition(uow, principal, files, original_id, name, extension, converted, *, replace_existing=False):
    created = []
    replace_committing = False
    try:
        pdf_bytes, pages = converted
        stem = Path(name).stem
        display_id = original_id
        if extension != "pdf":
            video = extension in VIDEO_EXTENSIONS
            display_id = _store(uow, principal, pdf_bytes,
                                f"{stem}-播放副本.mp4" if video else f"{stem}.pdf",
                                "video/mp4" if video else "application/pdf")
            created.append(display_id)
        page_ids = []
        for index, page in enumerate(pages):
            page_id = _store(uow, principal, page, f"{stem}-第{index + 1}页.png", "image/png")
            created.append(page_id)
            page_ids.append(str(page_id))
        # Upload storage commits independently; recheck a concurrent successful conversion.
        existing = uow.session.exec(select(OperationFileRendition).where(
            OperationFileRendition.tenant_id == uow.tenant_id,
            OperationFileRendition.original_file_id == original_id,
        )).first()
        if existing is None:
            uow.session.add(OperationFileRendition(tenant_id=uow.tenant_id,
                            original_file_id=original_id, display_file_id=display_id,
                            page_file_ids=page_ids))
            uow.session.commit()
            return
        if replace_existing:
            # Publish only after the new upload succeeded. Retain old copies: approved snapshots may reference them.
            existing.display_file_id = display_id
            existing.page_file_ids = page_ids
            uow.session.add(existing)
            replace_committing = True
            uow.session.commit()
            return
        _discard_batch(uow, principal, files, created)
    except Exception:
        uow.session.rollback()
        # An ambiguous replacement commit may already reference the new upload; retain it rather than break playback.
        if not replace_committing:
            _discard_batch(uow, principal, files, created)
        raise


def _discard_batch(uow, principal, files, file_ids):
    for file_id in reversed(file_ids):
        try:
            files.discard_upload(tenant_id=uow.tenant_id, file_id=file_id, uploader_id=principal.id)
        except Exception:
            uow.session.rollback()
            logger.warning("Unable to remove incomplete guidance upload %s", file_id)


def upload_operation_media(uow, principal, files, file: UploadFile) -> OperationAttachment:
    extension = Path(file.filename or "").suffix.lower().lstrip(".")
    if extension not in FILE_KINDS:
        raise HTTPException(status_code=422, detail="不支持的工序附件格式")
    if extension in MODEL_EXTENSIONS:
        data = file.file.read(MAX_MODEL_BYTES + 1)
        file.file.seek(0)
        validate_model_file(data, extension)
    with _timed_stage("store_original", extension):
        original_id = upload_authorized_file(session=uow.session, tenant_id=uow.tenant_id,
                                             uploader_id=principal.id, file=file)
    try:
        if extension in OFFICE_EXTENSIONS or extension == "pdf" or extension in VIDEO_EXTENSIONS:
            uow.session.add(OperationMediaJob(
                tenant_id=uow.tenant_id, original_file_id=original_id, uploader_id=principal.id,
            ))
            uow.session.commit()
    except Exception:
        _discard_batch(uow, principal, files, [original_id])
        raise
    with _timed_stage("validate_metadata", extension):
        asset = files.get_accessible_file(tenant_id=uow.tenant_id, file_id=original_id)
        return resolve_operation_attachment(uow, files, asset)


def run_media_conversion(session, tenant_id: uuid.UUID) -> None:
    """Process one durable job per tick; an interrupted job is reclaimed after ten minutes."""
    from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
    from app.platform.infra.file_directory import SqlFileAssetDirectory

    now = get_datetime_utc()
    with EsopTenantUnitOfWork(session, tenant_id) as uow:
        job = session.exec(select(OperationMediaJob).where(
            (OperationMediaJob.status == "queued") |
            ((OperationMediaJob.status == "running") & (OperationMediaJob.started_at < now - timedelta(minutes=10)))
        ).order_by(col(OperationMediaJob.created_at)).limit(1).with_for_update()).first()
        if job is None:
            return
        job.status = "running"
        job.started_at = now
        job.attempts += 1
        job.updated_at = now
        session.add(job)
        session.commit()
        job_id, file_id, uploader_id = job.id, job.original_file_id, job.uploader_id
        files = SqlFileAssetDirectory(session)
        try:
            asset = files.get_accessible_file(tenant_id=tenant_id, file_id=file_id)
            if asset is None:
                raise HTTPException(status_code=422, detail="原文件已不存在")
            extension = Path(asset.original_name).suffix.lower().lstrip(".")
            existing = session.exec(select(OperationFileRendition).where(
                OperationFileRendition.original_file_id == file_id)).first()
            try:
                canonical = resolve_operation_attachment(uow, files, asset)
            except HTTPException:
                canonical = None
            if canonical is None or not (canonical.display_pages or canonical.display_file_id):
                if extension in OFFICE_EXTENSIONS or extension == "pdf":
                    data = files.read_file_bytes(tenant_id=tenant_id, file_id=file_id, max_bytes=MAX_CONVERSION_BYTES)
                    with _timed_stage("conversion", extension):
                        converted = convert_document(data, extension)
                elif extension in VIDEO_EXTENSIONS:
                    data = files.read_file_bytes(tenant_id=tenant_id, file_id=file_id, max_bytes=asset.size)
                    with _timed_stage("conversion", "video"):
                        converted = convert_video(data, extension)
                else:
                    raise HTTPException(status_code=422, detail="该格式无需转换")
                with _timed_stage("store_renditions", extension):
                    _persist_rendition(uow, SimpleNamespace(id=uploader_id), files,
                                       file_id, asset.original_name, extension, converted,
                                       replace_existing=existing is not None)
                canonical = resolve_operation_attachment(uow, files, asset)
            # Draft rows hold a snapshot; refresh derived fields without changing names or order.
            for operation in session.exec(select(Operation).where(Operation.is_deleted == False)).all():  # noqa: E712
                if not any(str(item.get("file_id")) == str(file_id) for item in operation.attachments):
                    continue
                operation.attachments = [
                    {**item, "display_file_id": str(canonical.display_file_id) if canonical.display_file_id else None,
                     "display_content_type": canonical.display_content_type,
                     "display_pages": [str(page) for page in resolve_operation_attachment(
                         uow, files, asset, sheet_index=item.get("sheet_index")
                     ).display_pages]}
                    if str(item.get("file_id")) == str(file_id) else item
                    for item in operation.attachments
                ]
                session.add(operation)
            job = session.get(OperationMediaJob, job_id)
            job.status = "ready"
            job.error_message = None
            job.updated_at = get_datetime_utc()
            session.add(job)
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.exception("Operation media conversion failed for job %s", job_id)
            with EsopTenantUnitOfWork(session, tenant_id):
                job = session.get(OperationMediaJob, job_id)
                permanent = isinstance(exc, HTTPException) and exc.status_code == 422
                job.status = "failed" if permanent or job.attempts >= 3 else "queued"
                job.error_message = str(exc.detail)[:255] if isinstance(exc, HTTPException) else "转换服务暂时失败，可重新转换"
                job.updated_at = get_datetime_utc()
                session.add(job)
                session.commit()


def prepare_existing_operation_media(uow, principal, files, product_id):
    from app.modules.esop.product_sop import current_operations, ensure_product_editable

    ensure_product_editable(uow, product_id)
    queued = 0
    for operation in current_operations(uow, product_id):
        for attachment in operation.attachments:
            file_id = uuid.UUID(str(attachment["file_id"]))
            asset = files.get_accessible_file(tenant_id=uow.tenant_id, file_id=file_id)
            if asset is None:
                raise HTTPException(status_code=422, detail="原始附件已不存在，请重新上传")
            extension = Path(asset.original_name).suffix.lower().lstrip(".")
            if extension not in OFFICE_EXTENSIONS | VIDEO_EXTENSIONS | {"pdf"}:
                continue
            try:
                canonical = resolve_operation_attachment(uow, files, asset, sheet_index=attachment.get("sheet_index"))
            except HTTPException as exc:
                if exc.status_code != 422:
                    raise
                canonical = None
            if canonical and (canonical.display_pages or canonical.display_file_id):
                continue
            job = uow.session.exec(select(OperationMediaJob).where(OperationMediaJob.original_file_id == file_id)).first()
            if job is None:
                uow.session.add(OperationMediaJob(tenant_id=uow.tenant_id,
                                original_file_id=file_id, uploader_id=principal.id))
                queued += 1
            elif job.status == "failed":
                job.status, job.attempts, job.error_message = "queued", 0, None
                job.started_at = None
                job.updated_at = get_datetime_utc()
                uow.session.add(job)
                queued += 1
    return {"queued": queued}


def prepare_video_rendition(uow, principal, files, file_id: uuid.UUID, *, rebuild: bool = False):
    """Explicit maintenance operation; never edits approved SOP/version snapshots."""
    asset = files.get_accessible_file(tenant_id=uow.tenant_id, file_id=file_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="视频原件不存在或不可访问")
    extension = Path(asset.original_name).suffix.lower().lstrip(".")
    if extension not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=422, detail="该文件不是支持的视频格式")
    if not rebuild:
        existing = resolve_operation_attachment(uow, files, asset)
        if existing.display_file_id:
            return existing
    data = files.read_file_bytes(tenant_id=uow.tenant_id, file_id=file_id, max_bytes=asset.size)
    converted = convert_video(data, extension)
    _persist_rendition(uow, principal, files, file_id, asset.original_name, extension, converted, replace_existing=rebuild)
    return resolve_operation_attachment(uow, files, asset)
