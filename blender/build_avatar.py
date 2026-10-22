"""Build one avatar GLB from avatars/<slug>/spec.json with MPFB (run inside background Blender).

    blender -b --factory-startup --python blender/build_avatar.py -- \
        --spec avatars/rowan/spec.json --out-dir build/rebuild/rowan [--preview] [--blend work.blend]

The kit's Blender profile (BLENDER_USER_RESOURCES) must contain MPFB and the
MakeHuman packs the spec names; ``python -m tak setup`` installs them.
``python -m tak build`` runs this script, validates the result and writes
manifest.json.

Steps, in this order (each proxy is fitted to the real body shape):

1. body from the MakeHuman macros and skin, the game_engine rig, body weight fixes;
2. eyes, brows, lashes, teeth, tongue, hair and garments fitted; garment weights
   smoothed under the shoulders; garments layered (trousers under the top, shoes
   under the trouser legs);
3. ARKit and viseme targets loaded, macro shape keys baked into the basis, face
   targets copied onto the face parts through their MHCLO binding;
4. helper geometry removed with the garments' delete groups baked, then the body
   under garments without a delete list removed by ray casting (``cover``);
5. materials (``look``: the kit's or MPFB's; the kit eye treatment always), four
   normalised influences per vertex, export and GLB post-processing.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from tak_blender import emit, enable_mpfb, mpfb_version, progress, script_args  # noqa: E402
from tak_blender import cover, export, materials, render, rigfix, scene, skinmaps, weights  # noqa: E402

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


def credits_of(spec):
    """CC BY credit lines of community garments and hair, in outfit order, hair last."""
    lines = [item["credit"] for item in spec["clothes"] if item.get("credit")]
    if spec["hair"].get("credit"):
        lines.append(spec["hair"]["credit"])
    return lines


def kit_materials(spec, slug, base, parts, limits, mpfb, dump_maps):
    """The kit's own skin (baked maps), brows, lashes, teeth, tongue and hair."""
    _, skin_report = materials.skin(base, slug, spec["skin"], limits, mpfb, KIT_ROOT, dump_dir=dump_maps)
    skinmaps.clear_regions(base)
    materials.card(parts["eyebrows"], slug, "eyebrows", limits, darken=0.9, roughness=0.65)
    materials.card(parts["eyelashes"], slug, "eyelashes", limits, darken=0.55, roughness=0.6)
    # (role, albedo scale, roughness, specular, occlusion front, occlusion back)
    for role, brightness, rough, spec_level, front, back in (("teeth", 0.85, 0.32, 0.45, 0.85, 0.22),
                                                            ("tongue", 0.8, 0.5, 0.35, 0.36, 0.1)):
        materials.mouth_part(parts[role], slug, role, limits, brightness, rough, spec_level)
        materials.mouth_occlusion(parts[role], front, back)
    materials.hair(parts["hair"], slug, spec["hair"], limits)
    return skin_report


def mpfb_materials(spec, slug, base, parts, limits):
    """MPFB's own materials from the MakeHuman assets, named by role, textures capped."""
    materials.keep_mpfb(base, "skin", spec["skin"].get("roughness"))
    materials.limit_textures(base, limits["skin_max"])
    for role in ("eyebrows", "eyelashes", "teeth", "tongue", "hair"):
        cfg = spec[role]
        materials.keep_mpfb(parts[role], role, cfg.get("roughness"))
        if "recolor" in cfg or "base_color" in cfg:
            materials.recolor_texture(parts[role], slug, role, cfg.get("recolor"), cfg.get("base_color"))
        materials.limit_textures(parts[role], limits["default_max"])
    return {"look": "mpfb", "material": spec["skin"]["material"]}


def build(spec, out_dir, want_preview, blend_path, dump_maps=None):
    slug = spec["slug"]
    limits = spec["textures"]
    look = spec.get("look", "kit")
    weight_cfg = spec.get("weights", {})
    progress("blender", "enabling MPFB", 0.02)
    package = enable_mpfb()
    mpfb = scene.Mpfb(package)
    scene.clear_scene()

    progress("body", "creating body from MakeHuman macros", 0.05)
    base = scene.create_body(mpfb, spec)
    progress("rig", f"adding the {spec['rig']} rig", 0.12)
    rig = scene.add_rig(mpfb, base, spec["rig"])
    bone_names = [b.name for b in rig.data.bones]

    fixes = {}
    if weight_cfg.get("body", True):
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
        if item["slot"] in ("outfit", "top") and weight_cfg.get("garments", True):
            fixes["clothes_" + item["slot"]] = rigfix.correct_clothes(obj, rig, height_estimate)
    layering = {}
    if spec.get("layering", True):
        tucked = any(item.get("tucked") for item, _ in clothes)
        layering = scene.layer({item["slot"]: obj for item, obj in clothes}, tucked=tucked)

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

    regions = {}
    if look == "kit":
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
    progress("cover", "removing the body under garments without a delete list", 0.52)
    covered = cover.delete_covered(base, clothes)

    if look == "kit":
        progress("materials", "baking skin albedo, normal and roughness maps", 0.53)
        skin_report = kit_materials(spec, slug, base, parts, limits, mpfb, dump_maps)
        skin_report.update(regions)
    else:
        progress("materials", "keeping MPFB's materials for skin, face parts and hair", 0.53)
        skin_report = mpfb_materials(spec, slug, base, parts, limits)
    progress("materials", "eye treatment and clothing materials", 0.62)
    materials.eyes(parts["eyes"], slug, mpfb, spec["eyes"], limits)
    for item, obj in clothes:
        materials.clothing(obj, slug, item, limits)

    progress("weights", "limiting to four normalised influences per vertex", 0.66)
    meshes = [base] + list(parts.values()) + [obj for _, obj in clothes]
    for obj in meshes:
        matrix = weights.weight_matrix(obj, bone_names)
        weights.write_weights(obj, bone_names, weights.limit_and_normalize(matrix))

    # Stable, readable object names in the GLB (nodes from objects, meshes from data).
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
    credits = credits_of(spec)
    copyright_line = f"{spec['name']} avatar, {CREDIT}, CC BY 4.0"
    if credits:
        copyright_line += "; " + "; ".join(credits)
    gltf = export.postprocess(glb, {"talking_avatar_kit": {"slug": slug, "license": "CC-BY-4.0",
                                                           "credit": CREDIT}},
                              copyright=copyright_line)

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
         weight_fixes=fixes, layering=layering, cover=covered, look=look, credits=credits,
         body_vertices=len(base.data.vertices), skin=skin_report,
         preview="preview.png" if want_preview else None)
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
