"""Skin detail slots, regions and detail tiles (no Blender needed)."""
import ast
import copy
import hashlib
import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tak.pipeline import AVATARS_DIR, PACKS  # noqa: E402
from tak.pipeline.manifest import skin_summary  # noqa: E402
from tak.pipeline.spec import SKIN_DETAIL_SLOTS, SKIN_REGIONS, SpecError, load_spec, validate_spec  # noqa: E402

SKINMAPS = ROOT / "blender" / "tak_blender" / "skinmaps.py"
DETAIL_DIR = ROOT / "assets" / "detail" / "skin"


def _module_constant(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value
    raise KeyError(name)


def _tuple_constant(path, name):
    value = _module_constant(path, name)
    if isinstance(value, ast.BinOp):  # SLOTS = HEIGHT_SLOTS + (...)
        return _tuple_constant(path, value.left.id) + ast.literal_eval(value.right)
    return ast.literal_eval(value)


def test_spec_names_match_the_blender_side():
    assert tuple(SKIN_DETAIL_SLOTS) == _tuple_constant(SKINMAPS, "SLOTS")
    assert tuple(SKIN_REGIONS) == _tuple_constant(SKINMAPS, "REGIONS")


@pytest.mark.parametrize("slug", ["rowan", "mira"])
def test_shipped_detail_sources_exist(slug):
    spec = load_spec(AVATARS_DIR / slug / "spec.json")
    detail = spec["skin"].get("detail", {})
    assert set(detail) == set(SKIN_DETAIL_SLOTS)
    for slot, block in detail.items():
        source = block.get("source", "procedural")
        if source != "procedural":
            path = (ROOT / source).resolve()
            assert path.is_file(), source
            assert DETAIL_DIR.resolve() in path.parents


def _png_info(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, depth, colour = struct.unpack(">IIBB", data[16:26])
    return width, height, depth, colour


def test_detail_tiles_have_provenance():
    record = json.loads((DETAIL_DIR / "provenance.json").read_text(encoding="utf-8"))
    assert record["license"] == "CC-BY-4.0"
    files = sorted(p.name for p in DETAIL_DIR.glob("*.png"))
    assert files and sorted(record["files"]) == files
    for name, entry in record["files"].items():
        path = DETAIL_DIR / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        width, height, depth, colour = _png_info(path)
        assert width == height and width & (width - 1) == 0  # square, power of two
        assert colour == (2 if "color_variation" in name else 0)  # RGB or greyscale
    text = json.dumps(record)
    assert ":\\" not in text and "/mnt/" not in text


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s["skin"]["detail"].__setitem__("freckles", {}), "is not a detail slot"),
    (lambda s: s["skin"]["detail"]["lips_height"].__setitem__("source", "../outside.png"), "source must be"),
    (lambda s: s["skin"]["detail"]["lips_height"].__setitem__("source", "/abs/tile.png"), "source must be"),
    (lambda s: s["skin"]["detail"]["lips_height"].__setitem__("source", "assets/tile.exr"), "source must be"),
    (lambda s: s["skin"]["detail"]["lips_height"].__setitem__("rotate", 45), "rotate must be"),
    (lambda s: s["skin"]["detail"]["lips_height"].__setitem__("tiling", 0), "tiling must be"),
    (lambda s: s["skin"]["detail"]["lips_height"].__setitem__("strength", 5), "strength must be"),
    (lambda s: s["skin"]["detail"]["lips_height"].__setitem__("blend", 1), "unknown keys"),
    (lambda s: s["skin"].setdefault("regions", {}).__setitem__("toes", {}), "is not a skin region"),
    (lambda s: s["skin"].setdefault("regions", {}).__setitem__("lips", {"tint": [1, 1]}), "tint must be"),
    (lambda s: s["skin"].__setitem__("sheen_color", [2, 0, 0]), "sheen_color"),
    (lambda s: s["textures"].__setitem__("skin_normal_max", 3000), "textures.skin_normal_max"),
])
def test_invalid_skin_settings_are_rejected(mutate, message):
    spec = copy.deepcopy(load_spec(AVATARS_DIR / "rowan" / "spec.json"))
    mutate(spec)
    with pytest.raises(SpecError) as info:
        validate_spec(spec, "rowan")
    assert message in str(info.value)


def test_procedural_sources_are_accepted():
    spec = copy.deepcopy(load_spec(AVATARS_DIR / "mira" / "spec.json"))
    spec["skin"]["detail"] = {slot: {"source": "procedural", "seed": 3} for slot in SKIN_DETAIL_SLOTS}
    spec["skin"]["regions"] = {"nose": {"detail": 1.5, "roughness": -0.05, "tint": [1.0, 0.9, 0.9], "amount": 0.5}}
    validate_spec(spec, "mira")


def test_skin_summary_records_tile_hashes(tmp_path):
    tile = tmp_path / "assets" / "t.png"
    tile.parent.mkdir(parents=True)
    tile.write_bytes(b"tile")
    spec = {"skin": {"material": "young_asian_female"}}
    build = {"skin": {"detail": {"face_pores_height": {"source": "assets/t.png"},
                                 "lips_height": {"source": "procedural"}}}}
    summary = skin_summary(spec, build, {"author": "x", "license": "CC0"}, root=tmp_path)
    assert summary["maps"]["detail"]["face_pores_height"]["sha256"] == hashlib.sha256(b"tile").hexdigest()
    assert "sha256" not in summary["maps"]["detail"]["lips_height"]
    assert summary["asset"]["license"] == "CC0"


def test_skin_pack_is_installed_by_setup():
    assert PACKS["skins02"]["url"].startswith("https://files2.makehumancommunity.org/")
    assert len(PACKS["skins02"]["sha256"]) == 64
