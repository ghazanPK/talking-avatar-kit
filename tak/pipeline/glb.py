"""Minimal GLB reader (standard library only): JSON chunk, binary chunk, accessors."""
from __future__ import annotations

import json
import struct
from pathlib import Path

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
COMPONENTS = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
TYPE_SIZES = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
NORMALIZE = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}


class GlbError(ValueError):
    pass


class Glb:
    def __init__(self, data: bytes):
        if len(data) < 20:
            raise GlbError("file too short for GLB")
        magic, version, length = struct.unpack_from("<4sII", data)
        if magic != b"glTF":
            raise GlbError("not a GLB file (bad magic)")
        if version != 2:
            raise GlbError(f"unsupported glTF version {version}")
        if length != len(data):
            raise GlbError(f"header length {length} != file size {len(data)}")
        json_len, json_type = struct.unpack_from("<II", data, 12)
        if json_type != JSON_CHUNK:
            raise GlbError("first chunk is not JSON")
        self.json = json.loads(data[20:20 + json_len].decode("utf-8"))
        offset = 20 + json_len
        self.bin = b""
        if offset < len(data):
            bin_len, bin_type = struct.unpack_from("<II", data, offset)
            if bin_type != BIN_CHUNK:
                raise GlbError("second chunk is not BIN")
            self.bin = data[offset + 8:offset + 8 + bin_len]
        self.size = len(data)

    @classmethod
    def load(cls, path: Path) -> "Glb":
        return cls(Path(path).read_bytes())

    def accessor(self, index: int) -> list[tuple]:
        """Decode a (non-sparse part of an) accessor into tuples of floats/ints."""
        acc = self.json["accessors"][index]
        fmt, size = COMPONENTS[acc["componentType"]]
        width = TYPE_SIZES[acc["type"]]
        count = acc["count"]
        values: list[tuple] = [(0,) * width] * count
        if "bufferView" in acc:
            view = self.json["bufferViews"][acc["bufferView"]]
            stride = view.get("byteStride") or size * width
            base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            values = [struct.unpack_from("<" + fmt * width, self.bin, base + i * stride) for i in range(count)]
        if acc.get("normalized") and acc["componentType"] in NORMALIZE:
            scale = NORMALIZE[acc["componentType"]]
            values = [tuple(v / scale for v in row) for row in values]
        return values

    def node_names(self) -> list[str]:
        return [n.get("name", "") for n in self.json.get("nodes", [])]

    def mesh_nodes(self) -> list[dict]:
        return [n for n in self.json.get("nodes", []) if "mesh" in n]
