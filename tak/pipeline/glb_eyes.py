"""Give a built avatar GLB the kit's eye treatment without rebuilding it.

    python -m tak.pipeline.glb_eyes avatars/amina/amina.glb [more.glb ...]

Applies the same look the build gives Rowan and Mira (see ``blender/tak_blender/textures.py``
``tune_eye``): the saturated maroon iris of the MakeHuman eye texture becomes a natural brown at
the same luminance, the sclera is calmed, and the ``eyes`` material gets a clearcoat (wet
highlight) with roughness 0.35. The GLB is rewritten in place; the avatar's ``manifest.json``
(same folder) gets its new ``bytes`` and ``sha256``. Idempotent: an already treated GLB is left
unchanged. Maintainer tool: needs NumPy and Pillow.
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import sys
from pathlib import Path

GLB_MAGIC, JSON_CHUNK, BIN_CHUNK = b"glTF", 0x4E4F534A, 0x004E4942
MARK = "tak_eye_treatment"


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, version, _ = struct.unpack_from("<4sII", data, 0)
    if magic != GLB_MAGIC or version != 2:
        raise ValueError(f"{path}: not a glTF 2.0 binary")
    json_len, json_type = struct.unpack_from("<II", data, 12)
    if json_type != JSON_CHUNK:
        raise ValueError(f"{path}: first chunk is not JSON")
    gltf = json.loads(data[20:20 + json_len])
    offset = 20 + json_len
    bin_len, bin_type = struct.unpack_from("<II", data, offset)
    if bin_type != BIN_CHUNK:
        raise ValueError(f"{path}: second chunk is not BIN")
    return gltf, data[offset + 8: offset + 8 + bin_len]


def write_glb(path: Path, gltf: dict, views: list[bytes]) -> None:
    """Repack every bufferView into one aligned binary buffer and write the GLB."""
    blob = bytearray()
    for view, chunk in zip(gltf["bufferViews"], views):
        blob += b"\0" * (-len(blob) % 4)
        view["byteOffset"] = len(blob)
        view["byteLength"] = len(chunk)
        view["buffer"] = 0
        blob += chunk
    blob += b"\0" * (-len(blob) % 4)
    gltf["buffers"] = [{"byteLength": len(blob)}]
    body = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    body += b" " * (-len(body) % 4)
    total = 12 + 8 + len(body) + 8 + len(blob)
    path.write_bytes(struct.pack("<4sII", GLB_MAGIC, 2, total) + struct.pack("<II", len(body), JSON_CHUNK) + body
                     + struct.pack("<II", len(blob), BIN_CHUNK) + bytes(blob))


def tune_eye_rgb(rgb, sclera_level=0.86, iris_tint=(1.0, 0.64, 0.38), iris_gain=1.25, keep=0.25):
    """Same formula and defaults as ``tune_eye`` in the Blender build (values 0..1)."""
    import numpy as np

    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    luma = rgb @ weights
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    sclera = np.clip((luma - 0.45) / 0.25, 0, 1) * np.clip(1 - sat / 0.25, 0, 1)
    iris = np.clip((sat - 0.12) / 0.15, 0, 1)
    tint = np.array(iris_tint, dtype=np.float32)
    tint = tint / float(tint @ weights)
    iris_rgb = np.clip(luma[..., None] * iris_gain, 0, 1) * tint
    iris_rgb = iris_rgb * (1 - keep) + rgb * keep
    rgb = rgb * (1 - iris[..., None]) + iris_rgb * iris[..., None]
    sclera_rgb = rgb * sclera_level * np.array([1.0, 0.985, 0.96], dtype=np.float32)
    rgb = rgb * (1 - sclera[..., None]) + sclera_rgb * sclera[..., None]
    return np.clip(rgb, 0, 1)


def treat(path: Path) -> bool:
    import numpy as np
    from PIL import Image

    gltf, blob = read_glb(path)
    views = [blob[v.get("byteOffset", 0): v.get("byteOffset", 0) + v["byteLength"]] for v in gltf["bufferViews"]]
    eyes = [m for m in gltf.get("materials", []) if m.get("name", "").lower() == "eyes"]
    if not eyes:
        raise ValueError(f"{path}: no 'eyes' material")
    changed = False
    for material in eyes:
        if material.get("extras", {}).get(MARK):
            continue
        pbr = material.setdefault("pbrMetallicRoughness", {})
        texture = pbr.get("baseColorTexture")
        if texture is not None:
            image = gltf["images"][gltf["textures"][texture["index"]]["source"]]
            index = image["bufferView"]
            rgb = np.asarray(Image.open(io.BytesIO(views[index])).convert("RGB"), dtype=np.float32) / 255.0
            out = Image.fromarray((tune_eye_rgb(rgb) * 255.0 + 0.5).astype(np.uint8), "RGB")
            buffer = io.BytesIO()
            out.save(buffer, "PNG", optimize=True)
            views[index] = buffer.getvalue()
            image["mimeType"] = "image/png"
        pbr["roughnessFactor"] = 0.35
        pbr["metallicFactor"] = 0
        material.setdefault("extensions", {})["KHR_materials_clearcoat"] = {"clearcoatFactor": 1}
        material.setdefault("extras", {})[MARK] = "brown iris, calmed sclera, clearcoat, roughness 0.35"
        used = gltf.setdefault("extensionsUsed", [])
        if "KHR_materials_clearcoat" not in used:
            used.append("KHR_materials_clearcoat")
        changed = True
    if changed:
        write_glb(path, gltf, views)
        manifest_path = path.with_name("manifest.json")
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            data = path.read_bytes()
            manifest["bytes"] = len(data)
            manifest["sha256"] = hashlib.sha256(data).hexdigest()
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    paths = [Path(p) for p in (sys.argv[1:] if argv is None else argv)]
    if not paths:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    for path in paths:
        print(f"{path}: {'treated' if treat(path) else 'already treated'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
