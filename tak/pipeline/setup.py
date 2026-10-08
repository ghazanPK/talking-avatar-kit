"""Install MPFB and the MakeHuman CC0 asset packs into the kit's Blender profile.

The profile lives in ``.tak/blender-user/`` (git-ignored) and is used through
``BLENDER_USER_RESOURCES``, so the user's normal Blender setup is untouched.
Downloads come from the official MakeHuman Community sources; their sha256 is
recorded in ``.tak/install.json``. Re-running is cheap: archives that are
already installed with the same hash are skipped.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from . import (MPFB_ARCHIVE_SUBDIR, MPFB_REPO, MPFB_SHA256, MPFB_URL, MPFB_VERSION, PACKS,
               PROFILE_DIR, STATE_DIR, BLENDER_SCRIPTS)
from .progress import Progress
from .tools import (ToolError, blender_version, find_blender, parse_marker, profile_dir, run_blender,
                    settings_packs_dir)

RECORD = STATE_DIR / "install.json"
DOWNLOADS = STATE_DIR / "downloads"


class SetupError(RuntimeError):
    pass


def extension_dir(profile: Path = PROFILE_DIR) -> Path:
    return profile / "extensions" / MPFB_REPO / "mpfb"


def user_data_dir(profile: Path = PROFILE_DIR, repo: str = MPFB_REPO) -> Path:
    # bpy.utils.extension_path_user("bl_ext.<repo>.mpfb") + "/data", as MPFB's LocationService uses it.
    return profile / "extensions" / ".user" / repo / "mpfb" / "data"


def installed_repo(profile: Path) -> str | None:
    """Extension repository holding MPFB in ``profile`` (the kit uses user_default)."""
    for repo in (MPFB_REPO, "blender_org"):
        if (profile / "extensions" / repo / "mpfb" / "blender_manifest.toml").is_file():
            return repo
    return None


def asset_metadata(name: str, profile: Path | None = None) -> dict | None:
    """Author, licence and source of an installed MakeHuman asset, from its pack's packs/*.json."""
    profile = profile or PROFILE_DIR
    repo = installed_repo(profile) or MPFB_REPO
    for pack in sorted((user_data_dir(profile, repo) / "packs").glob("*.json")):
        try:
            entries = json.loads(pack.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entry = entries.get(name) if isinstance(entries, dict) else None
        if isinstance(entry, dict):
            return {"name": name, "pack": pack.stem, "author": entry.get("author"),
                    "license": entry.get("license"), "source": entry.get("source")}
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_record() -> dict:
    try:
        return json.loads(RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_record(record: dict) -> None:
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def download(url: str, dest: Path, report: Callable[[str, float], None]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "talking-avatar-kit-setup"})
    with urllib.request.urlopen(request, timeout=60) as response, tmp.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done, last = 0, 0.0
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            out.write(block)
            done += len(block)
            if total and (done / total - last >= 0.1 or done == total):
                last = done / total
                report(f"{dest.name}: {done // (1 << 20)} of {total // (1 << 20)} MiB", last)
    tmp.replace(dest)
    return dest


def _safe_extract(archive: zipfile.ZipFile, members: list[zipfile.ZipInfo], target: Path,
                  strip: str = "") -> int:
    root = target.resolve()
    count = 0
    for info in members:
        name = info.filename[len(strip):] if strip else info.filename
        if not name or name.endswith("/"):
            continue
        dest = (root / name).resolve()
        if root not in dest.parents:
            raise SetupError(f"unsafe path in archive: {info.filename}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count


def locate_archive(name: str, url: str, packs_dir: Path | None, expected: str | None,
                   report: Callable[[str, float], None]) -> Path:
    """Find an archive in ``packs_dir`` (by name or hash) or the download cache, else download it."""
    candidates: list[Path] = []
    if packs_dir:
        candidates.append(packs_dir / name)
    candidates.append(DOWNLOADS / name)
    for cand in candidates:
        if cand.is_file():
            return cand
    if packs_dir and expected:
        for cand in sorted(packs_dir.glob("*.zip")):
            if sha256_file(cand) == expected:
                return cand
    report(f"downloading {url}", 0.0)
    return download(url, DOWNLOADS / name, report)


def install_mpfb(archive: Path, profile: Path, record: dict, warnings: list[str]) -> dict:
    digest = sha256_file(archive)
    if digest != MPFB_SHA256:
        warnings.append(f"MPFB archive sha256 {digest} differs from the pinned {MPFB_SHA256}")
    target = extension_dir(profile)
    previous = record.get("mpfb", {})
    if previous.get("sha256") == digest and (target / "blender_manifest.toml").is_file():
        return dict(previous, skipped=True)
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist() if m.filename.startswith(MPFB_ARCHIVE_SUBDIR)]
        if not any(m.filename == MPFB_ARCHIVE_SUBDIR + "blender_manifest.toml" for m in members):
            raise SetupError(f"{archive.name} does not contain {MPFB_ARCHIVE_SUBDIR}blender_manifest.toml")
        if target.exists():
            shutil.rmtree(target)
        count = _safe_extract(zf, members, target, strip=MPFB_ARCHIVE_SUBDIR)
    manifest = (target / "blender_manifest.toml").read_text(encoding="utf-8")
    if f'version = "{MPFB_VERSION}"' not in manifest:
        raise SetupError(f"installed MPFB is not version {MPFB_VERSION}")
    return {"version": MPFB_VERSION, "url": MPFB_URL, "archive": archive.name, "sha256": digest,
            "files": count, "repository": MPFB_REPO, "skipped": False}


def install_pack(key: str, archive: Path, profile: Path, record: dict, warnings: list[str]) -> dict:
    meta = PACKS[key]
    digest = sha256_file(archive)
    if digest != meta["sha256"]:
        warnings.append(f"{archive.name} sha256 {digest} differs from the reference {meta['sha256']}")
    data = user_data_dir(profile)
    previous = record.get("packs", {}).get(key, {})
    if previous.get("sha256") == digest and (data / "packs" / f"{previous.get('pack_json', key)}.json").is_file():
        return dict(previous, skipped=True)
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        pack_json = [m.filename for m in members if m.filename.startswith("packs/") and m.filename.endswith(".json")]
        if not pack_json:
            raise SetupError(f"{archive.name} is not an MPFB asset pack (no packs/*.json)")
        count = _safe_extract(zf, members, data)
    return {"file": archive.name, "url": meta["url"], "sha256": digest, "files": count,
            "pack_json": Path(pack_json[0]).stem, "skipped": False}


def verify_in_blender(blender: str, profile: Path) -> dict:
    """Enable MPFB in background Blender and list the installed packs."""
    info: dict = {}
    for line in run_blender(blender, BLENDER_SCRIPTS / "setup_check.py", [], profile=profile):
        payload = parse_marker(line)
        if payload and payload.get("event") == "setup_check":
            info = payload
    if not info:
        raise ToolError("Blender did not report the MPFB setup check")
    return info


def run_setup(*, blender: str | None = None, packs_dir: Path | None = None,
              profile: Path | None = None, progress: Progress | None = None,
              verify: bool = True) -> dict:
    progress = progress or Progress()
    profile = profile or profile_dir()
    packs_dir = packs_dir or settings_packs_dir()
    warnings: list[str] = []
    if packs_dir is not None and not packs_dir.is_dir():
        raise SetupError(f"--packs-dir {packs_dir} is not a folder")
    profile.mkdir(parents=True, exist_ok=True)
    record = read_record()

    step = progress.scaled(0.0, 0.25)
    archive = locate_archive(f"mpfb2-v{MPFB_VERSION}.zip", MPFB_URL, packs_dir, MPFB_SHA256,
                             lambda m, p: step.emit("mpfb", m, p))
    step.emit("mpfb", f"installing MPFB {MPFB_VERSION} from {archive.name}", 0.8)
    mpfb = install_mpfb(archive, profile, record, warnings)
    step.emit("mpfb", "MPFB already installed" if mpfb["skipped"] else f"MPFB {MPFB_VERSION} installed", 1.0)

    packs: dict[str, dict] = {}
    keys = list(PACKS)
    for index, key in enumerate(keys):
        step = progress.scaled(0.25 + 0.6 * index / len(keys), 0.25 + 0.6 * (index + 1) / len(keys))
        meta = PACKS[key]
        archive = locate_archive(meta["file"], meta["url"], packs_dir, meta["sha256"],
                                 lambda m, p, s=step: s.emit("packs", m, p * 0.5))
        step.emit("packs", f"installing {archive.name}", 0.6)
        packs[key] = install_pack(key, archive, profile, record, warnings)
        step.emit("packs", f"{key} {'already installed' if packs[key]['skipped'] else 'installed'}", 1.0)

    clean = lambda d: {k: v for k, v in d.items() if k != "skipped"}  # noqa: E731
    record = {"schema_version": 1, "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "profile": "blender-user" if profile == PROFILE_DIR else "custom (settings mpfb_profile_dir)", "mpfb": clean(mpfb),
              "packs": {k: clean(v) for k, v in packs.items()}}

    blender = find_blender(blender)
    check: dict = {"verified": False}
    if not blender:
        warnings.append("Blender not found: install Blender 4.2 or newer, then pass --blender PATH or set BLENDER")
    elif verify:
        progress.emit("verify", "enabling MPFB in background Blender", 0.9)
        info = verify_in_blender(blender, profile)
        missing = [k for k, v in packs.items() if v["pack_json"] not in info.get("packs", [])]
        if info.get("mpfb_version") != MPFB_VERSION or missing:
            raise SetupError(f"Blender check failed: MPFB {info.get('mpfb_version')}, missing packs {missing}")
        check = {"verified": True, "blender_version": blender_version(blender),
                 "mpfb_version": info.get("mpfb_version"), "packs": info.get("packs"),
                 "asset_counts": info.get("asset_counts")}
        record["blender_version"] = check["blender_version"]
    write_record(record)
    progress.emit("done", "setup complete", 1.0)
    return {"ok": True, "mpfb": record["mpfb"], "packs": record["packs"], "check": check,
            "warnings": warnings}
