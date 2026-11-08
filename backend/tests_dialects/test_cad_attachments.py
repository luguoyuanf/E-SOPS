"""CAD attachment contracts without replacement databases or external storage."""

import io
import json
import struct
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.modules.esop import operation_media as media
from app.modules.esop.infrastructure.models import Operation
from app.modules.esop.product_sop import (
    snapshot_operations,
    submission_pages,
    validate_submission,
)
from app.platform.public_api.files import FileAssetSummary


def glb_document():
    chunk = json.dumps({"asset": {"version": "2.0"}}).encode()
    chunk += b" " * (-len(chunk) % 4)
    return b"glTF" + struct.pack("<IIII", 2, 20 + len(chunk), len(chunk), 0x4E4F534A) + chunk


MODEL_BYTES = {
    "dxf": b"0\nSECTION\n2\nENTITIES\n0\nLINE\n10\n0\n20\n0\n11\n10\n21\n10\n0\nENDSEC\n0\nEOF\n",
    "step": b"ISO-10303-21;\nHEADER;ENDSEC;DATA;#1=CARTESIAN_POINT('',(0.,0.,0.));ENDSEC;END-ISO-10303-21;",
    "stp": b"ISO-10303-21;\nHEADER;ENDSEC;DATA;#1=CARTESIAN_POINT('',(0.,0.,0.));ENDSEC;END-ISO-10303-21;",
    "stl": b"fixture".ljust(80, b"\0") + struct.pack("<I12fH", 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0),
    "obj": b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
    "glb": glb_document(),
    "gltf": b'{"asset":{"version":"2.0"},"buffers":[{"uri":"part.bin","byteLength":1}]}',
    "bin": b"\0",
    "mtl": b"newmtl steel\nKd 0.5 0.5 0.5\n",
}


@pytest.mark.parametrize("extension", MODEL_BYTES)
def test_model_originals_are_accepted_without_office_conversion(monkeypatch, extension):
    data = MODEL_BYTES[extension]
    media.validate_model_file(data, extension)
    file = SimpleNamespace(filename=f"part.{extension}", file=io.BytesIO(data))
    tenant, actor, fid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    asset = FileAssetSummary(id=fid, original_name=file.filename, size=len(data), sha256="0" * 64)
    files = Mock()
    files.get_accessible_file.return_value = asset
    store = Mock(side_effect=lambda **kwargs: fid if kwargs["file"].file.read() == data else None)
    convert = Mock()
    monkeypatch.setattr(media, "upload_authorized_file", store)
    monkeypatch.setattr(media, "convert_document", convert)
    result = media.upload_operation_media(SimpleNamespace(session=Mock(), tenant_id=tenant), SimpleNamespace(id=actor), files, file)
    assert result.file_id == fid and result.kind == media.FILE_KINDS[extension]
    assert result.display_file_id is None and result.display_pages == []
    convert.assert_not_called()
    store.assert_called_once()


@pytest.mark.parametrize("extension", ("dxf", "step", "stp", "stl", "obj", "glb", "gltf", "mtl"))
def test_corrupt_models_do_not_create_a_file_asset(monkeypatch, extension):
    store = Mock()
    monkeypatch.setattr(media, "upload_authorized_file", store)
    file = SimpleNamespace(filename=f"bad.{extension}", file=io.BytesIO(b"not a model"))
    with pytest.raises(HTTPException) as error:
        media.upload_operation_media(Mock(), Mock(), Mock(), file)
    assert error.value.status_code == 422 and "文件格式" in error.value.detail
    store.assert_not_called()


def test_binary_stl_triangle_count_and_glb_json_chunk_are_checked():
    with pytest.raises(HTTPException):
        media.validate_model_file(MODEL_BYTES["stl"][:-1], "stl")
    damaged = bytearray(MODEL_BYTES["glb"])
    struct.pack_into("<I", damaged, 12, 100_000)
    with pytest.raises(HTTPException):
        media.validate_model_file(bytes(damaged), "glb")
    with pytest.raises(HTTPException):
        media.validate_model_file(b"", "bin")


def test_cad_and_model_resources_stay_in_snapshot_but_not_image_projection():
    tenant, product = uuid.uuid4(), uuid.uuid4()
    files = Mock()
    assets = {}
    attachments = []
    for name, kind in (("part.dxf", "cad"), ("part.gltf", "model3d"), ("part.bin", "model_resource"), ("paint.png", "image")):
        fid = uuid.uuid4()
        assets[fid] = FileAssetSummary(id=fid, original_name=name, size=4, sha256="0" * 64)
        attachments.append({"file_id": str(fid), "name": name, "kind": kind, "size": 4})
    source = Operation(tenant_id=tenant, product_id=product, code="PROC12345678", name="安装", attachments=attachments)
    files.get_accessible_file.side_effect = lambda **kwargs: assets.get(kwargs["file_id"])
    snapshot = validate_submission(SimpleNamespace(session=Mock(), tenant_id=tenant), [source], files)
    assert [a["kind"] for a in snapshot[0]["attachments"]] == ["cad", "model3d", "model_resource", "image"]
    pages = submission_pages(snapshot[0]["attachments"])
    assert [page["file_id"] for page in pages] == [attachments[-1]["file_id"]]
    assert len(snapshot_operations([source])[0]["attachments"]) == 4
    assert all(call.kwargs["tenant_id"] == tenant for call in files.get_accessible_file.call_args_list)


def test_model_resource_alone_is_not_a_publishable_instruction():
    tenant, fid = uuid.uuid4(), uuid.uuid4()
    source = Operation(tenant_id=tenant, product_id=uuid.uuid4(), code="PROC12345678", name="安装",
                       attachments=[{"file_id": str(fid), "name": "part.bin", "kind": "model_resource", "size": 4}])
    files = Mock()
    files.get_accessible_file.return_value = FileAssetSummary(id=fid, original_name="part.bin", size=4, sha256="0" * 64)
    with pytest.raises(HTTPException) as error:
        validate_submission(SimpleNamespace(session=Mock(), tenant_id=tenant), [source], files)
    assert error.value.status_code == 422 and "主模型" in error.value.detail
