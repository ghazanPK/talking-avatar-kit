"""Validate built avatar GLBs.

Two layers:

* ``static_checks`` reads the GLB with the standard library: skeleton (53
  joints with the game_engine names), morph targets (all 52 ARKit + 15 visemes
  on the body, only known names elsewhere, all default weights zero), skin
  influences (at most four, normalised), materials and alpha modes, embedded
  textures, bind-pose height within the spec range, file size.
* ``blender_checks`` re-imports the GLB in background Blender
  (``blender/validate.py``), checks the same structure as Blender sees it and
  poses the arms to catch vertices without influences.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from . import AVATARS_DIR, BLENDER_SCRIPTS
from .glb import Glb, GlbError
from .names import ALPHA_MODES, BASE_MATERIALS, FACE, FACE_MESHES, GAME_ENGINE_BONES
from .progress import Progress
from .spec import load_spec
from .tools import PathArg, ToolError, find_blender, parse_marker, profile_dir, run_blender


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})

    @property
    def ok(self) -> bool:
        return all(c["ok"] for c in self.checks)

    def failures(self) -> list[str]:
        return [f"{c['check']}: {c['detail']}" for c in self.checks if not c["ok"]]


def expected_materials(spec: dict) -> list[str]:
    return list(BASE_MATERIALS) + [item["slot"] for item in spec["clothes"]]


def static_checks(glb_path: Path, spec: dict) -> dict:
    report = Report()
    try:
        glb = Glb.load(glb_path)
    except (OSError, GlbError, ValueError) as exc:
        report.add("glb", False, str(exc))
        return _summary(report, {})
    gltf = glb.json
    report.add("glb", True, f"glTF {gltf.get('asset', {}).get('version')} binary")

    max_bytes = spec["checks"]["max_bytes"]
    report.add("file_size", glb.size <= max_bytes, f"{glb.size} bytes (limit {max_bytes})")

    skins = gltf.get("skins", [])
    nodes = gltf.get("nodes", [])
    bones: list[str] = []
    if len(skins) != 1:
        report.add("skeleton", False, f"{len(skins)} skins, expected 1")
    else:
        bones = [nodes[j].get("name", "") for j in skins[0]["joints"]]
        missing = sorted(set(GAME_ENGINE_BONES) - set(bones))
        extra = sorted(set(bones) - set(GAME_ENGINE_BONES))
        report.add("skeleton", len(bones) == 53 and not missing and not extra,
                   f"{len(bones)} joints" + (f", missing {missing}" if missing else "")
                   + (f", unexpected {extra}" if extra else ""))

    meshes = gltf.get("meshes", [])
    by_node = {}
    for node in nodes:
        if "mesh" in node:
            by_node[node.get("name", "")] = (node, meshes[node["mesh"]])
    morphs: dict[str, list[str]] = {}
    for name, (node, mesh) in by_node.items():
        names = mesh.get("extras", {}).get("targetNames", [])
        if names:
            morphs[name] = names
    body = morphs.get("Body", [])
    missing_face = [n for n in FACE if n not in body]
    report.add("morph_targets", not missing_face and len(body) == len(FACE),
               f"Body has {len(body)} targets" + (f", missing {missing_face}" if missing_face else ""))
    unknown = {m: sorted(set(n) - set(FACE)) for m, n in morphs.items() if set(n) - set(FACE)}
    report.add("morph_names", not unknown, "only ARKit/viseme names" if not unknown else f"unknown {unknown}")
    stray = sorted(set(morphs) - set(FACE_MESHES))
    report.add("morph_meshes", not stray, ", ".join(f"{m} {len(n)}" for m, n in morphs.items())
               + (f"; unexpected morph meshes {stray}" if stray else ""))
    nonzero = [m["name"] for m in meshes if any(w for w in m.get("weights", []))]
    report.add("morph_defaults", not nonzero, "all default weights zero" if not nonzero else f"non-zero in {nonzero}")

    skinned = all(node.get("skin") == 0 for node, _ in by_node.values())
    report.add("skinned_meshes", skinned and bool(by_node), f"{len(by_node)} meshes bound to the skin")

    worst = 0.0
    for node, mesh in by_node.values():
        for prim in mesh.get("primitives", []):
            attrs = prim.get("attributes", {})
            if "WEIGHTS_1" in attrs or "JOINTS_1" in attrs:
                worst = max(worst, 1.0)
            if "WEIGHTS_0" in attrs:
                for row in glb.accessor(attrs["WEIGHTS_0"]):
                    worst = max(worst, abs(sum(row) - 1.0))
            else:
                worst = max(worst, 1.0)
    report.add("skin_weights", worst < 0.01, f"max |sum-1| = {worst:.4f}, at most 4 influences")

    materials = [m.get("name", "") for m in gltf.get("materials", [])]
    wanted = expected_materials(spec)
    missing_mat = [m for m in wanted if m not in materials]
    report.add("materials", not missing_mat, ", ".join(materials)
               + (f"; missing {missing_mat}" if missing_mat else ""))
    wrong_alpha = []
    for mat in gltf.get("materials", []):
        expected = ALPHA_MODES.get(mat.get("name"), "OPAQUE")
        if mat.get("alphaMode", "OPAQUE") != expected:
            wrong_alpha.append(f"{mat.get('name')}={mat.get('alphaMode')}")
    report.add("alpha_modes", not wrong_alpha, "as expected" if not wrong_alpha else ", ".join(wrong_alpha))

    external = [img.get("uri") for img in gltf.get("images", []) if "uri" in img]
    report.add("embedded_textures", not external, f"{len(gltf.get('images', []))} images embedded"
               if not external else f"external images {external}")

    lo, hi = math.inf, -math.inf
    for node, mesh in by_node.values():
        for prim in mesh.get("primitives", []):
            acc = gltf["accessors"][prim["attributes"]["POSITION"]]
            if "min" in acc and "max" in acc:
                lo, hi = min(lo, acc["min"][1]), max(hi, acc["max"][1])
    height = hi - lo if hi > lo else 0.0
    low, high = spec["checks"]["height_m"]
    report.add("height", low <= height <= high, f"{height:.3f} m (expected {low}-{high} m)")

    info = {"bytes": glb.size, "bones": bones, "morphs": morphs, "materials": materials,
            "height_m": round(height, 4), "meshes": list(by_node)}
    return _summary(report, info)


def _summary(report: Report, info: dict) -> dict:
    return {"ok": report.ok, "checks": report.checks, "failures": report.failures(), "info": info}


def blender_checks(glb_path: Path, spec: dict, blender: str, profile: Path | None = None) -> dict:
    payload: dict = {}
    profile = profile or profile_dir()
    args = [PathArg(glb_path), "--expect-bones", "53", "--height",
            str(spec["checks"]["height_m"][0]), str(spec["checks"]["height_m"][1])]
    try:
        for line in run_blender(blender, BLENDER_SCRIPTS / "validate.py", ["--glb", *args], profile=profile):
            data = parse_marker(line)
            if data and data.get("event") == "validate":
                payload = data
    except ToolError as exc:
        return {"ok": False, "checks": [], "failures": [str(exc)]}
    if not payload:
        return {"ok": False, "checks": [], "failures": ["Blender validation printed no result"]}
    checks = payload.get("checks", [])
    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "failures": [f"{c['check']}: {c['detail']}" for c in checks if not c["ok"]]}


def validate_glb(glb_path: Path, spec: dict, *, blender: str | None = None,
                 progress: Progress | None = None) -> dict:
    progress = progress or Progress()
    progress.emit("validate", f"checking {glb_path.name} structure", 0.0)
    result = {"static": static_checks(glb_path, spec)}
    if blender:
        progress.emit("validate", f"re-importing {glb_path.name} in Blender", 0.4)
        result["blender"] = blender_checks(glb_path, spec, blender)
    result["ok"] = all(part["ok"] for part in result.values())
    status = "passed" if result["ok"] else "failed: " + "; ".join(
        f for part in ("static", "blender") if part in result for f in result[part]["failures"])
    progress.emit("validate", f"{glb_path.name} validation {status}", 1.0)
    return result


def validate_avatar(slug: str, *, blender: str | bool | None = None,
                    progress: Progress | None = None, root: Path = AVATARS_DIR) -> dict:
    """Validate avatars/<slug>/<slug>.glb against its spec. ``blender=True`` discovers Blender."""
    spec = load_spec(root / slug / "spec.json")
    if blender is True:
        blender = find_blender()
        if not blender:
            raise ToolError("Blender not found for the re-import check (use --static-only)")
    return validate_glb(root / slug / f"{slug}.glb", spec, blender=blender or None, progress=progress)
