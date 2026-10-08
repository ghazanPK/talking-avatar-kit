"""Skin maps baked in UV space: region masks, detail height -> normal, roughness and albedo layers.

The skin is one glTF material (one albedo, one normal and one roughness
texture), so region-dependent detail is baked into those textures instead of
being tiled at run time:

1. ``compute_regions`` (before MPFB removes its helper geometry) derives soft
   per-vertex region weights from the body: face, lips, palms/soles, body,
   cheeks, nose, forehead, chin, under-eye, ears, knuckles, elbows, knees and
   nails. It uses MakeHuman vertex groups (``lips``, ``ears``, nails), the
   MakeHuman joint helpers (eyes, mouth, elbows, knees, finger joints) and the
   rig's skin weights, so it works for any MakeHuman body. The weights are
   stored as point attributes ``tak_region_<name>``.
2. ``bake`` rasterises those weights into UV space and composes:

   * normal map: the skin's own normal map (if the MakeHuman skin has one)
     plus the detail height slots ``face_pores_height``, ``body_skin_height``,
     ``palm_skin_height`` and ``lips_height``, each a seamless tile, repeated
     ``tiling`` times across the UV square, converted from height to slopes
     and applied only inside its region (face, body, palms/soles, lips);
   * albedo: the skin texture with islands padded, the ``color_variation``
     slot as a low-strength multiply, region tints (cheek, nose and ear
     redness, under-eye shadow, knuckles, elbows, knees) and a faint cavity
     darkening from the detail heights;
   * roughness: a base value with per-region offsets (oilier T-zone, matte
     cheeks, glossier lips and nails, rougher palms, knuckles, elbows and
     knees), the ``roughness_variation`` slot, and the skin's specular map
     when it has one.

Every slot takes ``{"source": "procedural"}`` (the default, generated here
from a fixed seed) or a path relative to the repository root to a seamless
tileable PNG. Builds are deterministic.
"""
import math
from pathlib import Path

import bpy
import numpy as np

HEIGHT_SLOTS = ("face_pores_height", "body_skin_height", "palm_skin_height", "lips_height")
SLOTS = HEIGHT_SLOTS + ("color_variation", "roughness_variation")
SLOT_REGION = {"face_pores_height": "face", "body_skin_height": "body",
               "palm_skin_height": "palms", "lips_height": "lips"}
REGIONS = ("face", "lips", "palms", "body", "cheeks", "nose", "forehead", "chin", "under_eye",
           "ears", "knuckles", "elbows", "knees", "nails")
ATTR = "tak_region_"

# strength: slope scale (height slots), relative albedo change (color_variation)
# or roughness amplitude (roughness_variation). tile_mm: the size one tile covers
# on the body (converted to repeats with the region's UV scale); "tiling" instead
# gives the repeats across the UV square directly.
DEFAULT_DETAIL = {
    "face_pores_height": {"source": "procedural", "strength": 0.12, "tile_mm": 110},
    "body_skin_height": {"source": "procedural", "strength": 0.12, "tile_mm": 140},
    "palm_skin_height": {"source": "procedural", "strength": 0.2, "tile_mm": 60},
    # The MakeHuman UV layout lays the head on its side (crown toward -U): rotate face-up tiles.
    "lips_height": {"source": "procedural", "strength": 0.2, "tile_mm": 40, "rotate": 90},
    "color_variation": {"source": "procedural", "strength": 0.06, "tile_mm": 160},
    "roughness_variation": {"source": "procedural", "strength": 0.05, "tile_mm": 100},
}
# Region whose UV scale converts tile_mm for each slot.
SLOT_SCALE_REGION = dict(SLOT_REGION, color_variation="face", roughness_variation="face")
# tint: albedo multiplier at full weight (scaled by "amount"); roughness: offset
# added at full weight; detail: multiplier of the detail-normal strength there.
DEFAULT_REGIONS = {
    "face": {"roughness": 0.0},
    "lips": {"tint": [1.0, 0.96, 0.96], "roughness": -0.14},
    "palms": {"tint": [1.03, 1.0, 0.98], "roughness": 0.08},
    "cheeks": {"tint": [1.02, 0.92, 0.9], "roughness": 0.04, "detail": 1.3},
    "nose": {"tint": [1.02, 0.93, 0.91], "roughness": -0.06, "detail": 1.6},
    "forehead": {"roughness": -0.05},
    "chin": {"roughness": -0.03, "detail": 1.2},
    "under_eye": {"tint": [0.93, 0.9, 0.94], "roughness": -0.02, "detail": 0.4},
    "ears": {"tint": [1.02, 0.92, 0.9], "roughness": 0.02},
    "knuckles": {"tint": [0.9, 0.86, 0.86], "roughness": 0.07},
    "elbows": {"tint": [0.92, 0.89, 0.88], "roughness": 0.1},
    "knees": {"tint": [0.92, 0.89, 0.88], "roughness": 0.1},
    "nails": {"tint": [1.04, 1.0, 1.0], "roughness": -0.22},
}
MASK_SIZE = 1024
REFERENCE_SIZE = 2048  # slope strengths are defined at this normal-map size


def detail_config(cfg):
    """Merge a spec's ``skin.detail`` over the defaults (slot -> settings)."""
    out = {}
    for slot in SLOTS:
        merged = dict(DEFAULT_DETAIL[slot])
        user = (cfg or {}).get(slot, {})
        if "tiling" in user and "tile_mm" not in user:
            merged.pop("tile_mm", None)
        merged.update(user)
        out[slot] = merged
    return out


def region_config(cfg):
    out = {}
    for name in REGIONS:
        merged = dict(DEFAULT_REGIONS.get(name, {}))
        merged.update((cfg or {}).get(name, {}))
        out[name] = merged
    return out


# --------------------------------------------------------------------------- per-vertex regions

def _basis(obj):
    mesh = obj.data
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    if mesh.shape_keys:
        mesh.shape_keys.key_blocks[0].data.foreach_get("co", co)
    else:
        mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    world = np.array(obj.matrix_world)
    return co @ world[:3, :3].T + world[:3, 3]


def _normals(obj, co):
    mesh = obj.data
    normals = np.zeros_like(co)
    mesh.calc_loop_triangles()
    tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
    mesh.loop_triangles.foreach_get("vertices", tris)
    tris = tris.reshape(-1, 3)
    face = np.cross(co[tris[:, 1]] - co[tris[:, 0]], co[tris[:, 2]] - co[tris[:, 0]])
    for k in range(3):
        np.add.at(normals, tris[:, k], face)
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def _group_weights(obj, test):
    """Sum of the weights of the vertex groups whose name passes ``test``, per vertex."""
    wanted = {g.index for g in obj.vertex_groups if test(g.name)}
    out = np.zeros(len(obj.data.vertices), dtype=np.float64)
    if not wanted:
        return out
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group in wanted:
                out[v.index] += g.weight
    return np.clip(out, 0, 1)


def _landmarks(obj, co):
    """Centroids of MakeHuman joint helper cubes (``joint-*`` vertex groups)."""
    names = {g.index: g.name for g in obj.vertex_groups if g.name.startswith("joint-")}
    acc = {}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group in names and g.weight > 0.5:
                acc.setdefault(names[g.group], []).append(v.index)
    return {name: co[idx].mean(axis=0) for name, idx in acc.items()}


def _smooth(x, lo, hi):
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _blob(co, center, radii):
    """Soft ellipsoid: 1 inside, falling to 0 at the radii (x, y, z in world units)."""
    d = (co - center) / np.asarray(radii)
    r = np.sqrt((d * d).sum(axis=1))
    return 1.0 - _smooth(r, 0.45, 1.0)


def compute_regions(obj):
    """Store soft region weights as point attributes on the body (call before helpers are removed)."""
    co = _basis(obj)
    n = _normals(obj, co)
    lm = _landmarks(obj, co)
    need = ("joint-l-eye", "joint-r-eye", "joint-mouth")
    missing = [k for k in need if k not in lm]
    if missing:
        raise RuntimeError(f"body has no MakeHuman joint helpers {missing}")
    # Blender world: +Z up, -Y is the character's front, +X the character's left.
    eye_l, eye_r = lm["joint-l-eye"], lm["joint-r-eye"]
    iod = float(np.linalg.norm(eye_l - eye_r))
    mid = (eye_l + eye_r) / 2
    front = np.array([0.0, -1.0, 0.0])
    facing = n @ front
    rel = (co - mid) / iod
    dx, dz, dfront = rel[:, 0], rel[:, 2], -rel[:, 1]
    body_group = _group_weights(obj, lambda name: name == "body")
    on_body = body_group > 0.5

    regions = {}
    # Head: above the jaw line (chin about 1.9 eye distances below the eyes), minus the underside of the jaw.
    head = _smooth(dz, -2.25, -1.95) * (1 - _smooth(-n[:, 2], 0.45, 0.8) * _smooth(-dz, 1.3, 1.6))
    ellipse = np.sqrt((dx / 1.3) ** 2 + ((dz + 0.45) / 1.9) ** 2)
    regions["face"] = head * (1 - _smooth(ellipse, 0.85, 1.05)) * _smooth(facing, -0.2, 0.25) \
        * _smooth(dfront, -1.2, -0.7)
    lips = _group_weights(obj, lambda name: name == "lips")
    regions["lips"] = lips
    nails = _group_weights(obj, lambda name: name in ("fingernails", "toenails"))
    regions["nails"] = nails
    regions["ears"] = _group_weights(obj, lambda name: name == "ears")

    # Palms and soles: hand/foot skin facing away from the nails / toward the ground.
    palms = np.zeros(len(co))
    for side in ("l", "r"):
        hand = _group_weights(obj, lambda name, s=side: name.endswith("_" + s) and name.split("_")[0] in
                              ("hand", "thumb", "index", "middle", "ring", "pinky"))
        keys = [f"joint-{side}-hand", f"joint-{side}-finger-2-1", f"joint-{side}-finger-5-1",
                f"joint-{side}-finger-3-4"]
        if not all(k in lm for k in keys):
            continue
        wrist, index, pinky, tip = (lm[k] for k in keys)
        palm_dir = np.cross(index - pinky, tip - wrist)
        palm_dir /= np.linalg.norm(palm_dir)
        nail_idx = np.nonzero((nails > 0.5) & (hand > 0.5))[0]
        if len(nail_idx):
            centre = co[hand > 0.5].mean(axis=0)
            if (co[nail_idx].mean(axis=0) - centre) @ palm_dir > 0:
                palm_dir = -palm_dir
        palms = np.maximum(palms, _smooth(hand, 0.3, 0.8) * _smooth(n @ palm_dir, 0.05, 0.45) * (1 - nails))
    ground = co[:, 2].min()
    feet = _group_weights(obj, lambda name: name.split("_")[0] in ("foot", "ball"))
    soles = _smooth(feet, 0.3, 0.8) * _smooth(-n[:, 2], 0.4, 0.8) * (1 - _smooth(co[:, 2] - ground, 0.3 * iod, 0.6 * iod))
    regions["palms"] = np.maximum(palms, soles)

    # Facial areas in eye-distance units around the eyes.
    face = regions["face"]
    cheeks = np.zeros(len(co))
    under = np.zeros(len(co))
    for eye, sign in ((eye_l, 1.0), (eye_r, -1.0)):
        cheeks = np.maximum(cheeks, _blob(co, eye + np.array([0.18 * sign, -0.3, -0.85]) * iod,
                                          (0.62 * iod, 2.0 * iod, 0.55 * iod)))
        under = np.maximum(under, _blob(co, eye + np.array([0.02 * sign, -0.3, -0.36]) * iod,
                                        (0.42 * iod, 2.0 * iod, 0.2 * iod)))
    regions["cheeks"] = cheeks * _smooth(facing, 0.0, 0.4) * face
    regions["under_eye"] = under * _smooth(facing, 0.0, 0.4) * face
    centre = (np.abs(dx) < 0.35) & (dz < -0.2) & (dz > -1.2) & on_body
    tip = co[centre][np.argmax(dfront[centre])] if centre.any() else mid
    regions["nose"] = _blob(co, tip + np.array([0, 0.1, 0.05]) * iod, (0.42 * iod, 0.9 * iod, 0.5 * iod)) * face
    regions["forehead"] = (1 - _smooth(np.abs(dx), 0.6, 1.1)) * _smooth(dz, 0.35, 0.65) * face
    lip_idx = np.nonzero(lips > 0.5)[0]
    mouth = co[lip_idx].mean(axis=0) if len(lip_idx) else lm["joint-mouth"]
    regions["chin"] = _blob(co, mouth + np.array([0, 0.0, -0.8]) * iod, (0.6 * iod, 1.0 * iod, 0.45 * iod)) * face

    knuckles = np.zeros(len(co))
    for name, pos in lm.items():
        parts = name.split("-")  # joint-l-finger-2-2
        if len(parts) == 5 and parts[2] == "finger" and parts[4] in ("2", "3") and parts[3] != "1":
            knuckles = np.maximum(knuckles, _blob(co, pos, (0.16 * iod,) * 3))
    regions["knuckles"] = knuckles * (1 - regions["palms"]) * (1 - nails)
    elbows = np.zeros(len(co))
    knees = np.zeros(len(co))
    for side in ("l", "r"):
        if f"joint-{side}-elbow" in lm:
            elbows = np.maximum(elbows, _blob(co, lm[f"joint-{side}-elbow"] + np.array([0, 0.25, 0]) * iod,
                                              (0.75 * iod,) * 3) * _smooth(n[:, 1], -0.1, 0.4))
        if f"joint-{side}-knee" in lm:
            knees = np.maximum(knees, _blob(co, lm[f"joint-{side}-knee"] - np.array([0, 0.4, 0]) * iod,
                                            (0.9 * iod,) * 3) * _smooth(facing, -0.1, 0.4))
    regions["elbows"], regions["knees"] = elbows, knees

    # Detail partition: lips > palms > face > body, summing to one.
    regions["lips"] = np.clip(regions["lips"], 0, 1)
    regions["palms"] = np.clip(regions["palms"], 0, 1) * (1 - regions["lips"])
    regions["face"] = np.clip(face, 0, 1) * (1 - regions["lips"]) * (1 - regions["palms"])
    regions["body"] = np.clip(1 - regions["lips"] - regions["palms"] - regions["face"], 0, 1)

    mesh = obj.data
    for name in REGIONS:
        attr = mesh.attributes.get(ATTR + name) or mesh.attributes.new(ATTR + name, "FLOAT", "POINT")
        attr.data.foreach_set("value", np.clip(regions[name], 0, 1).astype(np.float32))
    return {"eye_distance_m": round(iod, 4)}


def clear_regions(obj):
    for name in REGIONS:
        attr = obj.data.attributes.get(ATTR + name)
        if attr is not None:
            obj.data.attributes.remove(attr)


# --------------------------------------------------------------------------- UV rasterisation

def _uv_triangles(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    loops = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
    mesh.loop_triangles.foreach_get("loops", loops)
    uv = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    mesh.uv_layers.active.data.foreach_get("uv", uv)
    verts = np.empty(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", verts)
    loops = loops.reshape(-1, 3)
    return uv.reshape(-1, 2)[loops], verts[loops]


def rasterize(tri_uv, tri_val, size):
    """Barycentric rasterisation of per-corner values. Returns (image h x w x c, coverage)."""
    channels = tri_val.shape[2]
    out = np.zeros((size, size, channels), dtype=np.float32)
    cov = np.zeros((size, size), dtype=bool)
    p = tri_uv.astype(np.float64) * size - 0.5  # pixel centres at integers
    lo = np.floor(p.min(axis=1)).astype(np.int64)
    hi = np.ceil(p.max(axis=1)).astype(np.int64)
    extent = (hi - lo).max(axis=1) + 1
    a, b, c = p[:, 0], p[:, 1], p[:, 2]
    den = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    ok = np.abs(den) > 1e-12
    previous = 0
    for bucket in (2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 4096):
        sel = np.nonzero(ok & (extent > previous) & (extent <= bucket))[0]
        previous = bucket
        step = max(1, 1_000_000 // (bucket * bucket))
        for start in range(0, len(sel), step):
            idx = sel[start:start + step]
            g = np.arange(bucket)
            px = lo[idx, 0][:, None, None] + g[None, None, :]
            py = lo[idx, 1][:, None, None] + g[None, :, None]
            ax, ay = a[idx, 0][:, None, None], a[idx, 1][:, None, None]
            bx, by = b[idx, 0][:, None, None], b[idx, 1][:, None, None]
            cx, cy = c[idx, 0][:, None, None], c[idx, 1][:, None, None]
            d = den[idx][:, None, None]
            l1 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / d
            l2 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / d
            l3 = 1 - l1 - l2
            inside = (l1 >= -1e-4) & (l2 >= -1e-4) & (l3 >= -1e-4) & (px >= 0) & (py >= 0) & (px < size) & (py < size)
            t, yy, xx = np.nonzero(inside)
            if not len(t):
                continue
            w = np.stack([l1[t, yy, xx], l2[t, yy, xx], l3[t, yy, xx]], axis=1)
            vals = (tri_val[idx[t]] * w[:, :, None]).sum(axis=1)
            ys, xs = py[t, yy, 0], px[t, 0, xx]
            out[ys, xs] = vals
            cov[ys, xs] = True
    return out, cov


def fill(img, cov):
    """Push-pull fill of uncovered texels from covered ones (power-of-two square images)."""
    levels = [(img * cov[..., None], cov.astype(np.float32))]
    while levels[-1][1].shape[0] > 1:
        a, w = levels[-1]
        h = a.shape[0] // 2
        a2 = a.reshape(h, 2, h, 2, -1).sum(axis=(1, 3))
        w2 = w.reshape(h, 2, h, 2).sum(axis=(1, 3))
        levels.append((a2, w2))
    a, w = levels[-1]
    value = a / np.maximum(w, 1e-8)[..., None]
    for a, w in reversed(levels[:-1]):
        up = np.repeat(np.repeat(value, 2, axis=0), 2, axis=1)
        value = np.where(w[..., None] > 0, a / np.maximum(w, 1e-8)[..., None], up)
    return np.where(cov[..., None], img, value).astype(np.float32)


def resize(img, size):
    """Bilinear resize of a (h, w, c) array to (size, size, c), clamped at the borders."""
    h, w = img.shape[:2]
    if h == size and w == size:
        return img
    if h > size and h % size == 0 and w % size == 0:
        f = h // size
        return img.reshape(size, f, size, f, -1).mean(axis=(1, 3)).astype(np.float32)

    def axis(n_in):
        x = (np.arange(size) + 0.5) * n_in / size - 0.5
        x0 = np.clip(np.floor(x).astype(np.int64), 0, n_in - 1)
        x1 = np.clip(x0 + 1, 0, n_in - 1)
        return x0, x1, np.clip(x - x0, 0, 1).astype(np.float32)
    y0, y1, fy = axis(h)
    x0, x1, fx = axis(w)
    top = img[y0][:, x0] * (1 - fx)[None, :, None] + img[y0][:, x1] * fx[None, :, None]
    bot = img[y1][:, x0] * (1 - fx)[None, :, None] + img[y1][:, x1] * fx[None, :, None]
    return (top * (1 - fy)[:, None, None] + bot * fy[:, None, None]).astype(np.float32)


def uv_scale(obj):
    """Metres per UV unit for each detail region (area-weighted over the region's triangles)."""
    tri_uv, tri_vert = _uv_triangles(obj)
    co = _basis(obj)
    p = co[tri_vert]
    world = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    e1, e2 = tri_uv[:, 1] - tri_uv[:, 0], tri_uv[:, 2] - tri_uv[:, 0]
    uv = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    out = {}
    for name in ("face", "body", "palms", "lips"):
        w = _attr(obj, ATTR + name)[tri_vert].mean(axis=1)
        out[name] = float(np.sqrt((w * world).sum() / max((w * uv).sum(), 1e-12)))
    return out


def region_maps(obj, size=MASK_SIZE):
    """Rasterise the region attributes into UV space: (size x size x regions) array and coverage."""
    tri_uv, tri_vert = _uv_triangles(obj)
    values = np.stack([np.asarray(_attr(obj, ATTR + name)) for name in REGIONS], axis=1)
    img, cov = rasterize(tri_uv, values[tri_vert].astype(np.float32), size)
    return fill(img, cov), cov


def coverage(obj, size, erode=1):
    """Texels inside UV islands at ``size``, shrunk by ``erode`` texels (island borders are re-padded)."""
    tri_uv, _ = _uv_triangles(obj)
    _, cov = rasterize(tri_uv, np.ones(tri_uv.shape[:2] + (1,), dtype=np.float32), size)
    for _ in range(erode):
        cov = cov & np.roll(cov, 1, 0) & np.roll(cov, -1, 0) & np.roll(cov, 1, 1) & np.roll(cov, -1, 1)
    return cov


def _attr(obj, name):
    attr = obj.data.attributes[name]
    out = np.empty(len(attr.data), dtype=np.float32)
    attr.data.foreach_get("value", out)
    return out


# --------------------------------------------------------------------------- detail tiles

def _band_noise(size, rng, low, high, aniso=(1.0, 1.0)):
    """Tileable band-limited noise in [-1, 1]; frequencies in cycles per tile."""
    white = rng.standard_normal((size, size))
    spec = np.fft.rfft2(white)
    fy = np.fft.fftfreq(size)[:, None] * size * aniso[1]
    fx = np.fft.rfftfreq(size)[None, :] * size * aniso[0]
    radius = np.sqrt(fx * fx + fy * fy)
    centre, width = np.log(np.sqrt(low * high)), np.log(high / low) / 2.5
    mask = np.exp(-((np.log(np.maximum(radius, 1e-3)) - centre) ** 2) / (2 * width ** 2))
    out = np.fft.irfft2(spec * mask, s=(size, size))
    return out / (np.abs(out).max() + 1e-9)


def _pits(size, rng, cell, radius=(0.7, 1.4), keep=0.75):
    """Tileable field of small round pits (pores) on a jittered grid; 0 outside, <0 in pits."""
    count = size // cell
    gy, gx = np.mgrid[0:count, 0:count]
    jitter = rng.random((count, count, 2))
    cy = (gy + jitter[..., 0]) * cell
    cx = (gx + jitter[..., 1]) * cell
    r = radius[0] + (radius[1] - radius[0]) * rng.random((count, count))
    depth = (0.4 + 0.6 * rng.random((count, count))) * (rng.random((count, count)) < keep)
    field = np.zeros((size, size))
    reach = int(math.ceil(radius[1] * 2.5))
    for oy in range(-reach, reach + 1):
        for ox in range(-reach, reach + 1):
            py = np.floor(cy).astype(np.int64) + oy
            px = np.floor(cx).astype(np.int64) + ox
            d2 = ((py + 0.5 - cy) ** 2 + (px + 0.5 - cx) ** 2) / (r * r)
            np.add.at(field, (py % size, px % size), -depth * np.exp(-d2 * 1.5))
    return field


def _creases(noise, width):
    """Thin valleys along the zero crossings of a noise field (a cell network)."""
    return -np.exp(-(noise / width) ** 2)


def procedural_tile(slot, seed, size=512):
    """Built-in seamless tiles for each slot (authored for this kit, CC BY 4.0)."""
    rng = np.random.default_rng(seed)
    if slot == "face_pores_height":
        # Pores (one per ~8 texels of the tile) on a softly undulating surface.
        h = _pits(size, rng, 8, (1.2, 2.0), 0.85) * 1.0
        h += _band_noise(size, rng, 4, 12) * 0.25
        h += _creases(_band_noise(size, rng, 10, 22), 0.1) * 0.12
    elif slot == "body_skin_height":
        h = _creases(_band_noise(size, rng, 14, 30), 0.1) * 0.35
        h += _pits(size, rng, 10, (1.2, 1.8), 0.6) * 0.7
        h += _band_noise(size, rng, 4, 12) * 0.25
    elif slot == "palm_skin_height":
        h = _creases(_band_noise(size, rng, 10, 22), 0.1) * 1.0
        h += _band_noise(size, rng, 50, 110, aniso=(1.0, 0.35)) * 0.35
        h += _creases(_band_noise(size, rng, 30, 70), 0.1) * 0.35
    elif slot == "lips_height":
        # Vertical lip wrinkles (tile up = face up; the slot's "rotate" maps it onto the UV layout).
        h = _creases(_band_noise(size, rng, 12, 40, aniso=(1.0, 0.12)), 0.18) * 1.0
        h += _band_noise(size, rng, 60, 160) * 0.2
    elif slot == "color_variation":
        lum = _band_noise(size, rng, 2, 8) * 0.6 + _band_noise(size, rng, 8, 30) * 0.4
        red = _band_noise(size, rng, 3, 12)
        speck = np.clip(_band_noise(size, rng, 40, 120), 0.55, 1.0) - 0.55
        rgb = np.stack([lum + 0.35 * red, lum - 0.1 * red, lum - 0.25 * red], axis=-1)
        rgb -= speck[..., None] * np.array([0.6, 1.0, 1.1])
        return (rgb / (np.abs(rgb).max() + 1e-9)).astype(np.float32)
    elif slot == "roughness_variation":
        h = _band_noise(size, rng, 3, 12) * 0.6 + _band_noise(size, rng, 20, 80) * 0.4
    else:
        raise KeyError(slot)
    return _normalise(h)[..., None]


def _normalise(h):
    h = h - h.mean()
    return (h / (3 * h.std() + 1e-9)).astype(np.float32)


def repair_seams(tile, band=0.25):
    """Make a nearly seamless tile seamless: offset-and-blend, one axis at a time.

    For each axis the tile is blended with a copy shifted by half its size; the
    shifted copy takes over within ``band`` of the edges (where the original's
    seam is) and the original keeps the middle (where the copy's seam is). The
    blend is variance preserving, so contrast does not drop in the blend zones.
    """
    out = tile.astype(np.float64)
    n = out.shape[0]
    x = (np.arange(n) + 0.5) / n
    w = _smooth(np.minimum(x, 1 - x), 0.0, band)
    norm = np.sqrt(w * w + (1 - w) ** 2)
    for axis in (1, 0):
        mean = out.mean(axis=(0, 1))
        shifted = np.roll(out, n // 2, axis=axis)
        weight = (w[None, :] if axis == 1 else w[:, None])[..., None]
        scale = (norm[None, :] if axis == 1 else norm[:, None])[..., None]
        out = mean + (weight * (out - mean) + (1 - weight) * (shifted - mean)) / scale
    return out.astype(np.float32)


def rotate(tile, degrees):
    turns = int(round(float(degrees) / 90.0)) % 4
    return np.rot90(tile, k=turns, axes=(0, 1)).copy() if turns else tile


def read_image(path):
    """Pixels of an image file as raw values (no colour management), shape (h, w, 3)."""
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        w, h = image.size
        px = np.empty(w * h * 4, dtype=np.float32)
        image.pixels.foreach_get(px)
        return px.reshape(h, w, 4)[..., :3].astype(np.float64)
    finally:
        bpy.data.images.remove(image)


def load_tile(path, slot, repair=True):
    """Read a user-supplied tile (PNG/JPEG) as normalised height or relative colour.

    Height and roughness tiles are converted to luminance (generated maps are
    rarely exactly neutral grey); ``repair`` applies ``repair_seams``.
    """
    px = read_image(path)
    if px.shape[0] != px.shape[1]:
        raise ValueError(f"{Path(path).name}: detail tiles must be square")
    if slot == "color_variation":
        if repair:
            px = repair_seams(px)
        mean = px.reshape(-1, 3).mean(axis=0)
        rel = px / np.maximum(mean, 1e-4) - 1.0  # relative deviation, colour kept
        return np.clip(rel / (3 * rel.std() + 1e-9), -1, 1).astype(np.float32)
    lum =(px @ np.array([0.2126, 0.7152, 0.0722]))[..., None]
    if repair:
        lum = repair_seams(lum)
    return _normalise(lum[..., 0])[..., None]


def periodic_resample(tile, size):
    """Resize a seamless tile with Fourier resampling (stays seamless, no aliasing)."""
    n = tile.shape[0]
    if n == size:
        return tile
    m = min(n, size)
    k = np.round(np.fft.fftfreq(m, 1.0 / m)).astype(np.int64)  # integer frequencies kept
    src, dst = np.ix_(k % n, k % n), np.ix_(k % size, k % size)
    out = []
    for c in range(tile.shape[2]):
        spec = np.fft.fft2(tile[..., c])
        new = np.zeros((size, size), dtype=np.complex128)
        new[dst] = spec[src]
        out.append(np.real(np.fft.ifft2(new)) * (size * size) / (n * n))
    return np.stack(out, axis=-1).astype(np.float32)


def tiled(tile, size, tiling):
    """Repeat a seamless tile ``tiling`` times across a size x size image."""
    tiling = max(1, int(round(tiling)))
    cell = max(4, int(round(size / tiling)))
    reps = -(-size // cell)
    return np.tile(periodic_resample(tile, cell), (reps, reps, 1))[:size, :size]


def slot_tile(slot, settings, kit_root, seed):
    """The slot's seamless tile, rotated by its ``rotate`` setting (degrees, multiples of 90)."""
    source = settings.get("source", "procedural")
    if source == "procedural":
        tile = procedural_tile(slot, int(settings.get("seed", seed)))
    else:
        path = (Path(kit_root) / source).resolve()
        if Path(kit_root).resolve() not in path.parents:
            raise ValueError(f"skin.detail.{slot}.source must stay inside the repository")
        if not path.is_file():
            raise FileNotFoundError(f"skin.detail.{slot}.source {source} not found")
        tile = load_tile(path, slot, repair=bool(settings.get("repair_seams", True)))
    return rotate(tile, settings.get("rotate", 0))


# --------------------------------------------------------------------------- composition

def _image_array(image, size=None):
    w, h = image.size
    px = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(px)
    arr = px.reshape(h, w, 4)[..., :3]
    return resize(arr, size) if size else arr


def _new_image(name, array, non_color):
    size = array.shape[0]
    img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    rgba = np.concatenate([np.clip(array, 0, 1), np.ones(array.shape[:2] + (1,), dtype=np.float32)], axis=-1)
    img.pixels.foreach_set(np.ascontiguousarray(rgba, dtype=np.float32).ravel())
    img.update()
    img.pack()
    return img


def _gradient(h):
    """Central differences of a seamless height field (texels): d/dx (U) and d/dy (V)."""
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5
    return gx, gy


def bake(obj, slug, cfg, albedo_image, kit_root, *, normal_image=None, spec_image=None,
         albedo_size=2048, normal_size=2048, roughness_size=1024, dump_dir=None):
    """Compose the skin's albedo, normal and roughness images; returns them plus a report."""
    detail = detail_config(cfg.get("detail"))
    regions = region_config(cfg.get("regions"))
    masks, cov = region_maps(obj)
    names = list(REGIONS)
    report = {"detail": {s: {k: v for k, v in detail[s].items()} for s in SLOTS}}

    def mask(name, size):
        return resize(masks[..., names.index(name)][..., None], size)[..., 0]

    scales = uv_scale(obj)
    report["uv_mm_per_unit"] = {k: round(v * 1000, 1) for k, v in scales.items()}

    def repeats(slot):
        settings = detail[slot]
        if "tile_mm" in settings:
            value = scales[SLOT_SCALE_REGION[slot]] * 1000.0 / float(settings["tile_mm"])
        else:
            value = float(settings.get("tiling", 8))
        report["detail"][slot]["repeats"] = max(1, int(round(value)))
        return max(1, int(round(value)))

    # Heights per region at the normal-map size -> slopes and a cavity term.
    gx = np.zeros((normal_size, normal_size), dtype=np.float32)
    gy = np.zeros_like(gx)
    cavity = np.zeros_like(gx)
    slope_scale = 6.0 * normal_size / REFERENCE_SIZE
    boost = np.ones_like(gx)
    for name, settings in regions.items():
        if "detail" in settings:
            boost += mask(name, normal_size) * (float(settings["detail"]) - 1.0)
    slope_scale = slope_scale * np.maximum(boost, 0.0)
    for i, slot in enumerate(HEIGHT_SLOTS):
        settings = detail[slot]
        tile = slot_tile(slot, settings, kit_root, seed=101 + i)
        h = tiled(tile, normal_size, repeats(slot))[..., 0]
        weight = mask(SLOT_REGION[slot], normal_size) * float(settings.get("strength", 1.0))
        sx, sy = _gradient(h)
        gx += weight * sx * slope_scale
        gy += weight * sy * slope_scale
        cavity += weight * np.clip(-h, 0, None)
    if normal_image is not None:
        base = _image_array(normal_image)
        base = resize(fill(base, coverage(obj, base.shape[0])), normal_size) * 2.0 - 1.0
        strength = float(cfg.get("base_normal_strength", 1.0))
        z = np.maximum(base[..., 2], 0.2)
        gx -= strength * base[..., 0] / z
        gy -= strength * base[..., 1] / z
    normal = np.stack([-gx, -gy, np.ones_like(gx)], axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    normal_img = _new_image(f"{slug}_skin_normal", normal * 0.5 + 0.5, True)

    # Albedo: padded islands, colour variation, region tints, cavity.
    albedo = _image_array(albedo_image, albedo_size)
    albedo = fill(albedo, coverage(obj, albedo_size))
    if "tint" in cfg:
        albedo = albedo * np.asarray(cfg["tint"][:3], dtype=np.float32)
    cv = detail["color_variation"]
    tile = slot_tile("color_variation", cv, kit_root, seed=211)
    if tile.shape[2] == 1:
        tile = np.repeat(tile, 3, axis=2)
    albedo = albedo * (1.0 + float(cv.get("strength", 0.06)) * tiled(tile, albedo_size, repeats("color_variation")))
    for name, settings in regions.items():
        if "tint" in settings:
            m = mask(name, albedo_size)[..., None] * float(settings.get("amount", 1.0))
            albedo = albedo * (1.0 + m * (np.asarray(settings["tint"][:3], dtype=np.float32) - 1.0))
    cav = resize(cavity[..., None], albedo_size)[..., 0]
    albedo = albedo * (1.0 - float(cfg.get("cavity", 0.08)) * np.clip(cav, 0, 1))[..., None]
    albedo_img = _new_image(f"{slug}_skin", np.clip(albedo, 0, 1), False)

    # Roughness (G channel) with per-region offsets and variation.
    rough = np.full((roughness_size, roughness_size), float(cfg.get("roughness", 0.55)), dtype=np.float32)
    for name, settings in regions.items():
        if settings.get("roughness"):
            rough += mask(name, roughness_size) * float(settings["roughness"])
    rv = detail["roughness_variation"]
    tile = slot_tile("roughness_variation", rv, kit_root, seed=307)
    rough += float(rv.get("strength", 0.05)) * tiled(tile, roughness_size, repeats("roughness_variation"))[..., 0]
    if spec_image is not None:
        spec = _image_array(spec_image)
        spec_cov = coverage(obj, spec.shape[0])
        spec = resize(fill(spec, spec_cov), roughness_size).mean(axis=-1)
        mean = float(_image_array(spec_image)[spec_cov].mean())
        rough -= float(cfg.get("specular_map_strength", 0.25)) * (spec - mean)
    rough = np.clip(rough, 0.18, 0.95)
    rough_img = _new_image(f"{slug}_skin_roughness", np.repeat(rough[..., None], 3, axis=2), True)

    if dump_dir:
        _dump(dump_dir, slug, masks, names, normal, albedo, rough)
    report["normal_size"], report["albedo_size"], report["roughness_size"] = normal_size, albedo_size, roughness_size
    return albedo_img, normal_img, rough_img, report


def _dump(folder, slug, masks, names, normal, albedo, rough):
    """Write intermediate maps as PNG for inspection (debug)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    def save(name, arr):
        arr = np.clip(arr, 0, 1)
        if arr.ndim == 2:
            arr = np.repeat(arr[..., None], 3, axis=2)
        img = _new_image(f"dump_{name}", arr.astype(np.float32), True)
        img.filepath_raw = str(folder / f"{slug}_{name}.png")
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
    palette = np.array([[1, 0.2, 0.2], [1, 1, 0], [0.2, 1, 0.2], [0.2, 0.3, 1]], dtype=np.float32)
    partition = sum(masks[..., names.index(n)][..., None] * palette[i] for i, n in enumerate(("face", "lips", "palms", "body")))
    save("regions_detail", partition)
    extra = ("cheeks", "nose", "forehead", "chin", "under_eye", "ears", "knuckles", "elbows", "knees", "nails")
    for name in extra:
        save("region_" + name, masks[..., names.index(name)])
    save("normal", normal * 0.5 + 0.5)
    save("albedo", albedo)
    save("roughness", rough)
