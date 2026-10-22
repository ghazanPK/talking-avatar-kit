"""Unity side of the FBX export: find the editor, install exports into a project, batch-mode check.

The check creates (or reuses) a scratch project in ``build/unity-check/project``,
embeds the kit's ``unity/`` package, copies the exported avatars to
``Assets/TalkingAvatarKit/Avatars/<slug>/`` and runs

    Unity -batchmode -quit -projectPath ... -executeMethod TalkingAvatarKit.Editor.AvatarCheck.RunBatch

which imports the avatars, validates them (humanoid avatar, bone map, blendshapes,
materials, scale, orientation, T-pose reference) for each render pipeline and
renders preview PNGs. Unity is found through ``--unity-exe``, the ``UNITY``
environment variable, the user settings (``unity_path``), ``PATH`` or the
standard Unity Hub install folders; no machine paths are stored in the repository.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from . import KIT_ROOT
from .progress import Progress

PACKAGE_DIR = KIT_ROOT / "unity"
PACKAGE_NAME = "com.ghazanpk.talking-avatar-kit"
CHECK_ROOT = KIT_ROOT / "build" / "unity-check"
AVATARS_SUBDIR = Path("Assets") / "TalkingAvatarKit" / "Avatars"
EXPORT_FILES = ("*.fbx", "*.tak.json", "LICENSE.md")
CHECK_METHOD = "TalkingAvatarKit.Editor.AvatarCheck.RunBatch"
LICENSING_HINTS = ("licens", "entitlement", "serial", "activation", "no valid unity")


# --------------------------------------------------------------------------- discovery

def _hub_candidates() -> list[Path]:
    from .tools import _windows_env, is_wsl

    found: list[Path] = []
    roots: list[Path] = []
    if os.name == "nt" or is_wsl():
        for var in ("ProgramFiles", "ProgramW6432"):
            base = _windows_env(var)
            if base:
                roots.append(Path(base) / "Unity" / "Hub" / "Editor")
        for root in dict.fromkeys(roots):
            if root.is_dir():
                found.extend(sorted(root.glob("*/Editor/Unity.exe"), key=_version_key, reverse=True))
    elif sys.platform == "darwin":
        root = Path("/Applications/Unity/Hub/Editor")
        if root.is_dir():
            found.extend(sorted(root.glob("*/Unity.app/Contents/MacOS/Unity"), key=_version_key, reverse=True))
    else:
        root = Path.home() / "Unity" / "Hub" / "Editor"
        if root.is_dir():
            found.extend(sorted(root.glob("*/Editor/Unity"), key=_version_key, reverse=True))
    return found


def _version_key(path: Path) -> tuple:
    for part in path.parts:
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)([abfp])(\d+)", part)
        if match:
            return tuple(int(g) if g.isdigit() else g for g in match.groups())
    return (0,)


def _settings_unity() -> str | None:
    from .tools import from_windows_path, user_settings

    data = user_settings()
    for key in ("unity_path", "unity"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return from_windows_path(value.strip())
    tools = data.get("tools")
    if isinstance(tools, dict):
        value = tools.get("unity")
        if isinstance(value, dict):
            value = value.get("path")
        if isinstance(value, str) and value.strip():
            return from_windows_path(value.strip())
    return None


def find_unity(explicit: str | None = None) -> str | None:
    """A Unity editor executable, or None."""
    from .tools import from_windows_path

    env = os.environ.get("UNITY")
    for cand in (explicit, from_windows_path(env) if env else None, _settings_unity()):
        if cand and Path(cand).is_file():
            return str(cand)
    for cand in _hub_candidates():
        if cand.is_file():
            return str(cand)
    # Last resort: PATH, but only a real editor (other tools named Unity.exe exist, e.g. command-line helpers).
    for cand in (shutil.which("Unity"), shutil.which("Unity.exe")):
        if cand and is_editor(Path(cand)):
            return str(cand)
    return None


def is_editor(path: Path) -> bool:
    """True when ``path`` sits in a Unity editor install (Data folder next to it, or a macOS bundle)."""
    return (path.parent / "Data" / "Resources").is_dir() or (path.parent.parent / "Resources" / "Data").is_dir() \
        or path.parent.name == "MacOS"


def unity_version(unity: str) -> str | None:
    match = re.search(r"(\d+\.\d+\.\d+[abfp]\d+)", str(unity))
    return match.group(1) if match else None


def builtin_package_version(unity: str, name: str) -> str | None:
    """Version of a package that ships inside the editor (e.g. URP in Unity 6)."""
    exe = Path(unity)
    for base in (exe.parent / "Data", exe.parent.parent / "Resources" / "Data", exe.parent.parent / "Resources"):
        manifest = base / "Resources" / "PackageManager" / "BuiltInPackages" / name / "package.json"
        if manifest.is_file():
            try:
                return json.loads(manifest.read_text(encoding="utf-8")).get("version")
            except ValueError:
                return None
    return None


# --------------------------------------------------------------------------- project setup

def copy_package(dest_packages: Path) -> Path:
    target = dest_packages / PACKAGE_NAME
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(PACKAGE_DIR, target, ignore=shutil.ignore_patterns("*.meta.tmp"))
    return target


def copy_exports(out_root: Path, slugs: Sequence[str], assets_dir: Path) -> list[str]:
    copied = []
    for slug in slugs:
        src = out_root / slug
        if not (src / f"{slug}.fbx").is_file():
            raise FileNotFoundError(f"no export for {slug} in {src}; run 'python -m tak export fbx {slug}' first")
        dst = assets_dir / slug
        dst.mkdir(parents=True, exist_ok=True)
        for pattern in EXPORT_FILES:
            for file in src.glob(pattern):
                shutil.copy2(file, dst / file.name)
        tex_dst = dst / "textures"
        tex_dst.mkdir(exist_ok=True)
        for file in (src / "textures").iterdir():
            shutil.copy2(file, tex_dst / file.name)
        copied.append(slug)
    return copied


def write_manifest(project: Path, extra: dict[str, str]) -> None:
    """Create or update Packages/manifest.json with the given dependencies."""
    path = project / "Packages" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"dependencies": {}}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    deps = data.setdefault("dependencies", {})
    deps.update(extra)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def install_into_project(project: Path, out_root: Path, slugs: Sequence[str]) -> dict:
    """Copy the package (embedded in Packages/) and the exported avatars into an existing Unity project."""
    project = Path(project).resolve()
    if not (project / "Assets").is_dir():
        raise FileNotFoundError(f"{project} is not a Unity project (no Assets folder)")
    copy_package(project / "Packages")
    avatars = copy_exports(out_root, slugs, project / AVATARS_SUBDIR)
    return {"project": str(project), "package": f"Packages/{PACKAGE_NAME}",
            "avatars": [(AVATARS_SUBDIR / s).as_posix() for s in avatars]}


def prepare_check_project(project: Path, out_root: Path, slugs: Sequence[str], unity: str,
                          pipelines: Sequence[str]) -> dict:
    (project / "Assets").mkdir(parents=True, exist_ok=True)
    avatars_dir = project / AVATARS_SUBDIR
    if avatars_dir.exists():
        shutil.rmtree(avatars_dir)
    copy_package(project / "Packages")
    deps = {"com.unity.modules.animation": "1.0.0", "com.unity.modules.imageconversion": "1.0.0",
            "com.unity.modules.jsonserialize": "1.0.0", "com.unity.modules.uielements": "1.0.0",
            "com.unity.modules.imgui": "1.0.0"}
    info = {"project": _display(project)}
    if "urp" in pipelines:
        version = builtin_package_version(unity, "com.unity.render-pipelines.universal")
        if version:
            deps["com.unity.render-pipelines.universal"] = version
            info["urp"] = version
        else:
            info["urp"] = "not bundled with this editor; the URP check needs network access to the registry"
            deps["com.unity.render-pipelines.universal"] = "17.0.3"
    write_manifest(project, deps)
    info["avatars"] = copy_exports(out_root, slugs, avatars_dir)
    return info


# --------------------------------------------------------------------------- batch run

def run_unity_check(out_root: Path, slugs: Sequence[str], *, unity: str | None = None,
                    pipelines: Sequence[str] = ("builtin", "urp"), project: Path | None = None,
                    progress: Progress | None = None, timeout: int = 3600,
                    extra_args: Sequence[str] = ()) -> dict:
    """Import and validate the exports in Unity batch mode; returns the report (``ran`` False if Unity is missing)."""
    from .tools import to_tool_path

    progress = progress or Progress()
    exe = find_unity(unity)
    if not exe:
        return {"ran": False, "ok": False,
                "error": "Unity not found: set UNITY to the editor executable or pass --unity-exe"}
    project = Path(project or CHECK_ROOT / "project").resolve()
    work = project.parent
    previews = work / "previews"
    if previews.exists():
        shutil.rmtree(previews)
    previews.mkdir(parents=True)
    report_file = work / "report.json"
    log_file = work / "unity.log"
    for stale in (report_file,):
        if stale.exists():
            stale.unlink()
    progress.emit("unity", f"preparing {_display(project)}", 0.05)
    setup = prepare_check_project(project, out_root, slugs, exe, pipelines)
    cmd = [exe, "-batchmode", "-quit", "-projectPath", to_tool_path(project, exe),
           "-executeMethod", CHECK_METHOD,
           "-takReport", to_tool_path(report_file, exe), "-takPreviews", to_tool_path(previews, exe),
           "-takPipelines", ",".join(pipelines), "-logFile", to_tool_path(log_file, exe), *extra_args]
    progress.emit("unity", f"running Unity {unity_version(exe) or ''} in batch mode ({', '.join(pipelines)})", 0.1)
    started = time.time()
    try:
        code = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(work)).returncode
    except subprocess.TimeoutExpired:
        code = None
    elapsed = round(time.time() - started, 1)
    result: dict = {"ran": True, "unity": unity_version(exe), "exit_code": code, "seconds": elapsed,
                    "setup": setup, "log": _display(log_file), "previews": _display(previews)}
    if report_file.is_file():
        report = json.loads(report_file.read_text(encoding="utf-8"))
        result["report"] = report
        result["ok"] = bool(report.get("ok")) and code == 0
        result["summary"] = summarize(report)
    else:
        result["ok"] = False
        result["error"] = diagnose_log(log_file, code)
    result["preview_files"] = sorted(p.name for p in previews.glob("*.png"))
    progress.emit("unity", f"Unity check {'passed' if result['ok'] else 'failed'} in {elapsed} s", 1.0)
    return result


def summarize(report: dict) -> dict:
    out: dict = {}
    cross = report.get("cross_pipeline")
    if cross:
        failed = {f"{slug}/{view}": res.get("failed") for slug, views in (cross.get("avatars") or {}).items()
                  for view, res in views.items() if not res.get("ok")}
        out["cross_pipeline"] = {"ok": cross.get("ok"), "tolerance": cross.get("tolerance"), "failed": failed}
    for pipeline, data in (report.get("pipelines") or {}).items():
        avatars = {}
        for slug, res in (data.get("avatars") or {}).items():
            failed = [f"{c['check']}: {c['detail']}" for c in res.get("checks", []) if not c.get("ok")]
            avatars[slug] = "ok" if res.get("ok") else (failed or [res.get("error", "failed")])
        out[pipeline] = {"ok": data.get("ok"), "shader": data.get("shader"), "avatars": avatars,
                         "log_errors": len(data.get("log_errors") or [])}
    return out


def diagnose_log(log_file: Path, code: int | None) -> str:
    """Explain a Unity run that produced no report (licensing, compile errors, timeouts)."""
    if code is None:
        return "Unity timed out"
    if not log_file.is_file():
        return f"Unity exited with code {code} and wrote no log"
    text = log_file.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    licence = [ln.strip() for ln in lines if any(h in ln.lower() for h in LICENSING_HINTS)
               and ("error" in ln.lower() or "fail" in ln.lower() or "no valid" in ln.lower())]
    if licence:
        return "Unity licensing failed: " + " | ".join(dict.fromkeys(licence[:6]))
    compile_errors = [ln.strip() for ln in lines if "error CS" in ln]
    if compile_errors:
        return "script compile errors: " + " | ".join(dict.fromkeys(compile_errors[:6]))
    tail = [ln.strip() for ln in lines[-15:] if ln.strip()]
    return f"Unity exited with code {code} without a report; log tail: " + " | ".join(tail)


def _display(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(KIT_ROOT).as_posix()
    except ValueError:
        return str(path)
