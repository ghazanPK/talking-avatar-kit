"""User settings for the Studio and the pipeline.

Settings are stored outside the repository, in the user's configuration
folder: ``$XDG_CONFIG_HOME/talking-avatar-kit/settings.json`` (default
``~/.config``) on Linux and macOS, ``%APPDATA%\\talking-avatar-kit\\settings.json``
on Windows. ``TAK_CONFIG_DIR`` overrides the folder (used by tests).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

APP_DIR_NAME = "talking-avatar-kit"

# Known keys with their defaults. Empty strings mean "not set".
DEFAULTS: dict[str, Any] = {
    # Blender executable. Empty: discover through BLENDER, PATH and standard install folders.
    "blender_path": "",
    # Blender user folder holding MPFB and the asset packs. Empty: <repo>/.tak/blender-user.
    "mpfb_profile_dir": "",
    # Folder with already downloaded asset pack zips, passed to `tak setup --packs-dir`.
    "packs_dir": "",
    # Additional folders scanned for avatars (loose .glb files or <slug>/ folders).
    "extra_avatar_dirs": [],
}

STRING_KEYS = ("blender_path", "mpfb_profile_dir", "packs_dir")
LIST_KEYS = ("extra_avatar_dirs",)


class SettingsError(ValueError):
    """Raised for invalid setting values."""


def config_dir(env: dict[str, str] | None = None, os_name: str | None = None) -> Path:
    """Return the configuration folder for this application."""
    env = os.environ if env is None else env
    os_name = os.name if os_name is None else os_name
    override = env.get("TAK_CONFIG_DIR")
    if override:
        return Path(override)
    if os_name == "nt":
        base = env.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def settings_path(env: dict[str, str] | None = None, os_name: str | None = None) -> Path:
    return config_dir(env, os_name) / "settings.json"


def validate(updates: dict[str, Any]) -> dict[str, Any]:
    """Return a cleaned copy of ``updates``; raise SettingsError on bad input."""
    if not isinstance(updates, dict):
        raise SettingsError("settings must be a JSON object")
    clean: dict[str, Any] = {}
    for key, value in updates.items():
        if key in STRING_KEYS:
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise SettingsError(f"{key} must be a string")
            if "\x00" in value or len(value) > 4096:
                raise SettingsError(f"{key} is not a valid path")
            clean[key] = value.strip()
        elif key in LIST_KEYS:
            if value is None:
                value = []
            if isinstance(value, str):
                value = [line for line in value.splitlines()]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise SettingsError(f"{key} must be a list of strings")
            items = [v.strip() for v in value if v.strip()]
            if any("\x00" in v or len(v) > 4096 for v in items) or len(items) > 32:
                raise SettingsError(f"{key} contains an invalid path")
            clean[key] = items
        else:
            raise SettingsError(f"unknown setting: {key}")
    return clean


def load(path: Path | None = None) -> dict[str, Any]:
    """Load settings merged over the defaults. A missing or broken file yields defaults."""
    path = settings_path() if path is None else Path(path)
    data: dict[str, Any] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for key in DEFAULTS:
                if key in raw:
                    try:
                        data.update(validate({key: raw[key]}))
                    except SettingsError:
                        pass
    except (OSError, ValueError):
        pass
    merged = {key: (list(value) if isinstance(value, list) else value) for key, value in DEFAULTS.items()}
    merged.update(data)
    return merged


def save(updates: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Validate ``updates``, merge them into the stored settings and write atomically."""
    path = settings_path() if path is None else Path(path)
    clean = validate(updates)
    current = load(path)
    current.update(clean)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return current
