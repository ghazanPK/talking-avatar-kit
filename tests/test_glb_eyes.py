"""The GLB eye treatment: rewrites a valid GLB, recolours a maroon iris, adds clearcoat, is idempotent."""

import io
import json
import struct

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

from tak.pipeline.glb_eyes import read_glb, treat  # noqa: E402


def make_glb(path):
    image = Image.new("RGB", (8, 8), (220, 214, 208))  # sclera
    for x in range(2, 6):
        for y in range(2, 6):
            image.putpixel((x, y), (120, 25, 20))  # maroon iris
    png = io.BytesIO()
    image.save(png, "PNG")
    png = png.getvalue()
    filler = b"\x01\x02\x03\x04" * 3
    blob = filler + png + b"\0" * (-len(png) % 4)
    gltf = {
        "asset": {"version": "2.0"},
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(filler)},
                        {"buffer": 0, "byteOffset": len(filler), "byteLength": len(png)}],
        "buffers": [{"byteLength": len(blob)}],
        "images": [{"bufferView": 1, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": [{"name": "skin"}, {"name": "eyes", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "roughnessFactor": 0.7}}],
    }
    body = json.dumps(gltf).encode()
    body += b" " * (-len(body) % 4)
    total = 12 + 8 + len(body) + 8 + len(blob)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(body), 0x4E4F534A) + body
                     + struct.pack("<II", len(blob), 0x004E4942) + blob)
    (path.parent / "manifest.json").write_text(json.dumps({"file": path.name}), encoding="utf-8")


def iris_pixel(gltf, blob):
    view = gltf["bufferViews"][gltf["images"][0]["bufferView"]]
    data = blob[view["byteOffset"]: view["byteOffset"] + view["byteLength"]]
    return Image.open(io.BytesIO(data)).convert("RGB").getpixel((3, 3))


def test_treatment_recolours_iris_and_adds_clearcoat(tmp_path):
    glb = tmp_path / "amina.glb"
    make_glb(glb)
    assert treat(glb) is True
    gltf, blob = read_glb(glb)
    eyes = gltf["materials"][1]
    assert eyes["extensions"]["KHR_materials_clearcoat"]["clearcoatFactor"] == 1
    assert eyes["pbrMetallicRoughness"]["roughnessFactor"] == 0.35
    assert "KHR_materials_clearcoat" in gltf["extensionsUsed"]
    assert gltf["materials"][0] == {"name": "skin"}
    r, g, b = iris_pixel(gltf, blob)
    assert g / r > 25 / 120 + 0.2  # hue moved from maroon toward brown
    filler = gltf["bufferViews"][0]
    assert blob[filler["byteOffset"]: filler["byteOffset"] + 12] == b"\x01\x02\x03\x04" * 3
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["bytes"] == glb.stat().st_size and len(manifest["sha256"]) == 64


def test_treatment_is_idempotent(tmp_path):
    glb = tmp_path / "elena.glb"
    make_glb(glb)
    treat(glb)
    before = glb.read_bytes()
    assert treat(glb) is False
    assert glb.read_bytes() == before
