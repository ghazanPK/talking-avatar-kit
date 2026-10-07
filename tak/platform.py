"""Tool discovery and path conversion for Linux, macOS, Windows and WSL.

Blender is looked up, in order, from the user settings (``blender_path``),
the ``BLENDER`` environment variable, ``PATH`` and the standard install
folders derived from environment variables (``ProgramFiles``,
``ProgramFiles(x86)``, ``LOCALAPPDATA``). Under WSL the Windows variables are
read through ``cmd.exe`` and converted with ``wslpath``.

When a Windows executable (``*.exe``) is started from WSL, path arguments must
be Windows paths. :func:`convert_args` converts every :class:`pathlib.PurePath`
argument with ``wslpath -w`` in that case and leaves strings untouched.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path, PurePath
from typing import Any, Callable, Iterable

_WINDOWS_DRIVE = re.compile(r"^([A-Za-z]):[\\/]?(.*)$")
_MOUNTED_DRIVE = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")
_VERSION = re.compile(r"Blender\s+(\d+(?:\.\d+){1,2})")


# ---------------------------------------------------------------------------
# Platform detection

def is_wsl(proc_version: str | None = None) -> bool:
    """True when running inside Windows Subsystem for Linux."""
    if proc_version is None:
        if not sys.platform.startswith("linux"):
            return False
        try:
            proc_version = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
    return "microsoft" in proc_version.lower()


def platform_name() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "wsl" if is_wsl() else "linux"


# ---------------------------------------------------------------------------
# Path conversion

def _run_wslpath(flag: str, path: str) -> str | None:
    exe = shutil.which("wslpath")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, flag, path], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and value else None


def to_windows_path(path: str | PurePath, runner: Callable[[str, str], str | None] = _run_wslpath) -> str:
    """Convert a WSL path to a Windows path (``wslpath -w``).

    Paths that do not exist yet are converted through their nearest existing
    parent. Without ``wslpath`` a mounted drive (``/mnt/<drive>/...``) is converted
    by rule; other paths are returned unchanged.
    """
    text = str(path)
    if _WINDOWS_DRIVE.match(text):
        return text
    probe, tail = Path(text), []
    while not probe.exists() and probe.parent != probe:
        tail.insert(0, probe.name)
        probe = probe.parent
    converted = runner("-w", str(probe))
    if converted:
        return "\\".join([converted.rstrip("\\")] + tail) if tail else converted
    match = _MOUNTED_DRIVE.match(text)
    if match:
        drive, rest = match.group(1).upper(), (match.group(2) or "")
        return f"{drive}:\\" + rest.replace("/", "\\")
    return text


def to_wsl_path(path: str, runner: Callable[[str, str], str | None] = _run_wslpath) -> str:
    """Convert a Windows path (``X:\\...``) to its WSL form (``wslpath -u``)."""
    match = _WINDOWS_DRIVE.match(path)
    if not match:
        return path
    converted = runner("-u", path)
    if converted:
        return converted
    drive, rest = match.group(1).lower(), match.group(2).replace("\\", "/")
    return "/mnt/" + drive + ("/" + rest if rest else "")


def needs_windows_paths(executable: str | PurePath, wsl: bool | None = None) -> bool:
    """True when ``executable`` is a Windows program started from WSL."""
    wsl = is_wsl() if wsl is None else wsl
    return bool(wsl) and str(executable).lower().endswith(".exe")


def tool_path(executable: str | PurePath, path: str | PurePath, wsl: bool | None = None) -> str:
    """Return ``path`` in the form ``executable`` expects."""
    if needs_windows_paths(executable, wsl):
        return to_windows_path(path)
    return str(path)


def convert_args(executable: str | PurePath, args: Iterable[Any], wsl: bool | None = None) -> list[str]:
    """Convert :class:`PurePath` arguments for ``executable``; strings pass through."""
    convert = needs_windows_paths(executable, wsl)
    out = []
    for arg in args:
        if isinstance(arg, PurePath):
            out.append(to_windows_path(arg) if convert else str(arg))
        else:
            out.append(str(arg))
    return out


# ---------------------------------------------------------------------------
# Windows environment variables (also from WSL)

@lru_cache(maxsize=None)
def _wsl_windows_env(name: str) -> str | None:
    cmd = shutil.which("cmd.exe")
    if not cmd:
        return None
    try:
        out = subprocess.run([cmd, "/d", "/c", f"echo %{name}%"], capture_output=True,
                             text=True, timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    if not value or value == f"%{name}%":
        return None
    return to_wsl_path(value)


def windows_env(name: str, env: dict[str, str] | None = None, wsl: bool | None = None) -> str | None:
    """Value of a Windows environment variable, as a path usable from this process."""
    env = os.environ if env is None else env
    value = env.get(name)
    if value:
        return value
    if (is_wsl() if wsl is None else wsl):
        return _wsl_windows_env(name)
    return None


# ---------------------------------------------------------------------------
# Blender discovery

def _version_key(path: str) -> tuple:
    numbers = re.findall(r"\d+", Path(path).parent.name)
    return tuple(int(n) for n in numbers) if numbers else (0,)


def _windows_install_candidates(get_env: Callable[[str], str | None],
                                globber: Callable[[str], list[str]]) -> list[str]:
    found: list[str] = []
    bases = []
    for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = get_env(name)
        if base and base not in bases:
            bases.append(base)
    local = get_env("LOCALAPPDATA")
    for base in bases:
        matches = globber(os.path.join(base, "Blender Foundation", "Blender*", "blender.exe"))
        found.extend(sorted(matches, key=_version_key, reverse=True))
        found.append(os.path.join(base, "Steam", "steamapps", "common", "Blender", "blender.exe"))
    if local:
        matches = globber(os.path.join(local, "Programs", "Blender Foundation", "Blender*", "blender.exe"))
        found.extend(sorted(matches, key=_version_key, reverse=True))
    return found


def _macos_install_candidates(home: str) -> list[str]:
    return [os.path.join(prefix, "Blender.app", "Contents", "MacOS", "Blender")
            for prefix in ("/Applications", os.path.join(home, "Applications"))]


def blender_candidates(settings: dict | None = None,
                       env: dict[str, str] | None = None,
                       which: Callable[[str], str | None] = shutil.which,
                       wsl: bool | None = None,
                       os_name: str | None = None,
                       sys_platform: str | None = None,
                       get_windows_env: Callable[[str], str | None] | None = None,
                       globber: Callable[[str], list[str]] = glob.glob,
                       exists: Callable[[str], bool] = os.path.isfile) -> list[dict]:
    """Ordered Blender candidates: ``[{path, source, exists}]`` without duplicates.

    ``settings=None`` reads the user settings file; pass ``{}`` to ignore it.
    """
    if settings is None:
        from . import settings as tak_settings
        settings = tak_settings.load()
    env = os.environ if env is None else env
    os_name = os.name if os_name is None else os_name
    sys_platform = sys.platform if sys_platform is None else sys_platform
    wsl = is_wsl() if wsl is None and os_name != "nt" else bool(wsl)
    if get_windows_env is None:
        def get_windows_env(name: str) -> str | None:
            return windows_env(name, env=env, wsl=wsl)

    raw: list[tuple[str, str]] = []
    configured = settings.get("blender_path") or ""
    if configured:
        raw.append((configured, "settings"))
    if env.get("BLENDER"):
        raw.append((env["BLENDER"], "env:BLENDER"))
    for name in ("blender", "blender.exe") if (wsl or os_name == "nt") else ("blender",):
        hit = which(name)
        if hit:
            raw.append((hit, "PATH"))
    if os_name == "nt" or wsl:
        raw.extend((p, "standard") for p in _windows_install_candidates(get_windows_env, globber))
    if sys_platform == "darwin":
        raw.extend((p, "standard") for p in _macos_install_candidates(env.get("HOME", str(Path.home()))))

    seen, out = set(), []
    for path, source in raw:
        if wsl:
            path = to_wsl_path(path)
        key = os.path.normcase(os.path.normpath(path))
        if key in seen:
            continue
        seen.add(key)
        out.append({"path": path, "source": source, "exists": bool(exists(path))})
    return out


def find_blender(settings: dict | None = None, **kwargs) -> dict | None:
    """First existing Blender candidate (``{path, source, exists}``) or None.

    ``settings=None`` reads the user settings file (``blender_path``).
    """
    for candidate in blender_candidates(settings, **kwargs):
        if candidate["exists"]:
            return candidate
    return None


def parse_blender_version(text: str) -> str | None:
    match = _VERSION.search(text or "")
    return match.group(1) if match else None


_version_cache: dict[tuple[str, float], str | None] = {}


def blender_version(path: str, timeout: float = 90) -> str | None:
    """Run ``blender --version`` and return e.g. ``"4.2.3"`` (cached per file mtime)."""
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    key = (path, stamp)
    if key not in _version_cache:
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True,
                                 timeout=timeout, stdin=subprocess.DEVNULL,
                                 encoding="utf-8", errors="replace")
            _version_cache[key] = parse_blender_version(out.stdout + "\n" + out.stderr)
        except (OSError, subprocess.SubprocessError):
            _version_cache[key] = None
    return _version_cache[key]


def describe(settings: dict | None = None, with_version: bool = True) -> dict:
    """Summary used by the Studio settings page."""
    candidates = blender_candidates(settings)
    chosen = next((c for c in candidates if c["exists"]), None)
    blender = {"found": chosen is not None, "candidates": candidates}
    if chosen:
        blender.update(path=chosen["path"], source=chosen["source"],
                       windows_exe_from_wsl=needs_windows_paths(chosen["path"]))
        if with_version:
            blender["version"] = blender_version(chosen["path"])
    return {
        "platform": platform_name(),
        "python": {"executable": sys.executable, "version": sys.version.split()[0]},
        "blender": blender,
    }
