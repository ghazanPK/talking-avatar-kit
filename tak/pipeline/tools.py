"""Find Blender and run kit scripts inside it (Linux, macOS, Windows and WSL).

Discovery order: explicit option, ``tak.platform`` (when the Studio provides
it), the user settings file, the ``BLENDER`` environment variable, ``PATH``,
then the standard install folders derived from environment variables. No
machine-specific paths are stored in the repository.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Sequence

from . import PROFILE_DIR

MARKER = "TAK "  # prefix of structured lines printed by blender/ scripts


class ToolError(RuntimeError):
    """A required external tool is missing or failed."""


@lru_cache(maxsize=1)
def is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def is_windows_exe(path: str | os.PathLike) -> bool:
    return str(path).lower().endswith(".exe")


_MNT = re.compile(r"^/mnt/([a-zA-Z])(/.*)?$")


def to_tool_path(path: str | os.PathLike, tool: str | os.PathLike | None) -> str:
    """Return ``path`` in the form the tool expects (Windows form for a Windows exe under WSL)."""
    text = str(Path(path).resolve()) if not str(path).startswith("\\\\") else str(path)
    if not (tool and is_wsl() and is_windows_exe(tool)):
        return text
    match = _MNT.match(text)
    if match:
        rest = (match.group(2) or "/").replace("/", "\\")
        return match.group(1).upper() + ":" + rest
    try:
        return subprocess.run(["wslpath", "-w", text], check=True, capture_output=True,
                              text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ToolError(f"cannot convert {text} for a Windows tool: {exc}") from exc


def from_windows_path(text: str) -> str:
    """Convert a Windows path printed by a Windows tool back to a local path under WSL."""
    if not is_wsl() or not re.match(r"^[A-Za-z]:[\\/]", text):
        return text
    return "/mnt/" + text[0].lower() + text[2:].replace("\\", "/")


def settings_path() -> Path:
    if os.environ.get("TAK_CONFIG_DIR"):
        return Path(os.environ["TAK_CONFIG_DIR"]) / "settings.json"
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "talking-avatar-kit" / "settings.json"


def user_settings() -> dict:
    """The Studio's user settings (tak.settings when present, else the same JSON file)."""
    try:
        from tak import settings as tak_settings
        data = tak_settings.load()
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001 - fall back to reading the file directly
        pass
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def profile_dir() -> Path:
    """Blender user folder with MPFB and the packs: settings ``mpfb_profile_dir`` or ``.tak/blender-user``."""
    configured = user_settings().get("mpfb_profile_dir")
    if isinstance(configured, str) and configured.strip():
        return Path(from_windows_path(configured.strip())).expanduser()
    return PROFILE_DIR


def settings_packs_dir() -> Path | None:
    configured = user_settings().get("packs_dir")
    if isinstance(configured, str) and configured.strip():
        return Path(from_windows_path(configured.strip())).expanduser()
    return None


def _settings_blender() -> str | None:
    data = user_settings()
    if not data:
        return None
    for key in ("blender", "blender_path"):
        if isinstance(data.get(key), str) and data[key]:
            return data[key]
    tools = data.get("tools")
    if isinstance(tools, dict):
        value = tools.get("blender")
        if isinstance(value, dict):
            value = value.get("path")
        if isinstance(value, str) and value:
            return value
    return None


def _windows_env(name: str) -> str | None:
    """Read a Windows environment variable (directly on Windows, through cmd.exe under WSL)."""
    if os.name == "nt":
        return os.environ.get(name)
    if not is_wsl() or not shutil.which("cmd.exe"):
        return None
    try:
        out = subprocess.run(["cmd.exe", "/d", "/c", f"echo %{name}%"], capture_output=True,
                             text=True, timeout=15, cwd=str(PROFILE_DIR.parents[1])).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out or out == f"%{name}%":
        return None
    return from_windows_path(out.splitlines()[-1].strip())


def _standard_candidates() -> list[Path]:
    found: list[Path] = []
    if sys.platform == "darwin":
        found.append(Path("/Applications/Blender.app/Contents/MacOS/Blender"))
    if os.name == "nt" or is_wsl():
        for var in ("ProgramFiles", "LOCALAPPDATA"):
            base = _windows_env(var)
            if not base:
                continue
            folder = Path(base) / "Blender Foundation"
            if folder.is_dir():
                found.extend(sorted(folder.glob("Blender*/blender.exe"), reverse=True))
            if var == "LOCALAPPDATA":
                folder = Path(base) / "Programs" / "Blender Foundation"
                if folder.is_dir():
                    found.extend(sorted(folder.glob("Blender*/blender.exe"), reverse=True))
    return found


def _platform_blender() -> str | None:
    try:
        from tak import platform as tak_platform  # provided by the Studio package
    except ImportError:
        return None
    for name in ("find_blender", "blender_path", "discover_blender"):
        func = getattr(tak_platform, name, None)
        if callable(func):
            try:
                value = func()
            except Exception:  # noqa: BLE001 - discovery must never crash the pipeline
                return None
            if isinstance(value, dict):
                value = value.get("path")
            return str(value) if value else None
    return None


def find_blender(explicit: str | None = None) -> str | None:
    """Return a usable Blender executable path or None."""
    candidates: list[str | None] = [explicit, _platform_blender(), _settings_blender(),
                                    os.environ.get("BLENDER")]
    candidates += [shutil.which("blender"), shutil.which("blender.exe")]
    for cand in candidates:
        if cand and Path(cand).is_file():
            return str(cand)
    for cand in _standard_candidates():
        if cand.is_file():
            return str(cand)
    return None


@lru_cache(maxsize=8)
def blender_version(blender: str) -> str | None:
    try:
        out = subprocess.run([blender, "--factory-startup", "--version"], capture_output=True,
                             text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"Blender\s+(\d+\.\d+(?:\.\d+)?)", out)
    return match.group(1) if match else None


class PathArg(str):
    """Marks a command-line argument as a file path to convert for the tool."""


def blender_env(blender: str, profile: Path = PROFILE_DIR) -> dict[str, str]:
    env = dict(os.environ)
    env["BLENDER_USER_RESOURCES"] = str(profile.resolve())
    if is_wsl() and is_windows_exe(blender):
        # WSLENV forwards the variable to the Windows process; /p converts the path.
        names = [n for n in env.get("WSLENV", "").split(":") if n and not n.startswith("BLENDER_USER_RESOURCES")]
        env["WSLENV"] = ":".join(names + ["BLENDER_USER_RESOURCES/p"])
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def blender_command(blender: str, script: Path, args: Sequence[str] = (), *,
                    factory: bool = True) -> list[str]:
    cmd = [blender, "-b"]
    if factory:
        cmd.append("--factory-startup")
    cmd += ["--python-exit-code", "3", "--python", to_tool_path(script, blender), "--"]
    for arg in args:
        cmd.append(to_tool_path(arg, blender) if isinstance(arg, PathArg) else str(arg))
    return cmd


def run_blender(blender: str, script: Path, args: Sequence[str] = (), *,
                profile: Path = PROFILE_DIR, log_file: Path | None = None) -> Iterator[str]:
    """Run a script in background Blender and yield its output lines.

    Raises ToolError when Blender exits with a non-zero code.
    """
    cmd = blender_command(blender, script, args)
    log = log_file.open("w", encoding="utf-8") if log_file else None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=blender_env(blender, profile), text=True,
                                encoding="utf-8", errors="replace", bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if log:
                log.write(line + "\n")
            yield line
        code = proc.wait()
    finally:
        if log:
            log.close()
    if code != 0:
        raise ToolError(f"Blender exited with code {code} running {script.name}")


def parse_marker(line: str) -> dict | None:
    """Return the JSON payload of a structured ``TAK {...}`` line, else None."""
    if not line.startswith(MARKER):
        return None
    try:
        payload = json.loads(line[len(MARKER):])
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def host_description() -> dict:
    return {"system": platform.system(), "wsl": is_wsl(), "python": platform.python_version()}
