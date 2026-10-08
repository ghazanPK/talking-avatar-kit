"""Build avatars from their specs with headless Blender, validate, publish and write manifests.

Work happens in ``.tak/work/<slug>/``; the GLB and preview are copied to
``avatars/<slug>/`` only after validation passes, so a failed build never
replaces a good avatar.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import AVATARS_DIR, BLENDER_SCRIPTS, STATE_DIR
from .manifest import build_manifest, write_manifest
from .progress import Progress
from .setup import asset_metadata, installed_repo, read_record
from .spec import load_spec
from .tools import PathArg, ToolError, find_blender, parse_marker, profile_dir, run_blender
from .validate import validate_glb

WORK_DIR = STATE_DIR / "work"
LOG_DIR = STATE_DIR / "logs"


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(AVATARS_DIR.parent.resolve()).as_posix()
    except ValueError:
        return path.name


def build_one(slug: str, blender: str, *, validate: bool = True, preview: bool = True,
              keep_blend: bool = False, progress: Progress) -> dict:
    spec_path = AVATARS_DIR / slug / "spec.json"
    spec = load_spec(spec_path)
    work = WORK_DIR / slug
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f"build-{slug}.log"

    args = ["--spec", PathArg(spec_path), "--out-dir", PathArg(work)]
    if preview:
        args.append("--preview")
    if keep_blend:
        args += ["--blend", PathArg(work / f"{slug}.blend")]

    blender_part = progress.scaled(0.0, 0.8)
    blender_part.emit("blender", f"starting Blender for {slug}", 0.0)
    result: dict = {}
    try:
        for line in run_blender(blender, BLENDER_SCRIPTS / "build_avatar.py", args,
                                profile=profile_dir(), log_file=log):
            data = parse_marker(line)
            if not data:
                continue
            if data.get("event") == "progress":
                blender_part.emit(data.get("stage", "blender"), data.get("message", ""),
                                  float(data.get("progress", 0.0)))
            elif data.get("event") == "result":
                result = data
    except ToolError as exc:
        raise ToolError(f"{exc}; see .tak/logs/{log.name}") from exc
    glb = work / f"{slug}.glb"
    if not result or not glb.is_file():
        raise ToolError(f"Blender finished without producing {glb.name}; see .tak/logs/{log.name}")

    validation = None
    if validate:
        validation = validate_glb(glb, spec, blender=blender, progress=progress.scaled(0.8, 0.95))
        if not validation["ok"]:
            return {"ok": False, "slug": slug, "error": "validation failed",
                    "validation": _brief(validation), "log": f".tak/logs/{log.name}"}

    out = AVATARS_DIR / slug
    shutil.copy2(glb, out / glb.name)
    preview_name = None
    if preview and (work / "preview.png").is_file():
        shutil.copy2(work / "preview.png", out / "preview.png")
        preview_name = "preview.png"
    elif (out / "preview.png").is_file():
        preview_name = "preview.png"
    manifest = build_manifest(spec, out / glb.name, build=result, install=read_record(),
                              preview=preview_name, validation=validation,
                              skin_asset=asset_metadata(spec["skin"]["material"], profile_dir()))
    write_manifest(out / "manifest.json", manifest)
    progress.emit("publish", f"wrote {_rel(out / glb.name)} ({manifest['bytes']} bytes) and manifest.json", 1.0)
    return {"ok": True, "slug": slug, "glb": _rel(out / glb.name), "manifest": _rel(out / "manifest.json"),
            "preview": _rel(out / "preview.png") if preview_name else None, "bytes": manifest["bytes"],
            "sha256": manifest["sha256"], "height_m": manifest["height_m"],
            "validation": _brief(validation), "log": f".tak/logs/{log.name}"}


def _brief(validation: dict | None) -> dict | None:
    """Validation outcome without the bulky GLB details (those are in manifest.json)."""
    if validation is None:
        return None
    return {"ok": validation["ok"],
            **{part: {"ok": validation[part]["ok"], "failures": validation[part]["failures"],
                      "checks": [f"{c['check']}: {c['detail']}" for c in validation[part]["checks"]]}
               for part in ("static", "blender") if part in validation}}


def run_builds(slugs: list[str], *, blender: str | None = None, validate: bool = True,
               preview: bool = True, keep_blend: bool = False, progress: Progress | None = None) -> dict:
    progress = progress or Progress()
    exe = find_blender(blender)
    if not exe:
        raise ToolError("Blender not found: pass --blender PATH, set BLENDER, or add it to the settings")
    if installed_repo(profile_dir()) is None:
        raise ToolError("MPFB is not installed in the kit profile; run 'python -m tak setup' first")
    results = {}
    for index, slug in enumerate(slugs):
        part = progress.scaled(index / len(slugs), (index + 1) / len(slugs))
        part.emit("build", f"building {slug} ({index + 1} of {len(slugs)})", 0.0)
        try:
            results[slug] = build_one(slug, exe, validate=validate, preview=preview,
                                      keep_blend=keep_blend, progress=part)
        except Exception as exc:  # noqa: BLE001 - report per avatar, continue with the next
            results[slug] = {"ok": False, "slug": slug, "error": str(exc)}
            part.emit("build", f"{slug} failed: {exc}", 1.0)
    return {"ok": all(r["ok"] for r in results.values()), "avatars": results}
