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
        for key in ("roughness", "specular", "detail_normal_strength"):
            if key in skin:
                _unit(errors, f"skin.{key}", skin[key])
        if "tint" in skin:
            tint = skin["tint"]
            if not (isinstance(tint, list) and len(tint) == 3 and all(_num(v) and 0 <= v <= 1 for v in tint)):
                errors.append("skin.tint must be 3 numbers between 0 and 1 (albedo multipliers)")

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
        for key in ("default_max", "skin_max", "eyes_max"):
            value = textures.get(key)
            if not isinstance(value, int) or value not in (256, 512, 1024, 2048, 4096):
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
