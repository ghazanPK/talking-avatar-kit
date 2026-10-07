"""Report whether MPFB and its asset packs are usable in this Blender profile.

Run: blender -b --factory-startup --python blender/setup_check.py
Prints one ``TAK {...}`` line with event "setup_check".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from tak_blender import emit, enable_mpfb, mpfb_version  # noqa: E402


def main():
    info = {"blender_version": bpy.app.version_string, "mpfb_version": None, "packs": [],
            "asset_counts": {}}
    try:
        package = enable_mpfb()
    except RuntimeError as exc:
        emit("setup_check", error=str(exc), **info)
        return
    from importlib import import_module
    services = import_module(package.__name__ + ".services")
    assets = services.AssetService
    location = services.LocationService
    location.ensure_relevant_directories_exist()
    assets.update_all_asset_lists()
    info["mpfb_version"] = mpfb_version(package)
    info["module"] = package.__name__
    info["packs"] = sorted(assets.get_pack_names())
    for category in ("skins", "eyes", "eyebrows", "eyelashes", "hair", "teeth", "tongue", "clothes"):
        if category == "skins":
            items = assets.list_mhmat_assets(category)
        else:
            items = assets.list_mhclo_assets(category)
        info["asset_counts"][category] = len(items)
    data = location.get_user_data()
    info["user_data_found"] = os.path.isdir(os.path.join(data, "packs"))
    emit("setup_check", **info)


main()
