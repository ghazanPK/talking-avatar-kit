"""Fabric and pattern library: processing functions and the shipped assets/fabrics, assets/patterns.

The processing tests need NumPy and Pillow (the maintainer tool's only
dependencies) and are skipped without them; the library checks need only the
standard library.
"""
import json
import struct
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FABRICS = ROOT / "assets" / "fabrics"
PATTERNS = ROOT / "assets" / "patterns"


# ---------------------------------------------------------------- shipped library (stdlib only)

def _png_size(path):
    data = path.read_bytes()[:32]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", data[16:24])


def _jpeg_size(path):
    data = path.read_bytes()
    assert data[:2] == b"\xff\xd8", f"{path.name} is not a JPEG"
    i = 2
    while i < len(data):
        marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + length
    raise AssertionError(f"{path.name}: no frame header")


def test_fabric_index_lists_existing_maps():
    doc = json.loads((FABRICS / "fabrics.json").read_text(encoding="utf-8"))
    assert doc["schema_version"] == 1
    assert doc["license"] == "CC-BY-4.0" and doc["credit"]
    assert len(doc["fabrics"]) == 15
    for name, entry in doc["fabrics"].items():
        assert 1 <= entry["patch_cm"] <= 20, name
        assert 0 < entry["roughness"] <= 1 and 0 <= entry["sheen"] <= 1
        assert 0.4 < entry["albedo_mean_linear"] < 0.8
        assert abs(entry["albedo_mean_srgb"] - 0.8) < 0.03, name
        for kind, file in entry["maps"].items():
            path = FABRICS / name / file
            assert path.is_file(), path
            size = _jpeg_size(path) if file.endswith(".jpg") else _png_size(path)
            assert size == (entry["sizes"][kind],) * 2
        assert set(entry["provenance"]["inputs"]) >= {"albedo", "height"}
        for value in entry["provenance"]["inputs"].values():
            assert len(value) == 64


def test_pattern_index_lists_existing_masks():
    doc = json.loads((PATTERNS / "patterns.json").read_text(encoding="utf-8"))
    assert set(doc["patterns"]) == {"stripes_pinstripe", "stripes_breton", "gingham", "tartan_plaid", "houndstooth"}
    for name, entry in doc["patterns"].items():
        assert entry["kind"] in ("mask", "rgb")
        assert entry["colors"] == (2 if entry["kind"] == "mask" else 3)
        assert len(entry["patch_cm"]) == 2 and all(1 < v < 20 for v in entry["patch_cm"])
        assert _png_size(PATTERNS / entry["file"]) == (1024, 1024)


def test_library_size_budget():
    total = sum(p.stat().st_size for folder in (FABRICS, PATTERNS) for p in folder.rglob("*") if p.is_file())
    assert total < 15_000_000


def test_library_json_has_no_machine_paths():
    for path in (FABRICS / "fabrics.json", PATTERNS / "patterns.json"):
        text = path.read_text(encoding="utf-8")
        assert "/mnt/" not in text and ":\\" not in text and "/home/" not in text


# ---------------------------------------------------------------- processing (NumPy + Pillow)

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")
from tak.pipeline import fabrics as F  # noqa: E402


def _weave(size=256, period=16, seed=0):
    """A periodic diagonal weave plus noise (seamless by construction)."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size]
    base = 0.5 + 0.25 * np.sin(2 * np.pi * (x + y) / period)
    return np.clip(base + 0.05 * F.blur(rng.normal(size=(size, size)), 1.0), 0, 1)


def test_luminance_removes_colour_cast():
    rgb = np.zeros((4, 4, 3))
    rgb[..., 0], rgb[..., 1], rgb[..., 2] = 0.5, 0.6, 0.7
    lum = F.luminance(rgb)
    assert lum.shape == (4, 4)
    assert np.allclose(lum, 0.2126 * 0.5 + 0.7152 * 0.6 + 0.0722 * 0.7)


def test_blur_is_periodic_and_keeps_mean():
    img = _weave()
    out = F.blur(img, 3.0)
    assert abs(out.mean() - img.mean()) < 1e-9
    # Periodic: blurring a rolled image equals rolling the blurred image.
    assert np.allclose(F.blur(np.roll(img, 37, axis=1), 3.0), np.roll(out, 37, axis=1))


def test_seamless_tile_scores_near_one_and_seamed_tile_high():
    tile = _weave(period=16)
    assert max(F.seam_score(tile)) < 1.5
    seamed = tile[:, :250]  # cut mid-period: the wrap now jumps
    assert max(F.max_jump(seamed, period=16)) > 1.8


def test_repair_seams_makes_tile_seamless():
    rng = np.random.default_rng(3)
    tile = _weave(size=256, period=16)
    tile = np.roll(tile, 5, axis=1)[:, :243]     # not periodic any more
    tile = np.ascontiguousarray(tile[:243, :243]) + 0.02 * rng.normal(size=(243, 243))
    before = F.max_jump(tile, period=16)
    out, report = F.repair_seams(tile, period=16)
    after = F.max_jump(out, period=16)
    assert out.shape == tile.shape
    assert max(after) < max(before)
    assert max(after) < 1.8
    assert report["cuts"]["x"] and report["cuts"]["y"]


def test_resample_keeps_tile_seamless():
    tile = _weave(size=256, period=32)
    out = F.resample(tile, 128)
    assert out.shape == (128, 128)
    assert max(F.seam_score(out)) < 1.5


def test_height_to_normal_convention():
    # A ramp rising to the right: normals lean left (-X); rising toward the top of the
    # image (decreasing row): normals lean down the image (-Y, OpenGL / glTF convention).
    x = np.tile(np.linspace(0, 1, 64), (64, 1))
    n = F.height_to_normal(np.sin(2 * np.pi * x) * 0.5 + 0.5, patch_mm=10, relief_mm=0.5) * 2 - 1
    assert np.allclose(np.linalg.norm(n, axis=-1), 1, atol=1e-6)
    assert n[32, 1, 0] < 0            # slope up to the right at x ~ 0
    up = 1 - np.tile(np.linspace(0, 1, 64)[:, None], (1, 64))  # higher toward the top rows
    n2 = F.height_to_normal(np.sin(2 * np.pi * up) * 0.5 + 0.5, patch_mm=10, relief_mm=0.5) * 2 - 1
    assert n2[62, 32, 1] < 0 and abs(n2[62, 32, 0]) < 1e-6


def test_mask_period_and_crop_to_whole_periods():
    size, period = 300, 23.0
    x = np.arange(size)
    stripes = ((x % period) < period / 2).astype(float)
    mask = np.tile(stripes, (size, 1))
    found = F.mask_period(mask, 1)
    assert abs(found - period) < 0.6
    assert F.mask_period(mask, 0) is None          # no variation down the columns
    cropped, fraction = F.crop_to_periods(mask, (found, None))
    width = cropped.shape[1]
    assert abs(width / period - round(width / period)) < 0.2
    assert fraction[1] == 1.0


def test_clean_mask_snaps_to_palette():
    rng = np.random.default_rng(1)
    rgb = np.zeros((40, 40, 3))
    rgb[:20, :, 0] = 0.9
    rgb[20:, :, 2] = 0.95
    rgb += 0.05 * rng.random((40, 40, 3))
    clean = F.clean_mask(rgb, "rgb")
    assert set(np.unique(clean)) <= {0.0, 1.0}
    assert np.allclose(clean.sum(axis=2), 1)
    assert clean[5, 5, 0] == 1 and clean[35, 35, 2] == 1
    grey = F.clean_mask(rgb, "mask")
    assert set(np.unique(grey)) <= {0.0, 1.0}


def _write_png(path, arr):
    from PIL import Image
    Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).save(path)


def test_process_fabric_and_pattern_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "ALBEDO_SIZE", 128)
    monkeypatch.setattr(F, "NORMAL_SIZE", 64)
    monkeypatch.setattr(F, "ROUGHNESS_SIZE", 64)
    monkeypatch.setattr(F, "PATTERN_SIZE", 128)
    src = tmp_path / "src"
    src.mkdir()
    weave = _weave(size=200, period=20)
    tinted = np.stack([weave * 0.9, weave * 0.8, weave * 0.85], axis=-1)   # colour cast to remove
    _write_png(src / "denim_twill_albedo.png", tinted)
    _write_png(src / "denim_twill_height.png", np.roll(weave, 7, axis=0))
    _write_png(src / "denim_twill_roughness.png", 0.5 + 0.1 * weave)
    x = np.arange(200)
    _write_png(src / "stripes_breton.png", np.tile(((x % 25) < 12).astype(float)[:, None], (1, 200)))
    result = F.build_library(src, tmp_path)
    assert result["fabrics"] == ["denim_twill"] and result["patterns"] == ["stripes_breton"]
    doc = json.loads((tmp_path / "assets" / "fabrics" / "fabrics.json").read_text())
    entry = doc["fabrics"]["denim_twill"]
    assert entry["maps"] == {"albedo": "albedo.jpg", "normal": "normal.png", "roughness": "roughness.png"}
    from PIL import Image
    albedo = np.asarray(Image.open(tmp_path / "assets" / "fabrics" / "denim_twill" / "albedo.jpg"))
    assert albedo.ndim == 2 and albedo.shape == (128, 128)     # neutral grey, one channel
    assert abs(albedo.mean() / 255 - F.ALBEDO_MEAN_SRGB) < 0.03
    normal = np.asarray(Image.open(tmp_path / "assets" / "fabrics" / "denim_twill" / "normal.png")).astype(float)
    assert normal.shape == (64, 64, 3) and normal[..., 2].min() > 128   # z always points out
    pat = json.loads((tmp_path / "assets" / "patterns" / "patterns.json").read_text())["patterns"]["stripes_breton"]
    assert pat["kind"] == "mask" and pat["file"] == "stripes_breton.png"
    assert entry["provenance"]["inputs"]["albedo"] == F.sha256(src / "denim_twill_albedo.png")
