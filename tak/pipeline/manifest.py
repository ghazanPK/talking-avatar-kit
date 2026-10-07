"""Write avatars/<slug>/manifest.json from the built GLB, its spec and the build report."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import CREDIT, LICENSE_ID, MPFB_VERSION
from .glb import Glb
from .names import ARKIT, VISEMES

SCHEMA_VERSION = 1
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def material_summary(gltf: dict) -> list[dict]:
    meshes = gltf.get("meshes", [])
    users: dict[int, list[str]] = {}
    for node in gltf.get("nodes", []):
        if "mesh" in node:
            for prim in meshes[node["mesh"]].get("primitives", []):
                if "material" in prim:
                    users.setdefault(prim["material"], []).append(node.get("name", ""))
    out = []
    for index, mat in enumerate(gltf.get("materials", [])):
        pbr = mat.get("pbrMetallicRoughness", {})
        out.append({
            "slot": mat.get("name", f"material_{index}"),
            "meshes": users.get(index, []),
            "alpha_mode": mat.get("alphaMode", "OPAQUE"),
            "double_sided": bool(mat.get("doubleSided", False)),
            "base_color_texture": "baseColorTexture" in pbr,
            "base_color_factor": pbr.get("baseColorFactor"),
            "normal_texture": "normalTexture" in mat,
            "extensions": sorted(mat.get("extensions", {})),
        })
    return out


def build_manifest(spec: dict, glb_path: Path, *, build: dict | None = None,
                   install: dict | None = None, preview: str | None = "preview.png",
                   validation: dict | None = None) -> dict[str, Any]:
    """Assemble the manifest dictionary (pure function; no Blender needed)."""
    data = Path(glb_path).read_bytes()
    glb = Glb(data)
    gltf = glb.json
    nodes = gltf.get("nodes", [])
    skins = gltf.get("skins", [])
    bones = [nodes[j].get("name", "") for j in skins[0]["joints"]] if skins else []
    meshes = gltf.get("meshes", [])
    mesh_info = []
    morph_meshes: dict[str, list[str]] = {}
    for node in nodes:
        if "mesh" not in node:
            continue
        mesh = meshes[node["mesh"]]
        names = mesh.get("extras", {}).get("targetNames", [])
        count = sum(gltf["accessors"][p["attributes"]["POSITION"]]["count"] for p in mesh.get("primitives", []))
        mesh_info.append({"name": node.get("name", ""), "vertices": count, "morph_targets": len(names)})
        if names:
            morph_meshes[node.get("name", "")] = names
    body = set(morph_meshes.get("Body", []))
    build = build or {}
    versions = build.get("versions", {})
    packs = {k: v.get("sha256") for k, v in (install or {}).get("packs", {}).items()}
    images = []
    for img in gltf.get("images", []):
        view = gltf["bufferViews"][img["bufferView"]] if "bufferView" in img else {}
        images.append({"name": img.get("name"), "mime_type": img.get("mimeType"),
                       "bytes": view.get("byteLength")})
    assets = {
        "skin": spec["skin"]["material"], "eyes": f"{spec['eyes']['mesh']} / {spec['eyes']['material']}",
        "eyebrows": spec["eyebrows"]["asset"], "eyelashes": spec["eyelashes"]["asset"],
        "teeth": spec["teeth"]["asset"], "tongue": spec["tongue"]["asset"], "hair": spec["hair"]["asset"],
        **{item["slot"]: item["asset"] for item in spec["clothes"]},
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "slug": spec["slug"],
        "name": spec["name"],
        "description": spec["description"],
        "license": LICENSE_ID,
        "license_url": LICENSE_URL,
        "credit": CREDIT,
        "attribution": f"{spec['name']} avatar, {CREDIT}, licensed under CC BY 4.0. "
                       "Built with MPFB from CC0 MakeHuman assets.",
        "file": glb_path.name,
        "format": "glTF 2.0 binary (GLB)",
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "preview": preview,
        "units": "metres, +Y up, character faces +Z",
        "height_m": build.get("height_m"),
        "generator": {
            "pipeline": "talking-avatar-kit tak build",
            "blender": versions.get("blender"),
            "mpfb": versions.get("mpfb") or MPFB_VERSION,
            "gltf_exporter": versions.get("gltf_exporter"),
            "makehuman_packs_sha256": packs,
        },
        "source_assets": {"license": "CC0-1.0 (MakeHuman Community)", "names": assets},
        "rig": {
            "type": "MPFB game_engine",
            "rest_pose": "A-pose",
            "bone_count": len(bones),
            "bones": bones,
            "max_influences": 4,
            "weight_fixes": sorted(build.get("weight_fixes", {})),
        },
        "morph_targets": {
            "count": len(body),
            "arkit": [n for n in ARKIT if n in body],
            "visemes": [n for n in VISEMES if n in body],
            "meshes": morph_meshes,
        },
        "materials": material_summary(gltf),
        "meshes": mesh_info,
        "textures": images,
        "extensions_used": sorted(gltf.get("extensionsUsed", [])),
    }
    if validation is not None:
        manifest["validation"] = {
            "ok": validation.get("ok"),
            "checks": [c["check"] for part in ("static", "blender") if part in validation
                       for c in validation[part]["checks"]],
        }
    return manifest


def write_manifest(path: Path, manifest: dict) -> None:
    Path(path).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
