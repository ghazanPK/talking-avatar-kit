"""Fabric swatch and pattern-mask library: process source images into seamless, tintable tiles.

Maintainer tool. The processed library in ``assets/fabrics/`` and
``assets/patterns/`` is committed, so users never run this. It needs NumPy and
Pillow (``pip install numpy pillow``); the rest of the kit does not.

    python -m tak.pipeline.fabrics --src DIR [--out-root .] [--only denim_twill,...]

``DIR`` holds the source swatches named ``<fabric>_albedo.png``,
``<fabric>_height.png``, optional ``<fabric>_roughness.png`` and the pattern
masks ``<pattern>.png``. For every fabric the tool:

1. converts every map to luminance (Rec. 709 weights), so data maps carry no
   colour cast and the albedo is a neutral grey;
2. removes low-frequency shading (flat-field correction with a wide periodic
   Gaussian), so a tile does not repeat as a blotch;
3. aligns the maps: generated albedo and height images do not register pixel
   for pixel, so the albedo keeps only its low-frequency variation (slubs,
   heather) and takes its weave structure from the height map, which also
   gives the normal map; roughness keeps its low frequencies;
4. repairs the tile edges once for all maps together: the tile is offset by
   half its size and the two seams that move to the centre are replaced by
   strips of the same texture, joined along minimum-error cuts (image quilting);
5. normalises the albedo to a fixed mean brightness, resamples (periodic
   resampling keeps the tile seamless) and derives a tangent-space normal map
   from the height (OpenGL / glTF convention) using the real patch size;
6. writes ``albedo.jpg`` (greyscale JPEG), ``normal.png`` and optional
   ``roughness.png`` plus ``assets/fabrics/fabrics.json``.

Pattern masks are cleaned to exact palettes (black/white, or pure red, green,
blue channels), cropped to whole pattern periods so they tile, and resampled
with soft edges into ``assets/patterns/`` with ``patterns.json``.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

LUMA = (0.2126, 0.7152, 0.0722)
ALBEDO_MEAN_SRGB = 0.80
SOURCE_DATE = "2026-10-08"
PROVENANCE = ("Generated with an image generator from text prompts recorded by the author on "
              f"{SOURCE_DATE}; processed with tak.pipeline.fabrics (luminance, flat-field, map alignment, "
              "seam repair, resampling, normal map from height).")

# name: (label, real patch size in cm, relief depth in mm for the normal map, roughness, sheen, uses)
FABRICS: dict[str, dict[str, Any]] = {
    "cotton_jersey": {"label": "Cotton jersey", "patch_cm": 6, "relief_mm": 0.25, "roughness": 0.85, "sheen": 0.3,
                      "use": ["t-shirts", "tops"]},
    "denim_twill": {"label": "Denim twill", "patch_cm": 6, "relief_mm": 0.3, "roughness": 0.82, "sheen": 0.15,
                    "use": ["jeans", "jackets"]},
    "wool_suiting": {"label": "Wool suiting", "patch_cm": 5, "relief_mm": 0.12, "roughness": 0.72, "sheen": 0.35,
                     "use": ["suits", "trousers", "blazers"]},
    "cotton_poplin": {"label": "Cotton poplin", "patch_cm": 4, "relief_mm": 0.08, "roughness": 0.7, "sheen": 0.15,
                      "use": ["shirts", "blouses"]},
    "scrubs_twill": {"label": "Scrubs twill", "patch_cm": 5, "relief_mm": 0.12, "roughness": 0.75, "sheen": 0.1,
                     "use": ["medical scrubs"]},
    "leather_smooth": {"label": "Smooth leather", "patch_cm": 8, "relief_mm": 0.12, "roughness": 0.45, "sheen": 0.0,
                       "use": ["shoes", "belts", "jackets"]},
    "knit_sweater": {"label": "Knit", "patch_cm": 8, "relief_mm": 1.2, "roughness": 0.9, "sheen": 0.4,
                     "use": ["sweaters"]},
    "linen_plain": {"label": "Linen", "patch_cm": 6, "relief_mm": 0.25, "roughness": 0.82, "sheen": 0.1,
                    "use": ["shirts", "trousers", "dresses"]},
    "corduroy": {"label": "Corduroy", "patch_cm": 6, "relief_mm": 0.8, "roughness": 0.8, "sheen": 0.5,
                 "use": ["trousers", "jackets"]},
    "canvas_duck": {"label": "Canvas", "patch_cm": 8, "relief_mm": 0.3, "roughness": 0.85, "sheen": 0.05,
                    "use": ["work wear", "shoes", "bags"]},
    "sport_mesh": {"label": "Sport mesh", "patch_cm": 5, "relief_mm": 0.6, "roughness": 0.6, "sheen": 0.1,
                   "use": ["sportswear"]},
    "fleece": {"label": "Fleece", "patch_cm": 6, "relief_mm": 0.15, "roughness": 0.95, "sheen": 0.6,
               "use": ["sweatshirts", "jackets"]},
    "satin": {"label": "Satin", "patch_cm": 5, "relief_mm": 0.05, "roughness": 0.3, "sheen": 0.6,
              "use": ["blouses", "dresses", "linings"]},
    "suede": {"label": "Suede", "patch_cm": 8, "relief_mm": 0.15, "roughness": 0.92, "sheen": 0.5,
              "use": ["shoes", "jackets"]},
    "rubber_sole": {"label": "Rubber", "patch_cm": 6, "relief_mm": 0.2, "roughness": 0.65, "sheen": 0.0,
                    "use": ["shoe soles", "trainers"]},
}

# name: (label, kind, nominal patch in cm before cropping to whole periods)
# kind "mask": white = colour A, black = colour B; "rgb": red, green, blue regions = colours A, B, C.
PATTERNS: dict[str, dict[str, Any]] = {
    "stripes_pinstripe": {"label": "Pinstripe", "kind": "mask", "patch_cm": 10},
    "stripes_breton": {"label": "Breton stripes", "kind": "mask", "patch_cm": 10},
    # The source has 12.5 mm checks over its tile; the requested gingham check is 6.25 mm.
    "gingham": {"label": "Gingham", "kind": "rgb", "patch_cm": 5},
    "tartan_plaid": {"label": "Tartan", "kind": "rgb", "patch_cm": 15},
    "houndstooth": {"label": "Houndstooth", "kind": "mask", "patch_cm": 8},
}

ALBEDO_SIZE = 1024
NORMAL_SIZE = 512
ROUGHNESS_SIZE = 512
PATTERN_SIZE = 1024


def _np():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError("fabric processing needs NumPy and Pillow: pip install numpy pillow") from exc
    return np


# ---------------------------------------------------------------- image helpers (pure NumPy)

def luminance(rgb):
    """Rec. 709 luminance of an (H, W, 3) or (H, W) float array in 0..1."""
    np = _np()
    rgb = np.asarray(rgb, dtype=np.float64)
    if rgb.ndim == 2:
        return rgb
    return rgb[..., 0] * LUMA[0] + rgb[..., 1] * LUMA[1] + rgb[..., 2] * LUMA[2]


def srgb_to_linear(v):
    np = _np()
    v = np.asarray(v, dtype=np.float64)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def blur(img, sigma):
    """Periodic Gaussian blur (FFT), so a tile stays a tile."""
    np = _np()
    if sigma <= 0:
        return np.array(img, dtype=np.float64)
    h, w = img.shape[:2]
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    kernel = np.exp(-2.0 * (math.pi ** 2) * sigma * sigma * (fx * fx + fy * fy))
    if img.ndim == 3:
        kernel = kernel[..., None]
        spectrum = np.fft.rfft2(img, axes=(0, 1))
        return np.fft.irfft2(spectrum * kernel, s=(h, w), axes=(0, 1))
    return np.fft.irfft2(np.fft.rfft2(img) * kernel, s=(h, w))


def flat_field(img, sigma_frac=1 / 8, multiplicative=True):
    """Remove low-frequency shading; keeps the mean."""
    np = _np()
    sigma = max(img.shape[:2]) * sigma_frac
    low = blur(img, sigma)
    mean = float(img.mean())
    if multiplicative:
        return img / np.maximum(low, 1e-3) * mean
    return img - low + mean


def dominant_period(img, lo=4.0, hi=None):
    """Dominant spatial period in pixels (peak of the radially averaged power spectrum)."""
    np = _np()
    h, w = img.shape
    hi = hi or min(h, w) / 4
    spec = np.abs(np.fft.fft2(img - img.mean())) ** 2
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    radius = np.sqrt(fx * fx + fy * fy)
    period = np.where(radius > 0, 1.0 / np.maximum(radius, 1e-9), np.inf)
    valid = (period >= lo) & (period <= hi)
    if not valid.any():
        return lo
    bins = np.clip((radius[valid] * min(h, w)).astype(int), 0, None)
    power = np.bincount(bins, weights=spec[valid])
    counts = np.bincount(bins)
    profile = power / np.maximum(counts, 1)
    # Weight by frequency so the 1/f falloff does not always win at low frequencies.
    k = np.arange(len(profile))
    best = int(np.argmax(profile * k))
    return float(min(h, w) / max(best, 1))


def seam_score(img):
    """Edge discontinuity relative to ordinary neighbour differences, per axis (1.0 = seamless).

    Returns (x score, y score): mean |first column - last column| divided by
    the mean difference between adjacent columns inside the tile, and the same
    for rows. Works on (H, W) or (H, W, C) arrays.
    """
    np = _np()
    a = np.asarray(img, dtype=np.float64)
    inner_x = np.abs(np.diff(a, axis=1)).mean() + 1e-9
    inner_y = np.abs(np.diff(a, axis=0)).mean() + 1e-9
    edge_x = np.abs(a[:, 0] - a[:, -1]).mean()
    edge_y = np.abs(a[0] - a[-1]).mean()
    return float(edge_x / inner_x), float(edge_y / inner_y)


def centre_seam_score(img):
    """Seam score of the tile's centre lines (where repair_seams puts its cuts)."""
    np = _np()
    h, w = img.shape[:2]
    return seam_score(np.roll(img, (h // 2, w // 2), axis=(0, 1)))


def column_jumps(img, period=None):
    """Per-column discontinuity (with wrap): mean |column c - column c-1| relative to the same
    measure at the same weave phase one period to either side (or, without a period, the median
    of the 16 neighbouring columns). Weave structure scores about 1, a seam clearly more."""
    np = _np()
    a = np.asarray(img, dtype=np.float64)
    if a.ndim == 3:
        a = a.mean(axis=2)
    diff = np.abs(a - np.roll(a, 1, axis=1)).mean(axis=0)
    if period and period >= 3:
        p = int(round(period))
        shifts = [s for k in (-1, 1) for s in range(k * p - 2, k * p + 3)]
        reference = np.max(np.stack([np.roll(diff, s) for s in shifts]), axis=0)
    else:
        reference = np.median(np.stack([np.roll(diff, s) for s in range(-8, 9) if s != 0]), axis=0)
    return diff / np.maximum(reference, 1e-9)


def max_jump(img, period=None):
    """Worst column and row discontinuity anywhere in the tile, wrap included (about 1-1.3 = seamless)."""
    np = _np()
    a = np.asarray(img, dtype=np.float64)
    rows = np.swapaxes(a, 0, 1)
    return float(column_jumps(a, period).max()), float(column_jumps(rows, period).max())


def _seam_columns(img, threshold=1.6, keep_apart=0.2, period=None):
    """Columns with a seam-like jump, strongest first, at least ``keep_apart`` of the width apart."""
    np = _np()
    jumps = column_jumps(img, period)
    w = len(jumps)
    found = []
    for c in np.argsort(-jumps):
        if jumps[c] < threshold:
            break
        if all(min(abs(c - f), w - abs(c - f)) > keep_apart * w for f in found):
            found.append(int(c))
    return found


def _min_cut(err):
    """Minimum-error vertical path through an (H, W) error surface; returns column per row."""
    np = _np()
    h, w = err.shape
    cost = err.copy()
    back = np.zeros((h, w), dtype=np.int64)
    for y in range(1, h):
        prev = cost[y - 1]
        left = np.concatenate(([np.inf], prev[:-1]))
        right = np.concatenate((prev[1:], [np.inf]))
        stack = np.stack((left, prev, right))
        choice = np.argmin(stack, axis=0)
        cost[y] += stack[choice, np.arange(w)]
        back[y] = np.arange(w) + choice - 1
    path = np.zeros(h, dtype=np.int64)
    path[-1] = int(np.argmin(cost[-1]))
    for y in range(h - 1, 0, -1):
        path[y - 1] = back[y, path[y]]
    return path


def _fix_vertical_seam(tile, x0, weights, band_frac=0.25, overlap_frac=0.35, exclude=None):
    """Replace a band around column ``x0`` by a matching strip of the same tile.

    The strip is chosen by the smallest squared difference over both overlaps
    (all candidate columns at least a band away from the seam), then joined to
    the tile along minimum-error cuts with a 2 px feather.
    """
    np = _np()
    h, w = tile.shape[:2]
    band = max(8, int(w * band_frac)) // 2 * 2
    ov = max(3, int(band * overlap_frac))
    a, b = x0 - band // 2, x0 + band // 2
    guide = (tile * weights).sum(axis=2)
    target_l = guide[:, a:a + ov]
    target_r = guide[:, b - ov:b]
    candidates = [c for c in range(0, w - band) if c + band <= a - band // 2 or c >= b + band // 2]
    if exclude is not None:
        candidates = [c for c in candidates if not exclude(c, band)]
    if not candidates:
        return tile, 0.0
    cand = np.array(candidates)
    score = np.zeros(len(cand))
    for j in range(ov):
        score += ((guide[:, cand + j] - target_l[:, j:j + 1]) ** 2).sum(axis=0)
        score += ((guide[:, cand + band - ov + j] - target_r[:, j:j + 1]) ** 2).sum(axis=0)
    c = int(cand[int(np.argmin(score))])
    strip = tile[:, c:c + band]
    sguide = guide[:, c:c + band]
    mask = np.ones((h, band))
    path_l = _min_cut((sguide[:, :ov] - target_l) ** 2)
    path_r = _min_cut((sguide[:, band - ov:] - target_r) ** 2)
    cols = np.arange(band)[None, :]
    mask[cols < path_l[:, None]] = 0.0
    mask[cols > (band - ov + path_r)[:, None]] = 0.0
    # Feather the cut by two pixels.
    kernel = np.array([1, 2, 3, 2, 1], dtype=np.float64)
    kernel /= kernel.sum()
    padded = np.pad(mask, ((0, 0), (2, 2)), mode="edge")
    mask = sum(kernel[i] * padded[:, i:i + band] for i in range(5))
    out = tile.copy()
    region = out[:, a:b]
    out[:, a:b] = region * (1 - mask[..., None]) + strip * mask[..., None]
    err = float(np.sqrt(score.min() / (2 * ov * h)))
    return out, err


def repair_seams(tile, weights=None, seam_threshold=1.8, period=None):
    """Make an (H, W, C) or (H, W) tile seamless (offset by half, quilt the two centre seams).

    ``weights`` (one per channel) set how much each channel counts when
    matching. Returns (tile, report).
    """
    np = _np()
    arr = np.asarray(tile, dtype=np.float64)
    flat = arr.ndim == 2
    if flat:
        arr = arr[..., None]
    weights = np.ones(arr.shape[2]) if weights is None else np.asarray(weights, dtype=np.float64)
    weights = weights / weights.sum()
    h, w = arr.shape[:2]
    before = seam_score(arr)
    jumps_before = max_jump((arr * weights).sum(axis=2), period)
    out = np.roll(arr, (h // 2, w // 2), axis=(0, 1))
    cuts = {"x": [], "y": []}
    errors = []
    for axis in ("x", "y"):
        work = out if axis == "x" else np.transpose(out, (1, 0, 2))
        width = work.shape[1]
        # The original edge (now the centre line) first, then any seam the source
        # already had elsewhere (generated tiles sometimes carry one inside).
        work, err = _fix_vertical_seam(work, width // 2, weights)
        cuts[axis].append(width // 2)
        errors.append(round(err, 4))
        for _ in range(3):
            seams = _seam_columns((work * weights).sum(axis=2), threshold=seam_threshold, period=period)
            if not seams:
                break
            # Move the seam to the centre (the tile stays a tile) and quilt it there.
            work = np.roll(work, width // 2 - seams[0], axis=1)
            work, err = _fix_vertical_seam(work, width // 2, weights)
            cuts[axis].append(int(seams[0]))
            errors.append(round(err, 4))
        out = work if axis == "x" else np.transpose(work, (1, 0, 2))
    guide = (out * weights).sum(axis=2)
    report = {"edge_before": [round(v, 2) for v in before], "max_jump_before": [round(v, 2) for v in jumps_before],
              "max_jump_after": [round(v, 2) for v in max_jump(guide, period)], "cuts": cuts, "cut_rms": errors}
    return (out[..., 0] if flat else out), report


def resample(img, size, periodic=True):
    """Resize a tile to ``size`` x ``size``; periodic resampling keeps it seamless."""
    np = _np()
    from PIL import Image
    arr = np.asarray(img, dtype=np.float64)
    channels = [arr] if arr.ndim == 2 else [arr[..., i] for i in range(arr.shape[2])]
    out = []
    for ch in channels:
        h, w = ch.shape
        pad = max(4, h // 32) if periodic else 0
        src = np.pad(ch, pad, mode="wrap") if pad else ch
        scale = size / w
        big = int(round(src.shape[1] * scale))
        im = Image.fromarray(src.astype(np.float32), mode="F").resize((big, big), Image.LANCZOS)
        res = np.asarray(im, dtype=np.float64)
        p = int(round(pad * scale))
        res = res[p:p + size, p:p + size]
        if res.shape != (size, size):
            res = np.asarray(Image.fromarray(res.astype(np.float32), mode="F").resize((size, size), Image.LANCZOS))
        out.append(res)
    return out[0] if arr.ndim == 2 else np.stack(out, axis=-1)


def height_to_normal(height, patch_mm, relief_mm):
    """Tangent-space normal map (OpenGL / glTF: +X right, +Y up the image) from a 0..1 height tile.

    ``relief_mm`` is the height of a full 0..1 step; ``patch_mm`` the tile's real
    width, so the slope is physical. Returns RGB floats in 0..1.
    """
    np = _np()
    h = np.asarray(height, dtype=np.float64)
    size = h.shape[1]
    px_mm = patch_mm / size
    hm = (h - h.mean()) / max(h.std(), 1e-6) * 0.25 * relief_mm  # +-2 sigma spans the relief
    dx = (np.roll(hm, -1, axis=1) - np.roll(hm, 1, axis=1)) / (2 * px_mm)
    drow = (np.roll(hm, -1, axis=0) - np.roll(hm, 1, axis=0)) / (2 * px_mm)
    n = np.stack((-dx, drow, np.ones_like(hm)), axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n * 0.5 + 0.5


def mask_period(mask, axis):
    """Period (pixels) of a graphic mask along ``axis`` from its autocorrelation, or None."""
    np = _np()
    m = np.asarray(mask, dtype=np.float64)
    if m.ndim == 3:
        m = m @ np.array([1.0, 2.0, 4.0])
    # Remove what does not change along the axis (e.g. vertical bands when measuring rows).
    profile = m - m.mean(axis=axis, keepdims=True)
    spec = np.fft.rfft(profile, axis=axis)
    ac = np.fft.irfft(np.abs(spec) ** 2, axis=axis)
    ac = ac.mean(axis=1 - axis)
    n = len(ac)
    ac = ac[: n // 2]
    ac /= max(ac[0], 1e-9)
    # The smallest lag that repeats the pattern almost exactly (sub-bands of a tartan
    # correlate only partly, so a plain "first peak" would pick them).
    peaks = [lag for lag in range(3, len(ac) - 1) if ac[lag] >= ac[lag - 1] and ac[lag] >= ac[lag + 1]]
    if not peaks:
        return None
    best = max(ac[lag] for lag in peaks)
    if best < 0.5:
        return None
    for lag in peaks:
        if ac[lag] >= 0.9 * best:
            # refine with a parabola
            y0, y1, y2 = ac[lag - 1], ac[lag], ac[lag + 1]
            denom = y0 - 2 * y1 + y2
            shift = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-9 else 0.0
            return lag + shift
    return None


def clean_mask(img, kind):
    """Snap a generated mask to its palette: 'mask' -> 0/1, 'rgb' -> one-hot R, G, B."""
    np = _np()
    arr = np.asarray(img, dtype=np.float64)
    if kind == "mask":
        return (luminance(arr) > 0.5).astype(np.float64)
    labels = np.argmax(arr[..., :3], axis=2)
    # 3 x 3 majority filter removes one-pixel fringes left at region borders.
    votes = np.zeros(labels.shape + (3,))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            shifted = np.roll(labels, (dy, dx), axis=(0, 1))
            for k in range(3):
                votes[..., k] += shifted == k
    labels = np.argmax(votes, axis=2)
    return np.eye(3)[labels]


def best_repeat_window(arr, axis, period):
    """(start, length) of the window along ``axis`` that wraps best: a whole number of periods
    whose first line matches the line just after its end. Generated patterns are not exactly
    periodic, so the window is searched over offsets and lengths near k periods."""
    np = _np()
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim == 3:
        a = a @ np.array([1.0, 2.0, 4.0])
    lines = a if axis == 0 else a.T          # lines[i] = row i (axis 0) or column i (axis 1)
    n = lines.shape[0]
    best = None
    for k in range(1, int(n // period) + 1):
        for length in range(int(round(k * period)) - 3, int(round(k * period)) + 4):
            if length < 8 or length >= n:
                continue
            starts = np.arange(0, n - length)
            err = np.abs(lines[starts] - lines[starts + length]).mean(axis=1)
            i = int(np.argmin(err))
            score = float(err[i]) - 0.0005 * k   # prefer more periods when nearly equal
            if best is None or score < best[0]:
                best = (score, int(starts[i]), length)
    return (0, n) if best is None else (best[1], best[2])


def crop_to_periods(arr, periods):
    """Crop to a well-wrapping whole number of periods per axis (x period, y period); None = keep."""
    h, w = arr.shape[:2]
    px, py = periods
    # An axis that already holds a whole number of periods is kept as it is.
    whole = lambda p, n: p is None or abs(n / p - round(n / p)) < 0.03  # noqa: E731
    x0, out_w = (0, w) if whole(px, w) else best_repeat_window(arr, 1, px)
    y0, out_h = (0, h) if whole(py, h) else best_repeat_window(arr, 0, py)
    return arr[y0:y0 + out_h, x0:x0 + out_w], (out_w / w, out_h / h)


# ---------------------------------------------------------------- file IO

def read_rgb(path):
    np = _np()
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.float64) / 255.0


def sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _to8(arr):
    np = _np()
    return (np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)


def save_jpeg_grey(arr, path, quality=88):
    from PIL import Image
    Image.fromarray(_to8(arr), mode="L").save(path, quality=quality, optimize=True, progressive=False)


def save_png(arr, path):
    from PIL import Image
    a = _to8(arr)
    Image.fromarray(a, mode="L" if a.ndim == 2 else "RGB").save(path, optimize=True)


# ---------------------------------------------------------------- processing

def process_fabric(name, src: Path, out_dir: Path, recipe: dict) -> dict:
    np = _np()
    files = {"albedo": src / f"{name}_albedo.png", "height": src / f"{name}_height.png",
             "roughness": src / f"{name}_roughness.png"}
    if not files["albedo"].is_file() or not files["height"].is_file():
        raise FileNotFoundError(f"{name}: needs {name}_albedo.png and {name}_height.png in {src}")
    albedo = luminance(read_rgb(files["albedo"]))
    height = luminance(read_rgb(files["height"]))
    rough = luminance(read_rgb(files["roughness"])) if files["roughness"].is_file() else None
    size = albedo.shape[0]
    if height.shape != albedo.shape:
        height = resample(height, size)
    if rough is not None and rough.shape != albedo.shape:
        rough = resample(rough, size)
    report: dict[str, Any] = {"source_size": list(albedo.shape),
                              "source_edge_score": {"albedo": [round(v, 2) for v in seam_score(albedo)],
                                                    "height": [round(v, 2) for v in seam_score(height)]}}

    albedo = flat_field(albedo)
    height = flat_field(height, multiplicative=False)
    period = dominant_period(height)
    sigma = float(min(max(0.6 * period, 2.0), 24.0))
    albedo_low = blur(albedo, sigma)
    weave = height - blur(height, sigma)
    detail = albedo - albedo_low
    k = detail.std() / max(weave.std(), 1e-6)
    aligned = albedo_low + k * weave
    report["weave_period_px"] = round(period, 1)
    report["align_sigma_px"] = round(sigma, 1)
    channels = [aligned, height]
    weights = [1.0, 1.0]
    if rough is not None:
        rough = blur(flat_field(rough), sigma)
        channels.append(rough)
        weights.append(0.2)
    stack = np.stack(channels, axis=-1)
    stack, seam = repair_seams(stack, weights, period=period)
    report["seams"] = seam
    aligned, height = stack[..., 0], stack[..., 1]
    rough = stack[..., 2] if rough is not None else None

    # Albedo: fixed mean brightness (sRGB-encoded), contrast kept.
    for _ in range(4):  # rescale again after clipping highlights, until the mean holds
        aligned = np.clip(aligned * (ALBEDO_MEAN_SRGB / max(aligned.mean(), 1e-6)), 0.0, 1.0)
    albedo_out = np.clip(resample(aligned, ALBEDO_SIZE), 0, 1)
    height_out = resample(height, NORMAL_SIZE)
    normal = height_to_normal(height_out, recipe["patch_cm"] * 10.0, recipe["relief_mm"])

    out_dir.mkdir(parents=True, exist_ok=True)
    save_jpeg_grey(albedo_out, out_dir / "albedo.jpg")
    save_png(normal, out_dir / "normal.png")
    maps = {"albedo": "albedo.jpg", "normal": "normal.png"}
    entry = {"label": recipe["label"], "patch_cm": recipe["patch_cm"], "use": recipe["use"],
             "roughness": recipe["roughness"], "sheen": recipe["sheen"], "relief_mm": recipe["relief_mm"],
             "albedo_mean_linear": round(float(srgb_to_linear(_to8(albedo_out) / 255.0).mean()), 4),
             "albedo_mean_srgb": round(float((_to8(albedo_out) / 255.0).mean()), 4)}
    if rough is not None:
        # Keep the map's variation around the recipe roughness (mean 0.5 in the file).
        rough_out = resample(rough, ROUGHNESS_SIZE)
        rough_out = 0.5 + (rough_out - rough_out.mean()) / max(rough_out.std(), 1e-6) * 0.12
        save_png(np.clip(rough_out, 0, 1), out_dir / "roughness.png")
        maps["roughness"] = "roughness.png"
        entry["roughness_map_mean"] = 0.5
    entry["maps"] = maps
    entry["sizes"] = {"albedo": ALBEDO_SIZE, "normal": NORMAL_SIZE, **({"roughness": ROUGHNESS_SIZE} if rough is not None else {})}
    out_period = period * ALBEDO_SIZE / size
    entry["check"] = {"albedo_max_jump": [round(v, 2) for v in max_jump(albedo_out, out_period)],
                      "normal_max_jump": [round(v, 2) for v in max_jump(normal, period * NORMAL_SIZE / size)]}
    entry["provenance"] = {"inputs": {k: sha256(p) for k, p in files.items() if p.is_file()},
                           "outputs": {k: sha256(out_dir / v) for k, v in maps.items()},
                           "processing": report}
    return entry


def process_pattern(name, src: Path, out_dir: Path, recipe: dict) -> dict:
    np = _np()
    path = src / f"{name}.png"
    if not path.is_file():
        raise FileNotFoundError(f"pattern {name}: {path.name} not found in {src}")
    raw = read_rgb(path)
    clean = clean_mask(raw, recipe["kind"])
    px, py = mask_period(clean, 1), mask_period(clean, 0)
    cropped, fraction = crop_to_periods(clean, (px, py))
    # Area-filter resampling of the snapped mask: soft, anti-aliased edges. The crop may
    # be slightly non-square; the patch keeps its real width and height.
    out = resample_rect(cropped, PATTERN_SIZE)
    out = np.clip(out, 0, 1)
    if out.ndim == 3:
        out = out / np.maximum(out.sum(axis=2, keepdims=True), 1e-6)
    out_dir.mkdir(parents=True, exist_ok=True)
    save_png(out, out_dir / f"{name}.png")
    patch = recipe["patch_cm"]
    return {"label": recipe["label"], "kind": recipe["kind"], "file": f"{name}.png",
            "patch_cm": [round(patch * fraction[0], 3), round(patch * fraction[1], 3)],
            "colors": 2 if recipe["kind"] == "mask" else 3,
            "check": {"period_residual": period_residual(out),
                      "source_periods_px": [round(p, 2) if p else None for p in (px, py)]},
            "provenance": {"input": sha256(path), "output": sha256(out_dir / f"{name}.png"),
                           "processing": "palette snapped (" + ("black/white" if recipe["kind"] == "mask" else
                                                               "pure red, green, blue; 3 x 3 majority filter")
                                         + "), cropped to whole periods, area-resampled to "
                                         f"{PATTERN_SIZE} px"}}


def period_residual(tile):
    """Mean difference between a tile and itself shifted by its own period, per axis (0 = exact repeat).

    A seamless pattern tile holds whole periods, so the shift crosses the tile
    edge without a jump. Returns None for an axis without a detectable period.
    """
    np = _np()
    out = []
    for axis in (1, 0):
        p = mask_period(tile, axis)
        if not p:
            out.append(None)
            continue
        shifted = np.roll(tile, -int(round(p)), axis=axis)
        out.append(round(float(np.abs(tile - shifted).mean()), 4))
    return out


def resample_rect(arr, size):
    """Resize a non-square periodic crop to size x size (the patch keeps its real width and height)."""
    np = _np()
    from PIL import Image
    channels = [arr] if arr.ndim == 2 else [arr[..., i] for i in range(arr.shape[2])]
    out = [np.asarray(Image.fromarray(c.astype(np.float32), mode="F").resize((size, size), Image.BOX))
           for c in channels]
    return out[0] if arr.ndim == 2 else np.stack(out, axis=-1)


def _dir_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def build_library(src: Path, root: Path, only: list[str] | None = None, progress=None) -> dict:
    """Process every fabric and pattern found in ``src`` into ``root/assets``."""
    from . import CREDIT, LICENSE_ID
    fabrics_dir = root / "assets" / "fabrics"
    patterns_dir = root / "assets" / "patterns"
    index_path = fabrics_dir / "fabrics.json"
    pattern_index_path = patterns_dir / "patterns.json"
    old = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
    old_p = json.loads(pattern_index_path.read_text(encoding="utf-8")) if pattern_index_path.is_file() else {}
    fabrics = dict(old.get("fabrics", {}))
    patterns = dict(old_p.get("patterns", {}))
    todo_f = [n for n in FABRICS if (src / f"{n}_albedo.png").is_file() and (not only or n in only)]
    todo_p = [n for n in PATTERNS if (src / f"{n}.png").is_file() and (not only or n in only)]
    total = max(1, len(todo_f) + len(todo_p))
    for index, name in enumerate(todo_f):
        if progress:
            progress.emit("fabrics", f"processing {name}", index / total)
        fabrics[name] = process_fabric(name, src, fabrics_dir / name, FABRICS[name])
    for index, name in enumerate(todo_p):
        if progress:
            progress.emit("patterns", f"processing {name}", (len(todo_f) + index) / total)
        patterns[name] = process_pattern(name, src, patterns_dir, PATTERNS[name])
    common = {"schema_version": 1, "license": LICENSE_ID, "credit": CREDIT, "date": SOURCE_DATE,
              "provenance": PROVENANCE}
    fabric_doc = dict(common, description=(
        "Seamless, tintable fabric tiles: neutral grey albedo (mean sRGB "
        f"{ALBEDO_MEAN_SRGB}), tangent-space normal map (OpenGL/glTF convention), optional roughness "
        "variation (mean 0.5 around the fabric's roughness). patch_cm is the real width of one tile."),
        fabrics={k: fabrics[k] for k in sorted(fabrics)})
    pattern_doc = dict(common, description=(
        "Tileable pattern masks. kind 'mask': white = colour A, black = colour B. kind 'rgb': red, green "
        "and blue regions = colours A, B and C. patch_cm is the real [width, height] of one tile."),
        patterns={k: patterns[k] for k in sorted(patterns)})
    fabrics_dir.mkdir(parents=True, exist_ok=True)
    patterns_dir.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(fabric_doc, indent=2) + "\n", encoding="utf-8")
    pattern_index_path.write_text(json.dumps(pattern_doc, indent=2) + "\n", encoding="utf-8")
    size = _dir_bytes(fabrics_dir) + _dir_bytes(patterns_dir)
    if progress:
        progress.emit("done", f"fabric library: {len(fabrics)} fabrics, {len(patterns)} patterns, "
                      f"{size / 1e6:.1f} MB", 1.0)
    return {"ok": True, "fabrics": sorted(todo_f), "patterns": sorted(todo_p), "bytes": size,
            "index": "assets/fabrics/fabrics.json", "pattern_index": "assets/patterns/patterns.json"}


def main(argv=None) -> int:
    """Command line: rebuild the library; prints JSON progress lines and a final result line."""
    import argparse
    import sys
    import traceback

    from . import KIT_ROOT
    from .progress import Progress

    parser = argparse.ArgumentParser(prog="python -m tak.pipeline.fabrics", description=(
        "Rebuild assets/fabrics and assets/patterns from source swatches (needs NumPy and Pillow)."))
    parser.add_argument("--src", type=Path, required=True,
                        help="folder with <fabric>_albedo.png, <fabric>_height.png, [<fabric>_roughness.png] and masks")
    parser.add_argument("--out-root", type=Path, default=KIT_ROOT, help="kit root that receives assets/")
    parser.add_argument("--only", default="", help="comma-separated fabric or pattern names")
    parser.add_argument("--debug", action="store_true", help="print tracebacks on stderr")
    args = parser.parse_args(argv)
    progress = Progress()
    try:
        only = [n.strip() for n in args.only.split(",") if n.strip()] or None
        result = build_library(args.src, args.out_root, only=only, progress=progress)
    except Exception as exc:  # noqa: BLE001 - reported as a result line
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        progress.emit("fabrics", f"failed: {exc}", 1.0)
        progress.result({"ok": False, "error": str(exc)})
        return 1
    progress.result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
