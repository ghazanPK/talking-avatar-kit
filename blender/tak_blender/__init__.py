"""Helpers for kit scripts that run inside Blender (bpy available)."""
import json
import sys

MARKER = "TAK "


def emit(event, **payload):
    """Print a structured line read by tak.pipeline (``TAK {json}``)."""
    payload = dict(payload, event=event)
    sys.stdout.write(MARKER + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def progress(stage, message, value):
    emit("progress", stage=stage, message=message, progress=float(value))


def script_args():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def enable_mpfb():
    """Enable MPFB from the kit profile and return its package module.

    The kit installs MPFB into the local ``user_default`` repository; an
    existing profile that has it in ``blender_org`` works too.
    """
    import importlib
    import bpy

    errors = []
    for repo in ("user_default", "blender_org"):
        module = f"bl_ext.{repo}.mpfb"
        try:
            bpy.ops.preferences.addon_enable(module=module)
            package = importlib.import_module(module)
            importlib.import_module(module + ".services")
            return package
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{module}: {exc}")
    raise RuntimeError("MPFB is not installed in this Blender profile; run 'python -m tak setup'. "
                       + "; ".join(errors))


def mpfb_version(package):
    """Version string from the extension's blender_manifest.toml."""
    import re
    from pathlib import Path
    try:
        text = (Path(package.__file__).parent / "blender_manifest.toml").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else None
