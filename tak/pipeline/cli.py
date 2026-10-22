"""Command-line entry points used by ``python -m tak`` and the Studio job runner.

``setup_main``, ``build_main`` and ``check_main`` take an argv list (without
the sub-command name) and return a process exit code. ``setup`` and ``build``
print JSON progress lines and a final ``{"result": ...}`` line on stdout;
``check`` prints one JSON object.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Sequence

from . import AVATARS_DIR, MPFB_VERSION, PACKS, PROFILE_DIR
from .progress import Progress


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that raises instead of exiting, so callers get an exit code."""

    def error(self, message):  # noqa: D401
        raise SystemExit(f"{self.prog}: error: {message}")


def _fail(progress: Progress, stage: str, exc: BaseException, debug: bool) -> int:
    if debug:
        traceback.print_exc(file=sys.stderr)
    message = str(exc) or exc.__class__.__name__
    progress.emit(stage, f"failed: {message}", 1.0)
    progress.result({"ok": False, "error": message})
    return 1


def setup_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="tak setup", description=(
        f"Install MPFB {MPFB_VERSION} and the MakeHuman CC0 packs into the kit's Blender profile."))
    parser.add_argument("--blender", help="Blender executable (default: discovered)")
    parser.add_argument("--packs-dir", type=Path,
                        help="folder with pre-downloaded archives instead of downloading")
    parser.add_argument("--no-verify", action="store_true", help="skip the background Blender check")
    parser.add_argument("--debug", action="store_true", help="print tracebacks on stderr")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="tak build", description="Build avatars/<slug>/ from spec.json with headless Blender.")
    parser.add_argument("slugs", nargs="*", help="avatar slugs (folders under avatars/)")
    parser.add_argument("--all", action="store_true", help="build every avatar that has a spec.json")
    parser.add_argument("--blender", help="Blender executable (default: discovered)")
    parser.add_argument("--no-validate", action="store_true", help="skip validation after the build")
    parser.add_argument("--no-preview", action="store_true", help="skip the preview render")
    parser.add_argument("--keep-blend", action="store_true",
                        help="also save the working .blend file under .tak/work/")
    parser.add_argument("--debug", action="store_true", help="print tracebacks on stderr")
    return parser


def check_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="tak check", description="Report tool availability as JSON.")
    parser.add_argument("--blender", help="Blender executable (default: discovered)")
    parser.add_argument("--deep", action="store_true",
                        help="also start background Blender and enable MPFB")
    return parser


def validate_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="tak validate", description="Validate built avatar GLBs.")
    parser.add_argument("slugs", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--blender", help="Blender executable (default: discovered)")
    parser.add_argument("--static-only", action="store_true", help="skip the Blender re-import check")
    return parser


def _parse(parser: argparse.ArgumentParser, argv: Sequence[str] | None):
    try:
        return parser.parse_args(list(argv) if argv is not None else None), None
    except SystemExit as exc:
        if exc.code in (0, None):
            return None, 0
        print(exc.code if isinstance(exc.code, str) else "invalid arguments", file=sys.stderr)
        return None, 2


def resolve_slugs(slugs: Sequence[str], all_: bool, root: Path = AVATARS_DIR) -> list[str]:
    available = sorted(p.parent.name for p in root.glob("*/spec.json"))
    if all_:
        if slugs:
            raise ValueError("give slugs or --all, not both")
        if not available:
            raise ValueError(f"no avatars/<slug>/spec.json found")
        return available
    if not slugs:
        raise ValueError("name at least one avatar slug or pass --all")
    unknown = [s for s in slugs if s not in available]
    if unknown:
        raise ValueError(f"unknown avatar(s) {', '.join(unknown)}; available: {', '.join(available) or 'none'}")
    return list(dict.fromkeys(slugs))


def setup_main(argv: Sequence[str] | None = None) -> int:
    args, code = _parse(setup_parser(), argv)
    if args is None:
        return code
    progress = Progress()
    from .setup import run_setup
    try:
        result = run_setup(blender=args.blender, packs_dir=args.packs_dir, progress=progress,
                           verify=not args.no_verify)
    except Exception as exc:  # noqa: BLE001
        return _fail(progress, "setup", exc, args.debug)
    progress.result(result)
    return 0


def build_main(argv: Sequence[str] | None = None) -> int:
    args, code = _parse(build_parser(), argv)
    if args is None:
        return code
    progress = Progress()
    try:
        slugs = resolve_slugs(args.slugs, args.all)
    except ValueError as exc:
        print(f"tak build: error: {exc}", file=sys.stderr)
        progress.result({"ok": False, "error": str(exc)})
        return 2
    from .build import run_builds
    try:
        result = run_builds(slugs, blender=args.blender, validate=not args.no_validate,
                            preview=not args.no_preview, keep_blend=args.keep_blend,
                            progress=progress)
    except Exception as exc:  # noqa: BLE001
        return _fail(progress, "build", exc, args.debug)
    progress.result(result)
    return 0 if result.get("ok") else 1


def validate_main(argv: Sequence[str] | None = None) -> int:
    args, code = _parse(validate_parser(), argv)
    if args is None:
        return code
    progress = Progress()
    try:
        slugs = resolve_slugs(args.slugs, args.all)
    except ValueError as exc:
        print(f"tak validate: error: {exc}", file=sys.stderr)
        progress.result({"ok": False, "error": str(exc)})
        return 2
    from .validate import validate_avatar
    reports = {}
    for index, slug in enumerate(slugs):
        sub = progress.scaled(index / len(slugs), (index + 1) / len(slugs))
        reports[slug] = validate_avatar(slug, blender=None if args.static_only else (args.blender or True),
                                        progress=sub)
    ok = all(r["ok"] for r in reports.values())
    progress.result({"ok": ok, "avatars": reports})
    return 0 if ok else 1


def check_main(argv: Sequence[str] | None = None) -> int:
    args, code = _parse(check_parser(), argv)
    if args is None:
        return code
    print(json.dumps(collect_check(args.blender, deep=args.deep), indent=2))
    return 0


def collect_check(blender_option: str | None = None, *, deep: bool = False) -> dict:
    import platform
    from .setup import installed_repo, read_record, user_data_dir
    from .tools import (blender_version, find_blender, host_description, is_windows_exe, is_wsl,
                        profile_dir)

    record = read_record()
    blender = find_blender(blender_option)
    profile = profile_dir()
    repo = installed_repo(profile)
    data = user_data_dir(profile, repo or "user_default")
    packs = {key: (data / "packs" / f"{record.get('packs', {}).get(key, {}).get('pack_json', key)}.json").is_file()
             for key in PACKS}
    report = {
        "python": {"ok": sys.version_info >= (3, 10), "version": platform.python_version(),
                   "executable": sys.executable},
        "host": host_description(),
        "blender": {"ok": bool(blender), "path": blender,
                    "version": blender_version(blender) if blender else None,
                    "windows_exe_from_wsl": bool(blender and is_wsl() and is_windows_exe(blender))},
        "mpfb": {"ok": repo is not None, "required": MPFB_VERSION, "repository": repo,
                 "installed": record.get("mpfb", {}).get("version") if repo else None},
        "packs": {"ok": all(packs.values()), "installed": packs},
        "profile": {"exists": profile.is_dir(), "path": str(profile), "default": profile == PROFILE_DIR},
    }
    if blender and deep and report["mpfb"]["ok"]:
        from .setup import verify_in_blender
        try:
            report["mpfb"]["blender_check"] = verify_in_blender(blender, profile)
        except Exception as exc:  # noqa: BLE001
            report["mpfb"]["blender_check"] = {"error": str(exc)}
    if blender:
        version = report["blender"]["version"] or "0"
        major_minor = tuple(int(p) for p in version.split(".")[:2] if p.isdigit())
        report["blender"]["ok"] = major_minor >= (4, 2)
    report["ready"] = all(report[k]["ok"] for k in ("python", "blender", "mpfb", "packs"))
    return report


def export_main(argv: Sequence[str] | None = None) -> int:
    """``export fbx <slug>|--all ...``: Unity-ready FBX export (see tak.pipeline.export)."""
    from .export import export_main as run_export

    return run_export(argv)


COMMANDS = {"setup": setup_main, "build": build_main, "check": check_main, "validate": validate_main,
            "export": export_main}


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        print("usage: python -m tak.pipeline {setup,build,check,validate,export} [options]", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])
