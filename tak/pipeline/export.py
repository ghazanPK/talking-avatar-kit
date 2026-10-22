"""Export the shipped avatars to Unity-ready FBX.

``python -m tak export fbx <slug>... | --all`` converts ``avatars/<slug>/<slug>.glb``
(the shipped GLB, not an MPFB rebuild) with headless Blender into

    build/export/<slug>/
        <slug>.fbx          binary FBX: metres, +Y up, facing +Z, 53-bone rig, no leaf bones,
                            ARKit + viseme shape keys, normals and tangents
        textures/           textures from the GLB (unchanged bytes) and derived Unity maps,
                            referenced from the FBX by relative path
        <slug>.tak.json     sidecar: licence and credit, bone map (Unity humanoid names),
                            Unity-space rest skeleton, blendshapes per mesh, materials
        LICENSE.md          the avatar licence

The Unity package in ``unity/`` reads the sidecar when it imports the FBX.
Everything here runs with the standard library; Blender is a subprocess.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Sequence

from . import AVATARS_DIR, BLENDER_SCRIPTS, CREDIT, KIT_ROOT, LICENSE_ID
from .glb import Glb
from .names import ARKIT, GAME_ENGINE_BONES, VISEMES
from .progress import Progress

SIDECAR_SCHEMA = "talking-avatar-kit/fbx-sidecar"
SIDECAR_VERSION = 1
SIDECAR_SUFFIX = ".tak.json"
DEFAULT_OUT = KIT_ROOT / "build" / "export"
TEXTURES_SUBDIR = "textures"
LICENSE_URLS = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
}
LICENSE_LABELS = {"CC-BY-4.0": "CC BY 4.0", "CC0-1.0": "CC0 1.0"}

# Unity Mecanim human bone (HumanTrait.BoneName) -> MPFB game_engine bone.
# Every game_engine bone except "Root" is mapped; the rig has no eye or jaw bones
# (eyes and jaw move with blendshapes), so LeftEye, RightEye and Jaw stay empty.
HUMANOID_MAP: dict[str, str] = {
    "Hips": "pelvis",
    "Spine": "spine_01",
    "Chest": "spine_02",
    "UpperChest": "spine_03",
    "Neck": "neck_01",
    "Head": "head",
}
for _side, _s in (("Left", "l"), ("Right", "r")):
    HUMANOID_MAP.update({
        f"{_side}Shoulder": f"clavicle_{_s}",
        f"{_side}UpperArm": f"upperarm_{_s}",
        f"{_side}LowerArm": f"lowerarm_{_s}",
        f"{_side}Hand": f"hand_{_s}",
        f"{_side}UpperLeg": f"thigh_{_s}",
        f"{_side}LowerLeg": f"calf_{_s}",
        f"{_side}Foot": f"foot_{_s}",
        f"{_side}Toes": f"ball_{_s}",
    })
    for _finger, _bone in (("Thumb", "thumb"), ("Index", "index"), ("Middle", "middle"),
                           ("Ring", "ring"), ("Little", "pinky")):
        for _joint, _n in (("Proximal", "01"), ("Intermediate", "02"), ("Distal", "03")):
            HUMANOID_MAP[f"{_side} {_finger} {_joint}"] = f"{_bone}_{_n}_{_s}"

# Bones Unity requires for a valid humanoid avatar.
UNITY_REQUIRED = (
    "Hips", "Spine", "Head", "LeftUpperArm", "LeftLowerArm", "LeftHand", "RightUpperArm",
    "RightLowerArm", "RightHand", "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "RightUpperLeg",
    "RightLowerLeg", "RightFoot",
)
UNMAPPED_BONES = ("Root",)


class ExportError(RuntimeError):
    pass


# --------------------------------------------------------------------------- avatars and manifests

def available_avatars(root: Path = AVATARS_DIR) -> list[str]:
    """Slugs of avatars/<slug>/ folders that hold a built <slug>.glb."""
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / f"{p.name}.glb").is_file()) \
        if root.is_dir() else []


def resolve_slugs(slugs: Sequence[str], all_: bool, root: Path = AVATARS_DIR) -> list[str]:
    available = available_avatars(root)
    if all_:
        if slugs:
            raise ValueError("give slugs or --all, not both")
        if not available:
            raise ValueError("no avatars/<slug>/<slug>.glb found")
        return available
    if not slugs:
        raise ValueError("name at least one avatar slug or pass --all")
    unknown = [s for s in slugs if s not in available]
    if unknown:
        raise ValueError(f"unknown avatar(s) {', '.join(unknown)}; available: {', '.join(available) or 'none'}")
    return list(dict.fromkeys(slugs))


def _first(data: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def avatar_meta(manifest: dict, slug: str) -> dict:
    """Licence, credit and naming from a manifest, tolerant of the kit's two manifest styles.

    Style 1 (kit build): ``license``, ``license_url``, ``credit``, ``attribution``.
    Style 2 (owner builds): ``licence``/``license`` as a string or an object, ``credits``
    (a string, list or object list), ``attribution``, ``rig``, ``facial_shape_keys``.
    """
    lic = _first(manifest, "license", "licence", default=None)
    lic_id, lic_url = None, _first(manifest, "license_url", "licence_url")
    if isinstance(lic, dict):
        lic_id = _first(lic, "id", "spdx", "name")
        lic_url = lic_url or _first(lic, "url")
    elif isinstance(lic, str):
        lic_id = lic
    lic_id = lic_id or LICENSE_ID
    credit = manifest.get("credit")
    credits = manifest.get("credits")
    if isinstance(credits, str):
        credit = credit or credits
        credits = []
    elif isinstance(credits, dict):
        credits = [credits]
    elif not isinstance(credits, list):
        credits = []
    name = _first(manifest, "name", "display_name", default=slug.replace("_", " ").title())
    attribution = _first(manifest, "attribution")
    if isinstance(attribution, (list, dict)):
        credits = credits + (attribution if isinstance(attribution, list) else [attribution])
        attribution = None
    credit = credit or CREDIT
    if not attribution:
        attribution = f"{name} avatar, {credit}, licensed under {LICENSE_LABELS.get(lic_id, lic_id)}."
    licence = {
        "id": lic_id,
        "url": lic_url or LICENSE_URLS.get(lic_id),
        "credit": credit,
        "attribution": attribution,
        "credits": credits,
    }
    # Per-component licences (style 2: {"character_geometry_and_makehuman_assets": "CC0-1.0"}).
    components = manifest.get("licenses") or manifest.get("licences")
    if isinstance(components, dict) and components:
        licence["components"] = components
    return {"slug": slug, "name": name, "description": manifest.get("description", ""), "license": licence}


def load_manifest(slug: str, root: Path = AVATARS_DIR) -> dict:
    path = root / slug / "manifest.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ExportError(f"{path.name} of {slug} is not valid JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------- GLB materials and textures

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _safe_name(text: str, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", text or "").strip("._")
    return name or fallback


def texture_files(gltf: dict) -> dict[int, str]:
    """glTF image index -> unique file name for the textures/ folder."""
    used: set[str] = set()
    files: dict[int, str] = {}
    for index, image in enumerate(gltf.get("images", [])):
        ext = _EXT.get(image.get("mimeType", ""), Path(image.get("uri", "")).suffix or ".png")
        stem = _safe_name(image.get("name") or Path(image.get("uri", "")).stem, f"image_{index}")
        name, n = stem + ext, 2
        while name.lower() in used:
            name, n = f"{stem}_{n}{ext}", n + 1
        used.add(name.lower())
        files[index] = name
    return files


def material_plan(gltf: dict) -> dict[str, dict]:
    """Material name -> what the FBX material and the Unity material need (paths relative to textures/)."""
    files = texture_files(gltf)
    textures = gltf.get("textures", [])

    def tex(ref: dict | None) -> dict | None:
        if not ref or "index" not in ref:
            return None
        source = textures[ref["index"]].get("source")
        if source is None or source not in files:
            return None
        out = {"file": files[source]}
        if ref.get("texCoord"):
            out["uv"] = ref["texCoord"]
        if "scale" in ref:
            out["scale"] = ref["scale"]
        return out

    plan: dict[str, dict] = {}
    for index, mat in enumerate(gltf.get("materials", [])):
        name = mat.get("name") or f"material_{index}"
        pbr = mat.get("pbrMetallicRoughness", {})
        metallic = float(pbr.get("metallicFactor", 1.0))
        roughness = float(pbr.get("roughnessFactor", 1.0))
        entry: dict[str, Any] = {
            "alpha_mode": mat.get("alphaMode", "OPAQUE"),
            "double_sided": bool(mat.get("doubleSided", False)),
            "base_color_factor": [float(v) for v in pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])],
            "base_color": tex(pbr.get("baseColorTexture")),
            "normal": tex(mat.get("normalTexture")),
            "metallic_roughness": tex(pbr.get("metallicRoughnessTexture")),
            "occlusion": tex(mat.get("occlusionTexture")),
            "emissive": tex(mat.get("emissiveTexture")),
            "emissive_factor": [float(v) for v in mat.get("emissiveFactor", [0.0, 0.0, 0.0])],
            "metallic": metallic,
            "roughness": roughness,
            "smoothness": round(1.0 - roughness, 6),
            "gltf_extensions": sorted(mat.get("extensions", {})),
        }
        if entry["alpha_mode"] == "MASK":
            entry["alpha_cutoff"] = float(mat.get("alphaCutoff", 0.5))
        if entry["normal"] is not None:
            entry["normal"].setdefault("scale", 1.0)
        f0 = specular_f0(mat)
        if f0 is not None:
            entry["specular_f0"] = f0
        if entry["metallic_roughness"]:
            stem = Path(entry["metallic_roughness"]["file"]).stem
            kind = "specular_smoothness" if f0 is not None else "metallic_smoothness"
            entry["unity_map"] = {"kind": kind, "source": entry["metallic_roughness"]["file"],
                                  "file": f"{stem}_{kind}.png"}
        plan[name] = {k: v for k, v in entry.items() if v is not None}
    return plan


def specular_f0(material: dict) -> float | None:
    """Normal-incidence reflectance of a dielectric with KHR_materials_ior/specular, else None.

    Unity's metallic workflow fixes F0 at 0.04; the kit's skin, hair and mouth
    materials use less (glTF ior 1.4-1.55 scaled by specularFactor), so the
    Unity materials use the specular workflow with this value instead.
    """
    ext = material.get("extensions", {})
    if not ({"KHR_materials_ior", "KHR_materials_specular"} & set(ext)):
        return None
    if float(material.get("pbrMetallicRoughness", {}).get("metallicFactor", 1.0)) > 0.0:
        return None
    ior = float(ext.get("KHR_materials_ior", {}).get("ior", 1.5))
    spec = ext.get("KHR_materials_specular", {})
    color = spec.get("specularColorFactor", [1.0, 1.0, 1.0])
    f0 = ((ior - 1.0) / (ior + 1.0)) ** 2 * float(spec.get("specularFactor", 1.0)) * (sum(color) / len(color))
    return round(min(max(f0, 0.0), 1.0), 6)


def extract_textures(glb: Glb, dest: Path) -> dict[str, dict]:
    """Write every embedded image to ``dest`` unchanged; returns file -> {sha256, bytes}."""
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for index, name in texture_files(glb.json).items():
        image = glb.json["images"][index]
        if "bufferView" not in image:
            raise ExportError(f"image {name} is not embedded in the GLB")
        view = glb.json["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        data = glb.bin[start:start + view["byteLength"]]
        (dest / name).write_bytes(data)
        out[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return out


def texture_roles(plan: dict[str, dict]) -> dict[str, dict]:
    """File -> roles and colour space (what the Unity texture importer must set)."""
    roles: dict[str, set[str]] = {}
    for mat in plan.values():
        for key in ("base_color", "normal", "metallic_roughness", "occlusion", "emissive"):
            if mat.get(key):
                roles.setdefault(mat[key]["file"], set()).add(key)
        if mat.get("unity_map"):
            roles.setdefault(mat["unity_map"]["file"], set()).add(mat["unity_map"]["kind"])
    out = {}
    for file, rs in sorted(roles.items()):
        linear = not (rs & {"base_color", "emissive", "specular_smoothness"})
        out[file] = {"roles": sorted(rs), "color_space": "linear" if linear else "sRGB",
                     "normal_map": "normal" in rs}
    return out


# --------------------------------------------------------------------------- sidecar

def humanoid_map(bones: Sequence[str]) -> tuple[dict[str, str], list[str]]:
    present = set(bones)
    mapping = {human: bone for human, bone in HUMANOID_MAP.items() if bone in present}
    unmapped = [b for b in bones if b not in set(mapping.values())]
    return mapping, unmapped


def build_sidecar(meta: dict, info: dict, plan: dict[str, dict], textures: dict[str, dict], *,
                  slug: str, glb_path: Path, glb_sha256: str, glb_bytes: int,
                  fbx_path: Path) -> dict:
    mapping, unmapped = humanoid_map(info["bones"])
    meshes = {m["name"]: m["blendshapes"] for m in info["meshes"] if m["blendshapes"]}
    all_shapes = {n for names in meshes.values() for n in names}
    material_meshes: dict[str, list[str]] = {}
    for mesh in info["meshes"]:
        for mat in mesh["materials"]:
            if mat:
                material_meshes.setdefault(mat, []).append(mesh["name"])
    roles = texture_roles(plan)
    materials = {}
    for name, spec in plan.items():
        if name not in material_meshes:
            continue
        entry = {"meshes": material_meshes[name]}
        for key in ("alpha_mode", "alpha_cutoff", "double_sided", "base_color_factor", "metallic",
                    "roughness", "smoothness", "specular_f0", "emissive_factor", "gltf_extensions"):
            if key in spec:
                entry[key] = spec[key]
        for key in ("base_color", "normal", "metallic_roughness", "occlusion", "emissive"):
            if spec.get(key):
                entry[key] = dict(spec[key], file=f"{TEXTURES_SUBDIR}/{spec[key]['file']}")
        if spec.get("unity_map"):
            entry[spec["unity_map"]["kind"]] = {"file": f"{TEXTURES_SUBDIR}/{spec['unity_map']['file']}"}
        materials[name] = entry
    texture_list = []
    for file, role in roles.items():
        item = {"file": f"{TEXTURES_SUBDIR}/{file}", **role}
        item.update(textures.get(file, {}))
        texture_list.append(item)
    bounds = info.get("bounds_unity", {})
    return {
        "schema": SIDECAR_SCHEMA,
        "schema_version": SIDECAR_VERSION,
        "slug": slug,
        "name": meta["name"],
        "description": meta.get("description", ""),
        "license": meta["license"],
        "source": {"file": f"avatars/{slug}/{glb_path.name}", "sha256": glb_sha256, "bytes": glb_bytes},
        "fbx": {
            "file": fbx_path.name,
            "format": "FBX 7.4 binary",
            "blender": info.get("blender"),
            "exporter": info.get("fbx_exporter"),
            "settings": info.get("fbx_settings", {}),
        },
        "units": {"unit": "metre", "up": "+Y", "forward": "+Z", "handedness": "Unity (left-handed) after import",
                  "height_m": info.get("height_m"), "bounds": bounds},
        "rig": {
            "type": "MPFB game_engine",
            "rest_pose": "A-pose",
            "armature": info["armature"],
            "root_bone": "Root" if "Root" in info["bones"] else info["bones"][0],
            "bones": info["bones"],
            "humanoid": mapping,
            "unmapped": unmapped,
            "skeleton": info["skeleton"],
        },
        "blendshapes": {
            "arkit": [n for n in ARKIT if n in all_shapes],
            "visemes": [n for n in VISEMES if n in all_shapes],
            "other": sorted(all_shapes - set(ARKIT) - set(VISEMES)),
            "meshes": meshes,
        },
        "meshes": [{k: m[k] for k in ("name", "vertices", "triangles", "materials")} for m in info["meshes"]],
        "materials": materials,
        "textures": texture_list,
    }


REQUIRED_SIDECAR_KEYS = ("schema", "schema_version", "slug", "name", "license", "source", "fbx", "units",
                         "rig", "blendshapes", "meshes", "materials", "textures")


def check_sidecar(sidecar: dict) -> list[str]:
    """Schema problems of a sidecar (empty when it is valid)."""
    problems = [f"missing key {k}" for k in REQUIRED_SIDECAR_KEYS if k not in sidecar]
    if problems:
        return problems
    if sidecar["schema"] != SIDECAR_SCHEMA or sidecar["schema_version"] != SIDECAR_VERSION:
        problems.append("unknown schema or version")
    lic = sidecar["license"]
    for key in ("id", "credit", "attribution"):
        if not isinstance(lic.get(key), str) or not lic.get(key):
            problems.append(f"license.{key} missing")
    rig = sidecar["rig"]
    bones = rig.get("bones", [])
    missing_bones = [b for b in GAME_ENGINE_BONES if b not in bones]
    if missing_bones:
        problems.append(f"rig lacks game_engine bones {missing_bones}")
    human = rig.get("humanoid", {})
    missing_human = [h for h in UNITY_REQUIRED if h not in human]
    if missing_human:
        problems.append(f"humanoid map lacks required bones {missing_human}")
    stray = [b for b in human.values() if b not in bones]
    if stray:
        problems.append(f"humanoid map names unknown bones {stray}")
    names = [e.get("name") for e in rig.get("skeleton", [])]
    if any(b not in names for b in bones):
        problems.append("skeleton does not list every bone")
    for entry in rig.get("skeleton", []):
        if len(entry.get("position", [])) != 3 or len(entry.get("rotation", [])) != 4:
            problems.append(f"skeleton entry {entry.get('name')} malformed")
            break
        if entry.get("parent") is not None and entry["parent"] not in names:
            problems.append(f"skeleton entry {entry.get('name')} has unknown parent")
            break
    shapes = sidecar["blendshapes"]
    if len(shapes.get("arkit", [])) != len(ARKIT):
        problems.append(f"{len(shapes.get('arkit', []))} ARKit blendshapes, expected {len(ARKIT)}")
    if len(shapes.get("visemes", [])) != len(VISEMES):
        problems.append(f"{len(shapes.get('visemes', []))} visemes, expected {len(VISEMES)}")
    for mat, spec in sidecar["materials"].items():
        if spec.get("alpha_mode") not in ("OPAQUE", "MASK", "BLEND"):
            problems.append(f"material {mat} has alpha mode {spec.get('alpha_mode')}")
        for key in ("base_color", "normal", "metallic_smoothness", "specular_smoothness"):
            file = spec.get(key, {}).get("file") if isinstance(spec.get(key), dict) else None
            if file and (file.startswith("/") or ":" in file or ".." in file):
                problems.append(f"material {mat} {key} path is not relative: {file}")
    return problems


# --------------------------------------------------------------------------- export

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _run_blender_json(blender: str, args: list, progress: Progress, log_file: Path | None) -> list[dict]:
    from .tools import parse_marker, profile_dir, run_blender

    events = []
    for line in run_blender(blender, BLENDER_SCRIPTS / "export_fbx.py", args, profile=profile_dir(),
                            log_file=log_file):
        data = parse_marker(line)
        if not data:
            continue
        events.append(data)
        if data.get("event") == "progress":
            progress.emit(data.get("stage", "export"), data.get("message", ""), data.get("progress", 0.0))
    return events


def export_avatar(slug: str, *, out_root: Path = DEFAULT_OUT, blender: str, root: Path = AVATARS_DIR,
                  progress: Progress | None = None, verify: bool = True) -> dict:
    from .tools import PathArg

    progress = progress or Progress()
    glb_path = root / slug / f"{slug}.glb"
    if not glb_path.is_file():
        raise ExportError(f"{glb_path.name} not found in avatars/{slug}/")
    out_dir = out_root / slug
    if out_dir.exists():
        shutil.rmtree(out_dir)
    textures_dir = out_dir / TEXTURES_SUBDIR
    # Blender logs hold machine paths; keep them out of the distributable avatar folder.
    logs_dir = out_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    progress.emit("prepare", f"reading {glb_path.name}", 0.02)
    glb = Glb.load(glb_path)
    plan = material_plan(glb.json)
    textures = extract_textures(glb, textures_dir)
    meta = avatar_meta(load_manifest(slug, root), slug)
    fbx_path = out_dir / f"{slug}.fbx"
    with tempfile.TemporaryDirectory(prefix="tak-export-", dir=str(out_root)) as tmp:
        tmp_dir = Path(tmp)
        plan_file = tmp_dir / "plan.json"
        info_file = tmp_dir / "info.json"
        plan_file.write_text(json.dumps({"textures_subdir": TEXTURES_SUBDIR, "materials": plan}, indent=1),
                             encoding="utf-8")
        args = ["--glb", PathArg(glb_path), "--fbx", PathArg(fbx_path), "--plan", PathArg(plan_file),
                "--info", PathArg(info_file)]
        _run_blender_json(blender, args, progress.scaled(0.05, 0.75), logs_dir / f"{slug}-export.log")
        info = json.loads(info_file.read_text(encoding="utf-8"))
        for name, spec in plan.items():
            ms = spec.get("unity_map")
            if ms and (textures_dir / ms["file"]).is_file():
                data = (textures_dir / ms["file"]).read_bytes()
                textures[ms["file"]] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        sidecar = build_sidecar(meta, info, plan, textures, slug=slug, glb_path=glb_path,
                                glb_sha256=_sha256(glb_path), glb_bytes=glb_path.stat().st_size,
                                fbx_path=fbx_path)
        sidecar["fbx"]["sha256"] = _sha256(fbx_path)
        sidecar["fbx"]["bytes"] = fbx_path.stat().st_size
        problems = check_sidecar(sidecar)
        (out_dir / f"{slug}{SIDECAR_SUFFIX}").write_text(json.dumps(sidecar, indent=1, ensure_ascii=False) + "\n",
                                                        encoding="utf-8")
        licence = root / slug / "LICENSE.md"
        if not licence.is_file():
            licence = root / "LICENSE.md"
        if licence.is_file():
            shutil.copyfile(licence, out_dir / "LICENSE.md")
        result: dict[str, Any] = {
            "ok": not problems,
            "fbx": _display(fbx_path),
            "sidecar": _display(out_dir / f"{slug}{SIDECAR_SUFFIX}"),
            "bytes": sidecar["fbx"]["bytes"],
            "bones": len(info["bones"]),
            "humanoid_bones": len(sidecar["rig"]["humanoid"]),
            "blendshapes": {m: len(n) for m, n in sidecar["blendshapes"]["meshes"].items()},
            "materials": sorted(sidecar["materials"]),
            "textures": len(sidecar["textures"]),
            "height_m": info.get("height_m"),
            "sidecar_problems": problems,
            "fbx_paths": fbx_path_check(fbx_path),
        }
        result["ok"] = result["ok"] and result["fbx_paths"]["ok"]
        if verify:
            progress.emit("verify", f"re-importing {fbx_path.name} in Blender", 0.8)
            report_file = tmp_dir / "verify.json"
            _run_blender_json(blender, ["--verify", PathArg(fbx_path), "--info", PathArg(report_file)],
                              progress.scaled(0.8, 0.98), logs_dir / f"{slug}-verify.log")
            report = json.loads(report_file.read_text(encoding="utf-8"))
            result["verify"] = verify_report(report, sidecar)
            result["ok"] = result["ok"] and result["verify"]["ok"]
    progress.emit("done", f"{slug}: {'ok' if result['ok'] else 'problems found'}", 1.0)
    return result


def verify_report(report: dict, sidecar: dict) -> dict:
    """Compare Blender's re-import of the FBX with the sidecar."""
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    bones = report.get("bones", [])
    add("bones", sorted(bones) == sorted(sidecar["rig"]["bones"]) and not report.get("leaf_bones"),
        f"{len(bones)} bones" + (f", leaf bones {report['leaf_bones']}" if report.get("leaf_bones") else ""))
    wanted = sidecar["blendshapes"]["meshes"]
    got = {m["name"]: m["blendshapes"] for m in report.get("meshes", []) if m["blendshapes"]}
    diff = {m: sorted(set(wanted.get(m, [])) ^ set(got.get(m, []))) for m in set(wanted) | set(got)}
    diff = {m: d for m, d in diff.items() if d}
    add("shape_keys", not diff, ", ".join(f"{m} {len(n)}" for m, n in sorted(got.items()))
        + (f"; differences {diff}" if diff else ""))
    height = report.get("height_m") or 0.0
    expected = sidecar["units"].get("height_m") or 0.0
    add("scale", abs(height - expected) < 0.01, f"{height:.3f} m (GLB {expected:.3f} m)")
    add("orientation", report.get("faces_minus_y") and report.get("left_on_plus_x"),
        "faces -Y in Blender (+Z in Unity), left side on +X" if report.get("faces_minus_y")
        else "unexpected facing direction")
    scales = report.get("object_scales", {})
    bad = {k: v for k, v in scales.items() if any(abs(c - 1.0) > 1e-3 for c in v)}
    add("object_scale", not bad, "all objects at scale 1" if not bad else f"scaled objects {bad}")
    missing = sorted(set(sidecar["materials"]) - set(report.get("materials", [])))
    add("materials", not missing, ", ".join(report.get("materials", [])) + (f"; missing {missing}" if missing else ""))
    images = report.get("images", [])
    add("texture_paths", bool(images) and report.get("images_missing", 0) == 0,
        f"{len(images)} textures resolved from the FBX folder"
        + (f", {report['images_missing']} missing" if report.get("images_missing") else ""))
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


_ABS_PATH = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:[A-Za-z0-9 _.-]{1,64}[\\/]){2,}"
                       rb"|/mnt/[a-z]/[A-Za-z0-9 _.-]+|/home/[a-z_][a-z0-9_-]*/|/Users/[A-Za-z][A-Za-z0-9_.-]*/")


def fbx_path_check(fbx_path: Path) -> dict:
    """Texture references in the FBX must be relative; no machine paths may leak into the file."""
    data = fbx_path.read_bytes()
    leaks = sorted({m.group(0)[:80].decode("utf-8", "replace") for m in _ABS_PATH.finditer(data)})
    rel = sorted({m.group(0).decode("utf-8", "replace")
                  for m in re.finditer(rb"textures/[A-Za-z0-9_.-]+", data)})
    return {"check": "fbx_paths", "ok": not leaks and bool(rel),
            "detail": f"{len(rel)} relative texture references" + (f"; absolute paths {leaks}" if leaks else "")}


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(KIT_ROOT).as_posix()
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- CLI

class _Parser(argparse.ArgumentParser):
    def error(self, message):  # noqa: D401
        raise SystemExit(f"{self.prog}: error: {message}")


def export_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="tak export fbx",
                     description="Convert avatars/<slug>/<slug>.glb to a Unity-ready FBX with headless Blender.")
    parser.add_argument("slugs", nargs="*", help="avatar slugs (folders under avatars/)")
    parser.add_argument("--all", action="store_true", help="export every avatar that has a GLB")
    parser.add_argument("--out", type=Path, default=None,
                        help="output folder (default build/export); each avatar goes to <out>/<slug>/")
    parser.add_argument("--blender", help="Blender executable (default: discovered)")
    parser.add_argument("--no-verify", action="store_true", help="skip the Blender re-import check")
    parser.add_argument("--unity", type=Path, metavar="PROJECT",
                        help="also copy the exports and the kit's Unity package into this Unity project")
    parser.add_argument("--unity-check", action="store_true",
                        help="import the exports in a temporary Unity project in batch mode and validate them")
    parser.add_argument("--unity-exe", help="Unity editor executable (default: UNITY or discovered)")
    parser.add_argument("--pipeline", choices=("builtin", "urp", "both"), default="both",
                        help="render pipeline(s) for --unity-check (default both)")
    parser.add_argument("--skip-export", action="store_true",
                        help="reuse existing exports in the output folder (for --unity/--unity-check)")
    parser.add_argument("--debug", action="store_true", help="print tracebacks on stderr")
    return parser


def parse_export_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse ``export`` arguments; the first positional must be the format (``fbx``)."""
    argv = list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        export_parser().print_help()
        raise SystemExit(0)
    if argv[0] != "fbx":
        raise SystemExit(f"tak export: error: unknown format {argv[0]!r} (supported: fbx)")
    return export_parser().parse_args(argv[1:])


def export_main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_export_args(argv)
    except SystemExit as exc:
        if exc.code in (0, None):
            return 0
        print(exc.code if isinstance(exc.code, str) else "invalid arguments", file=sys.stderr)
        return 2
    progress = Progress()
    try:
        slugs = resolve_slugs(args.slugs, args.all)
    except ValueError as exc:
        print(f"tak export: error: {exc}", file=sys.stderr)
        progress.result({"ok": False, "error": str(exc)})
        return 2
    out_root = (args.out or DEFAULT_OUT).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"ok": True, "out": _display(out_root), "avatars": {}}
    try:
        if not args.skip_export:
            from .tools import find_blender

            blender = find_blender(args.blender)
            if not blender:
                raise ExportError("Blender not found (set BLENDER, pass --blender or install Blender 4.2+)")
            for index, slug in enumerate(slugs):
                sub = progress.scaled(index / len(slugs) * 0.7, (index + 1) / len(slugs) * 0.7)
                result["avatars"][slug] = export_avatar(slug, out_root=out_root, blender=blender,
                                                        progress=sub, verify=not args.no_verify)
        else:
            for slug in slugs:
                exists = (out_root / slug / f"{slug}.fbx").is_file()
                result["avatars"][slug] = {"ok": exists, "fbx": _display(out_root / slug / f"{slug}.fbx"),
                                           "reused": True}
        result["ok"] = all(a["ok"] for a in result["avatars"].values())
        if args.unity:
            from .unity import install_into_project

            progress.emit("unity", f"copying into {args.unity}", 0.72)
            result["unity_project"] = install_into_project(args.unity, out_root, slugs)
        if args.unity_check:
            from .unity import run_unity_check

            pipelines = ("builtin", "urp") if args.pipeline == "both" else (args.pipeline,)
            result["unity_check"] = run_unity_check(out_root, slugs, unity=args.unity_exe, pipelines=pipelines,
                                                    progress=progress.scaled(0.72, 1.0))
            if result["unity_check"].get("ran"):
                result["ok"] = result["ok"] and result["unity_check"].get("ok", False)
    except Exception as exc:  # noqa: BLE001
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        message = str(exc) or exc.__class__.__name__
        progress.emit("export", f"failed: {message}", 1.0)
        result.update(ok=False, error=message)
        progress.result(result)
        return 1
    progress.result(result)
    return 0 if result["ok"] else 1
