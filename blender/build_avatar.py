"""Build one avatar GLB from avatars/<slug>/spec.json with MPFB (run inside background Blender).

    blender -b --factory-startup --python blender/build_avatar.py -- \
        --spec avatars/rowan/spec.json --out-dir avatars/rowan [--preview] [--blend work.blend]

The kit's Blender profile (BLENDER_USER_RESOURCES) must contain MPFB and the
MakeHuman packs; ``python -m tak setup`` installs them. ``python -m tak build``
runs this script, validates the result and writes manifest.json.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from tak_blender import emit, enable_mpfb, mpfb_version, progress, script_args  # noqa: E402
from tak_blender import export, materials, render, rigfix, scene, skinmaps, weights  # noqa: E402

KIT_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent

# Proxies that receive the face targets through their MHCLO binding.
FACE_PROXIES = ("eyes", "eyebrows", "eyelashes", "teeth", "tongue")
CREDIT = "talking-avatar-kit by Ghazanfar Ali"
OBJECT_NAMES = {"body": "Body", "eyes": "Eyes", "eyebrows": "Eyebrows", "eyelashes": "Eyelashes",
                "teeth": "Teeth", "tongue": "Tongue", "hair": "Hair"}


def parse():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--blend", help="also save the working .blend here")
    parser.add_argument("--dump-maps", help="also write the skin's region masks and baked maps as PNG here")
    return parser.parse_args(script_args())


def build(spec, out_dir, want_preview, blend_path, dump_maps=None):
    slug = spec["slug"]
    limits = spec["textures"]
    progress("blender", "enabling MPFB", 0.02)
    package = enable_mpfb()
    mpfb = scene.Mpfb(package)
    scene.clear_scene()

    progress("body", "creating body from MakeHuman macros", 0.05)
    base = scene.create_body(mpfb, spec)
    progress("rig", f"adding the {spec['rig']} rig", 0.12)
    rig = scene.add_rig(mpfb, base, spec["rig"])
    bone_names = [b.name for b in rig.data.bones]

    progress("weights", "correcting body skin weights", 0.16)
    fixes = rigfix.correct_body(base, rig)

    progress("proxies", "fitting eyes, brows, lashes, teeth, tongue, hair and clothes", 0.2)
    parts = {"eyes": scene.add_proxy(mpfb, base, "eyes", spec["eyes"]["mesh"])}
    for role in ("eyebrows", "eyelashes", "teeth", "tongue", "hair"):
        parts[role] = scene.add_proxy(mpfb, base, role, spec[role]["asset"])
    clothes = []
    height_estimate = rigfix.body_height(base)
    for item in spec["clothes"]:
        obj = scene.add_proxy(mpfb, base, "clothes", item["asset"])
        clothes.append((item, obj))
        if item["slot"] in ("outfit", "top"):
            fixes["clothes_" + item["slot"]] = rigfix.correct_clothes(obj, rig, height_estimate)
    outer = next((o for i, o in clothes if i["slot"] in ("outfit", "bottom")), None)
    for item, obj in clothes:
        if item["slot"] == "shoes" and outer is not None:
            fixes["tucked_shoe_vertices"] = scene.tuck_under(obj, outer)

    progress("face", "loading ARKit and viseme targets", 0.35)
    scene.load_face_targets(mpfb, base)
    scene.bake_macro_shapes(base)
    face_names = mpfb.ARKIT + mpfb.VISEMES
    morphs = {}
    for role in FACE_PROXIES:
        morphs[OBJECT_NAMES[role]] = scene.transfer_face_targets(mpfb, base, parts[role], face_names)
    if spec["eyes"]["mesh"] == "high-poly":
        scene.remove_eye_shell(parts["eyes"])
    progress("face", "face targets transferred to " + ", ".join(
        f"{k} ({len(v)})" for k, v in morphs.items()), 0.45)

    progress("regions", "computing skin regions (face, lips, palms, cheeks, ...)", 0.48)
    regions = skinmaps.compute_regions(base)

    progress("masks", "baking clothing masks and removing helper geometry", 0.5)
    scene.remove_helpers(mpfb, base)
    # Drop every shape key that is not a face target (the basis stays first).
    keys = base.data.shape_keys.key_blocks
    for key in list(keys)[1:]:
        if key.name not in face_names:
            base.shape_key_remove(key)
    morphs = {"Body": [k.name for k in base.data.shape_keys.key_blocks][1:], **morphs}

    progress("materials", "baking skin albedo, normal and roughness maps", 0.53)
    _, skin_report = materials.skin(base, slug, spec["skin"], limits, mpfb, KIT_ROOT, dump_dir=dump_maps)
    skinmaps.clear_regions(base)
    skin_report.update(regions)
    progress("materials", "building eye, mouth, hair and clothing materials", 0.62)
    materials.eyes(parts["eyes"], slug, mpfb, spec["eyes"], limits)
    materials.card(parts["eyebrows"], slug, "eyebrows", limits, darken=0.9, roughness=0.65)
    materials.card(parts["eyelashes"], slug, "eyelashes", limits, darken=0.55, roughness=0.6)
    # (role, albedo scale, roughness, specular, occlusion front, occlusion back)
    for role, brightness, rough, spec_level, front, back in (("teeth", 0.85, 0.32, 0.45, 0.85, 0.22),
                                                            ("tongue", 0.8, 0.5, 0.35, 0.36, 0.1)):
        materials.mouth_part(parts[role], slug, role, limits, brightness, rough, spec_level)
        materials.mouth_occlusion(parts[role], front, back)
    materials.hair(parts["hair"], slug, spec["hair"], limits)
    for item, obj in clothes:
        materials.clothing(obj, slug, item, limits)

    progress("weights", "limiting to four normalised influences per vertex", 0.66)
    meshes = [base] + list(parts.values()) + [obj for _, obj in clothes]
    for obj in meshes:
        matrix = weights.weight_matrix(obj, bone_names)
        weights.write_weights(obj, bone_names, weights.limit_and_normalize(matrix))

    # Stable, readable object names in the GLB.
    base.name = base.data.name = "Body"
    for role, obj in parts.items():
        obj.name = obj.data.name = OBJECT_NAMES[role]
    for item, obj in clothes:
        obj.name = obj.data.name = item["slot"].capitalize()
    rig.name = rig.data.name = "Armature"

    out_dir.mkdir(parents=True, exist_ok=True)
    glb = out_dir / f"{slug}.glb"
    progress("export", f"exporting {glb.name}", 0.72)
    objects = scene.descendants(rig)
    versions = {"blender": bpy.app.version_string, "mpfb": mpfb_version(package),
                "gltf_exporter": _exporter_version()}
    export.export_glb(glb, objects, rig)
    gltf = export.postprocess(glb, {"talking_avatar_kit": {"slug": slug, "license": "CC-BY-4.0",
                                                           "credit": CREDIT}},
                              copyright=f"{spec['name']} avatar, {CREDIT}, CC BY 4.0")

    height = None
    if blend_path:
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), compress=True)
    if want_preview:
        progress("preview", "rendering preview.png", 0.85)
        height = render.preview(bpy.context.scene, objects, out_dir / "preview.png")
    else:
        lo, hi = render.bounds(objects)
        height = hi.z - lo.z

    emit("result", slug=slug, glb=glb.name, bones=bone_names, morphs=morphs,
         materials=[m["name"] for m in gltf.get("materials", [])],
         meshes=[o.name for o in meshes], height_m=round(height, 4), versions=versions,
         weight_fixes=fixes, skin=skin_report, preview="preview.png" if want_preview else None)
    progress("blender", "build finished", 0.9)


def _exporter_version():
    try:
        import addon_utils
        for mod in addon_utils.modules():
            if mod.__name__ == "io_scene_gltf2":
                return ".".join(str(v) for v in addon_utils.module_bl_info(mod)["version"])
    except Exception:  # noqa: BLE001
        pass
    return None


def main():
    args = parse()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    build(spec, Path(args.out_dir), args.preview, args.blend, args.dump_maps)


main()
