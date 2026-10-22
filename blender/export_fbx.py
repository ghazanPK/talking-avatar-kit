"""Convert a shipped avatar GLB to a Unity-ready FBX (run inside Blender).

    blender -b --factory-startup --python blender/export_fbx.py -- \
        --glb avatars/rowan/rowan.glb --fbx build/export/rowan/rowan.fbx \
        --plan plan.json --info info.json

``--plan`` is written by ``tak.pipeline.export``: the material plan (texture
files already extracted from the GLB into the FBX folder's ``textures/``) and
the Unity metallic-smoothness maps to derive. ``--info`` receives what the
sidecar needs (Unity-space skeleton, meshes and blendshapes, bounds).

``--verify FBX`` instead re-imports an exported FBX with Blender's importer
and reports bones, shape keys, materials, size and orientation.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from tak_blender import emit, script_args  # noqa: E402
from tak_blender import fbx  # noqa: E402


def export(args):
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    out_fbx = Path(args.fbx)
    textures_dir = out_fbx.parent / plan.get("textures_subdir", "textures")
    fbx.clear_scene()
    emit("progress", stage="import", message=f"importing {Path(args.glb).name}", progress=0.1)
    bpy.ops.import_scene.gltf(filepath=args.glb)
    rig, meshes = fbx.find_rig()
    fbx.remove_extras(rig, meshes)
    rig.data.pose_position = "REST"
    for obj in meshes:
        if obj.data.shape_keys:
            for key in obj.data.shape_keys.key_blocks:
                key.value = 0.0

    emit("progress", stage="materials", message="rebuilding materials for FBX", progress=0.3)
    derived = {}
    materials = plan.get("materials", {})
    for mat in bpy.data.materials:
        if mat.users and mat.name in materials:
            fbx.rebuild_material(mat, materials[mat.name], textures_dir)
    for name, spec in materials.items():
        ms = spec.get("unity_map")
        if ms:
            derived[name] = fbx.write_unity_map(
                textures_dir / ms["source"], textures_dir / ms["file"],
                spec.get("metallic", 0.0), spec.get("roughness", 1.0),
                spec.get("specular_f0") if ms["kind"] == "specular_smoothness" else None)

    emit("progress", stage="export", message=f"writing {out_fbx.name}", progress=0.6)
    out_fbx.parent.mkdir(parents=True, exist_ok=True)
    fbx.y_up_data(rig, meshes)
    settings = dict(fbx.FBX_SETTINGS)
    props = bpy.ops.export_scene.fbx.get_rna_type().properties.keys()
    fbx.relative_texture_paths_only()
    bpy.ops.export_scene.fbx(filepath=str(out_fbx), **{k: v for k, v in settings.items() if k in props})

    lo, hi = fbx.world_bounds(meshes)
    info = {
        "armature": rig.name,
        "bones": [b.name for b in rig.data.bones],
        "skeleton": fbx.unity_skeleton(rig, meshes, out_fbx.stem),
        "meshes": [fbx.mesh_info(o) for o in meshes],
        "bounds_unity": {"min": fbx._vec(fbx.TO_UNITY @ lo), "max": fbx._vec(fbx.TO_UNITY @ hi)},
        "height_m": round(hi.z - lo.z, 4),
        "derived_textures": derived,
        "fbx_settings": {k: (sorted(v) if isinstance(v, set) else v) for k, v in settings.items()},
        "blender": bpy.app.version_string,
        "fbx_exporter": fbx.fbx_exporter_version(),
    }
    Path(args.info).write_text(json.dumps(info, indent=1), encoding="utf-8")
    emit("export", fbx=str(out_fbx), bones=len(info["bones"]), meshes=len(meshes))


def verify(args):
    fbx.clear_scene()
    bpy.ops.import_scene.fbx(filepath=args.verify)
    rig, meshes = fbx.find_rig()
    lo, hi = fbx.world_bounds(meshes)
    bones = rig.data.bones

    def head(name):
        b = bones.get(name)
        return (rig.matrix_world @ b.head_local) if b else None

    foot, ball = head("foot_l"), head("ball_l")
    hand_l, hand_r = head("hand_l"), head("hand_r")
    used = {n.image for m in bpy.data.materials if m.use_nodes
            for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image}
    images = sorted(Path(bpy.path.abspath(i.filepath)).name for i in used)
    missing = sum(1 for i in used if not (i.packed_file or Path(bpy.path.abspath(i.filepath)).is_file()))
    report = {
        "armature": rig.name,
        "armature_matrix": [list(map(lambda v: round(v, 5), row)) for row in rig.matrix_world],
        "bones": [b.name for b in bones],
        "leaf_bones": [b.name for b in bones if b.name.endswith("_end")],
        "meshes": [fbx.mesh_info(o) for o in meshes],
        "height_m": round(hi.z - lo.z, 4),
        "min_z": round(lo.z, 4),
        # Blender: character faces -Y; toes ahead of the ankle, left hand on +X.
        "faces_minus_y": bool(foot and ball and ball.y < foot.y),
        "left_on_plus_x": bool(hand_l and hand_r and hand_l.x > hand_r.x),
        "materials": sorted(m.name for m in bpy.data.materials if m.users),
        "images": images,
        "images_missing": missing,
        "object_scales": {o.name: [round(v, 4) for v in o.matrix_world.to_scale()] for o in [rig, *meshes]},
    }
    Path(args.info).write_text(json.dumps(report, indent=1), encoding="utf-8")
    emit("verify", ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb")
    parser.add_argument("--fbx")
    parser.add_argument("--plan")
    parser.add_argument("--info", required=True)
    parser.add_argument("--verify", help="re-import this FBX and report instead of exporting")
    args = parser.parse_args(script_args())
    if args.verify:
        verify(args)
    else:
        if not (args.glb and args.fbx and args.plan):
            parser.error("--glb, --fbx and --plan are required for an export")
        export(args)


main()
