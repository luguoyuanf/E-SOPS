"""Read Excel sheet boundaries for product SOP draft import."""

import io
import posixpath
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
MAX_ARCHIVE_ENTRY_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 1000

SKIP_NAMES = {"变更履历表", "修订履历表", "修订记录", "版本记录", "封面", "目录"}


def workbook_sheets(data: bytes, extension: str) -> list[dict[str, object]]:
    if extension == "xls":
        office = shutil.which("libreoffice") or shutil.which("soffice")
        if office is None:
            raise HTTPException(503, "Excel 解析服务暂不可用")
        with TemporaryDirectory(prefix="esop-import-") as temp:
            source = Path(temp) / "source.xls"
            source.write_bytes(data)
            try:
                subprocess.run([office, f"-env:UserInstallation={(Path(temp) / 'profile').as_uri()}",
                                "--headless", "--convert-to", "xlsx", "--outdir", temp, str(source)],
                               check=True, capture_output=True, timeout=60)
                data = (Path(temp) / "source.xlsx").read_bytes()
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                raise HTTPException(422, "Excel 文件无法解析") from exc
    if extension not in {"xls", "xlsx"}:
        raise HTTPException(422, "请选择 Excel 文件")
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if sum(entry.file_size for entry in entries) > MAX_ARCHIVE_EXPANDED_BYTES:
                raise HTTPException(422, "Excel 解压后总数据量过大")
            for entry in entries:
                if entry.file_size > MAX_ARCHIVE_ENTRY_BYTES:
                    raise HTTPException(422, "Excel 内部文件数据过大")
                if entry.file_size > max(entry.compress_size, 1) * MAX_ARCHIVE_COMPRESSION_RATIO:
                    raise HTTPException(422, "Excel 压缩比例异常")
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relations = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {item.attrib["Id"]: item.attrib["Target"] for item in relations.findall(f"{{{PACKAGE_REL}}}Relationship")}
            sheets = []
            content_index = 0
            for sheet in workbook.findall(f"{{{MAIN}}}sheets/{{{MAIN}}}sheet"):
                if sheet.attrib.get("state", "visible") != "visible":
                    continue
                name = sheet.attrib["name"].strip()
                target = targets[sheet.attrib[f"{{{REL}}}id"]]
                path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
                entry = archive.getinfo(path)
                root = ElementTree.fromstring(archive.read(entry))
                has_values = any(cell.find(f"{{{MAIN}}}v") is not None or
                                 cell.find(f"{{{MAIN}}}is") is not None or
                                 cell.find(f"{{{MAIN}}}f") is not None
                                 for cell in root.iter(f"{{{MAIN}}}c"))
                has_drawing = root.find(f"{{{MAIN}}}drawing") is not None
                if has_values or has_drawing:
                    sheets.append({"index": content_index, "name": name,
                                   "selected": name not in SKIP_NAMES and len(name) <= 100})
                    content_index += 1
            if not sheets or len(sheets) > 100:
                raise HTTPException(422, "Excel 没有可导入的 sheet，或 sheet 数量超过 100")
            return sheets
    except (BadZipFile, KeyError, ValueError, ElementTree.ParseError) as exc:
        raise HTTPException(422, "Excel 文件无法解析") from exc
