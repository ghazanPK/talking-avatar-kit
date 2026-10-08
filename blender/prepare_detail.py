"""Prepare seamless skin detail tiles for the skin detail slots (run inside background Blender).

    blender -b --factory-startup --python blender/prepare_detail.py -- \
        --in RAW_FOLDER --out assets/detail/skin [--size 1024]

Reads the tiles named after the detail slots (``face_pores_height``,
``body_skin_height``, ``palm_skin_height``, ``lips_height``,
``roughness_variation``, ``skin_color_variation_light``,
``skin_color_variation_dark``; PNG or JPEG, square, any size) and writes for
each one a processed PNG of ``--size`` pixels:

* height and roughness tiles: converted to luminance, seams repaired
  (offset-and-blend, variance preserving), resampled in the Fourier domain
  (stays seamless), contrast normalised to mean 0.5 with +-3 standard
  deviations spanning 0..1, saved as 8-bit greyscale;
* colour variation tiles: seams repaired per channel and resampled, colour
  kept, saved as 8-bit RGB.

A ``provenance.json`` next to them lists each output with the sha256 of its
input and output and the processing applied.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import numpy as np  # noqa: E402

from tak_blender import script_args  # noqa: E402
from tak_blender.skinmaps import periodic_resample, read_image, repair_seams  # noqa: E402

GREY = ("face_pores_height", "body_skin_height", "palm_skin_height", "lips_height", "roughness_variation")
COLOUR = ("skin_color_variation_light", "skin_color_variation_dark")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_png(array, path, grey):
    size = array.shape[0]
    img = bpy.data.images.new(path.stem, size, size, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "Non-Color"
    rgb = np.repeat(array, 3, axis=2) if array.shape[2] == 1 else array
    rgba = np.concatenate([np.clip(rgb, 0, 1), np.ones((size, size, 1))], axis=2).astype(np.float32)
    img.pixels.foreach_set(rgba.ravel())
    scene = bpy.context.scene
    scene.view_settings.view_transform = "Raw" if "Raw" in [
        t.identifier for t in type(scene.view_settings).bl_rna.properties["view_transform"].enum_items] else "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    settings = scene.render.image_settings
    settings.file_format = "PNG"
    settings.color_mode = "BW" if grey else "RGB"
    settings.color_depth = "8"
    settings.compression = 100
    img.save_render(str(path), scene=scene)
    bpy.data.images.remove(img)


def find(folder, stem):
    for ext in (".png", ".jpg", ".jpeg"):
        if (folder / (stem + ext)).is_file():
            return folder / (stem + ext)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="src", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--origin", default="", help="provenance text recorded in provenance.json")
    parser.add_argument("--license", default="CC-BY-4.0")
    args = parser.parse_args(script_args())
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    record = {"license": args.license, "origin": args.origin, "processing": {
        "grey": "luminance (Rec. 709 weights), seam repair (offset-and-blend per axis, variance preserving, "
                "band 25%), Fourier resampling to {0} px, contrast normalised (mean 0.5, 3 sd = 0.5)".format(args.size),
        "colour": "seam repair per channel, Fourier resampling to {0} px".format(args.size)}, "files": {}}
    for stem in GREY + COLOUR:
        path = find(src, stem)
        if path is None:
            print(f"skip {stem}: not found")
            continue
        px = read_image(path)
        grey = stem in GREY
        if grey:
            tile = (px @ np.array([0.2126, 0.7152, 0.0722]))[..., None]
        else:
            tile = px
        tile = periodic_resample(repair_seams(tile), args.size).astype(np.float64)
        if grey:
            t = tile[..., 0]
            tile = (0.5 + (t - t.mean()) / (6 * t.std() + 1e-9))[..., None]
        target = out / f"{stem}.png"
        save_png(tile, target, grey)
        record["files"][target.name] = {"input": path.name, "input_size": list(px.shape[:2]),
                                        "input_sha256": sha256(path), "sha256": sha256(target),
                                        "kind": "height/roughness (grey)" if grey else "albedo variation (RGB)"}
        print(f"wrote {target.name}")
    (out / "provenance.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


main()
