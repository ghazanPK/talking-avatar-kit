"""Avatar specification (avatars/<slug>/spec.json): loading and validation.

A spec names MakeHuman/MPFB assets by their asset name (no file paths) plus a
few material settings. ``blender/build_avatar.py`` reads the same file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
MACROS = ("gender", "age", "muscle", "weight", "height", "proportions", "cupsize", "firmness")
RACES = ("african", "asian", "caucasian")
RIGS = ("game_engine",)
SLOTS = ("outfit", "top", "bottom", "shoes", "hat", "accessory")
EYE_MESHES = ("high-poly", "low-poly")
# Skin detail slots and regions (blender/tak_blender/skinmaps.py bakes them).
SKIN_DETAIL_SLOTS = ("face_pores_height", "body_skin_height", "palm_skin_height", "lips_height",
                     "color_variation", "roughness_variation")
SKIN_REGIONS = ("face", "lips", "palms", "body", "cheeks", "nose", "forehead", "chin", "under_eye",
                "ears", "knuckles", "elbows", "knees", "nails")
SOURCE_RE = re.compile(r"^[A-Za-z0-9_\-]+(/[A-Za-z0-9_.\-]+)*\.(png|jpg|jpeg)$", re.IGNORECASE)
TEXTURE_SIZES = (256, 512, 1024, 2048, 4096)


class SpecError(ValueError):
    """The spec file is invalid; the message lists every problem found."""


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _unit(errors: list[str], where: str, value: Any) -> None:
    if not _num(value) or not 0.0 <= value <= 1.0:
        errors.append(f"{where} must be a number between 0 and 1")


def _asset(errors: list[str], where: str, block: Any, extra: dict[str, str] | None = None) -> None:
    if not isinstance(block, dict):
        errors.append(f"{where} must be an object with an 'asset' name")
        return
    if not isinstance(block.get("asset"), str) or not NAME_RE.match(block["asset"]):
        errors.append(f"{where}.asset must be an asset name (letters, digits, _ . -)")
    for key, kind in (extra or {}).items():
        if key in block:
            if kind == "unit":
                _unit(errors, f"{where}.{key}", block[key])
            elif kind == "color":
                value = block[key]
                if not (isinstance(value, list) and len(value) in (3, 4) and all(_num(v) and 0 <= v <= 1 for v in value)):
                    errors.append(f"{where}.{key} must be 3 or 4 numbers between 0 and 1")
            elif kind == "bool" and not isinstance(block[key], bool):
                errors.append(f"{where}.{key} must be true or false")


def _range(errors: list[str], where: str, value: Any, lo: float, hi: float) -> None:
    if not _num(value) or not lo <= value <= hi:
        errors.append(f"{where} must be a number between {lo:g} and {hi:g}")


def _rgb(errors: list[str], where: str, value: Any, hi: float = 1.0) -> None:
    if not (isinstance(value, list) and len(value) == 3 and all(_num(v) and 0 <= v <= hi for v in value)):
        errors.append(f"{where} must be 3 numbers between 0 and {hi:g}")


def _skin_detail(errors: list[str], detail: Any) -> None:
    if not isinstance(detail, dict):
        errors.append("skin.detail must be an object of detail slots")
        return
    for slot, block in detail.items():
        where = f"skin.detail.{slot}"
        if slot not in SKIN_DETAIL_SLOTS:
            errors.append(f"{where} is not a detail slot ({', '.join(SKIN_DETAIL_SLOTS)})")
            continue
        if not isinstance(block, dict):
            errors.append(f"{where} must be an object")
            continue
        source = block.get("source", "procedural")
        if source != "procedural" and not (isinstance(source, str) and SOURCE_RE.match(source)
                                           and ".." not in source.split("/")):
            errors.append(f"{where}.source must be \"procedural\" or a repository-relative PNG/JPEG path")
        if "strength" in block:
            _range(errors, f"{where}.strength", block["strength"], -2.0, 2.0)
        if "tile_mm" in block:
            _range(errors, f"{where}.tile_mm", block["tile_mm"], 1.0, 2000.0)
        if "tiling" in block and not (isinstance(block["tiling"], int) and 1 <= block["tiling"] <= 512):
            errors.append(f"{where}.tiling must be an integer between 1 and 512")
        if "seed" in block and not isinstance(block["seed"], int):
            errors.append(f"{where}.seed must be an integer")
        if "rotate" in block and block["rotate"] not in (0, 90, 180, 270):
            errors.append(f"{where}.rotate must be 0, 90, 180 or 270")
        if "repair_seams" in block and not isinstance(block["repair_seams"], bool):
            errors.append(f"{where}.repair_seams must be true or false")
        unknown = set(block) - {"source", "strength", "tile_mm", "tiling", "seed", "rotate", "repair_seams"}
        if unknown:
            errors.append(f"{where} has unknown keys {sorted(unknown)}")


def _skin_regions(errors: list[str], regions: Any) -> None:
    if not isinstance(regions, dict):
        errors.append("skin.regions must be an object of regions")
        return
    for name, block in regions.items():
        where = f"skin.regions.{name}"
        if name not in SKIN_REGIONS:
            errors.append(f"{where} is not a skin region ({', '.join(SKIN_REGIONS)})")
            continue
        if not isinstance(block, dict):
            errors.append(f"{where} must be an object")
            continue
        if "tint" in block:
            _rgb(errors, f"{where}.tint", block["tint"], 2.0)
        if "amount" in block:
            _range(errors, f"{where}.amount", block["amount"], 0.0, 2.0)
        if "roughness" in block:
            _range(errors, f"{where}.roughness", block["roughness"], -1.0, 1.0)
        if "detail" in block:
            _range(errors, f"{where}.detail", block["detail"], 0.0, 4.0)
        unknown = set(block) - {"tint", "amount", "roughness", "detail"}
        if unknown:
            errors.append(f"{where} has unknown keys {sorted(unknown)}")


def validate_spec(spec: Any, slug: str | None = None) -> dict:
    """Return the spec when valid, else raise SpecError listing all problems."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    if spec.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(spec.get("slug"), str) or not SLUG_RE.match(spec["slug"]):
        errors.append("slug must be lowercase letters, digits and dashes")
    elif slug is not None and spec["slug"] != slug:
        errors.append(f"slug '{spec['slug']}' does not match its folder '{slug}'")
    for key in ("name", "description"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            errors.append(f"{key} must be a non-empty string")

    body = spec.get("body")
    if not isinstance(body, dict):
        errors.append("body must be an object of MakeHuman macro values")
    else:
        for key in MACROS:
            if key not in body:
                errors.append(f"body.{key} is required")
            else:
                _unit(errors, f"body.{key}", body[key])
        race = body.get("race")
        if not isinstance(race, dict) or set(race) != set(RACES):
            errors.append(f"body.race must give {', '.join(RACES)}")
        else:
            for key in RACES:
                _unit(errors, f"body.race.{key}", race[key])
            if all(_num(v) for v in race.values()) and sum(race.values()) <= 0:
                errors.append("body.race values must not all be zero")
        unknown = set(body) - set(MACROS) - {"race"}
        if unknown:
            errors.append(f"body has unknown keys {sorted(unknown)}")

    if spec.get("rig") not in RIGS:
        errors.append(f"rig must be one of {RIGS}")

    skin = spec.get("skin")
    if not isinstance(skin, dict) or not isinstance(skin.get("material"), str) or not NAME_RE.match(skin.get("material", "")):
        errors.append("skin.material must be a MakeHuman skin name")
    else:
        for key in ("roughness", "specular", "specular_map_strength", "cavity", "sheen"):
            if key in skin:
                _unit(errors, f"skin.{key}", skin[key])
        if "base_normal_strength" in skin:
            _range(errors, "skin.base_normal_strength", skin["base_normal_strength"], 0.0, 2.0)
        if "tint" in skin:
            tint = skin["tint"]
            if not (isinstance(tint, list) and len(tint) == 3 and all(_num(v) and 0 <= v <= 1 for v in tint)):
                errors.append("skin.tint must be 3 numbers between 0 and 1 (albedo multipliers)")
        if "sheen_color" in skin:
            _rgb(errors, "skin.sheen_color", skin["sheen_color"])
        if "detail" in skin:
            _skin_detail(errors, skin["detail"])
        if "regions" in skin:
            _skin_regions(errors, skin["regions"])

    eyes = spec.get("eyes")
    if not isinstance(eyes, dict) or eyes.get("mesh") not in EYE_MESHES or not NAME_RE.match(str(eyes.get("material", ""))):
        errors.append(f"eyes needs mesh ({'/'.join(EYE_MESHES)}) and a material name")

    for key in ("eyebrows", "eyelashes", "teeth", "tongue"):
        _asset(errors, key, spec.get(key))
    _asset(errors, "hair", spec.get("hair"), {"roughness": "unit", "base_color": "color"})

    clothes = spec.get("clothes")
    if not isinstance(clothes, list) or not clothes:
        errors.append("clothes must be a non-empty list")
    else:
        slots = []
        for index, item in enumerate(clothes):
            where = f"clothes[{index}]"
            _asset(errors, where, item, {"roughness": "unit", "base_color": "color", "keep_texture": "bool"})
            if isinstance(item, dict):
                if item.get("slot") not in SLOTS:
                    errors.append(f"{where}.slot must be one of {SLOTS}")
                slots.append(item.get("slot"))
        if len(slots) != len(set(slots)):
            errors.append("clothes slots must be unique")

    face = spec.get("face")
    if not isinstance(face, dict) or face.get("arkit") is not True or face.get("visemes") != "meta":
        errors.append("face must be {\"arkit\": true, \"visemes\": \"meta\"}")

    textures = spec.get("textures")
    if not isinstance(textures, dict):
        errors.append("textures must be an object")
    else:
        for key in ("default_max", "skin_max", "eyes_max", "skin_normal_max", "skin_roughness_max"):
            if key not in textures and key in ("skin_normal_max", "skin_roughness_max"):
                continue
            value = textures.get(key)
            if not isinstance(value, int) or value not in TEXTURE_SIZES:
                errors.append(f"textures.{key} must be one of 256, 512, 1024, 2048, 4096")

    checks = spec.get("checks")
    if not isinstance(checks, dict):
        errors.append("checks must be an object")
    else:
        height = checks.get("height_m")
        if not (isinstance(height, list) and len(height) == 2 and all(_num(v) for v in height)
                and 0.5 < height[0] < height[1] < 3.0):
            errors.append("checks.height_m must be [min, max] in metres")
        if not isinstance(checks.get("max_bytes"), int) or checks["max_bytes"] <= 0:
            errors.append("checks.max_bytes must be a positive integer")

    if errors:
        raise SpecError("; ".join(errors))
    return spec


def load_spec(path: Path) -> dict:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise SpecError(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise SpecError(f"{path} is not valid JSON: {exc}") from exc
    return validate_spec(spec, Path(path).parent.name)
