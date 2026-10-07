"""Re-import a built GLB in background Blender and check it (run inside Blender).

    blender -b --factory-startup --python blender/validate.py -- --glb avatars/rowan/rowan.glb \
        [--expect-bones 53] [--height 1.85 2.05]

Prints one ``TAK {"event": "validate", "checks": [...]}`` line; the exit code
stays 0 so the caller decides (``python -m tak validate`` turns failures into
a non-zero exit).
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
from mathutils import Quaternion, Vector  # noqa: E402

from tak_blender import emit, script_args  # noqa: E402

FACE_COUNT = 67


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", required=True)
    parser.add_argument("--expect-bones", type=int, default=53)
    parser.add_argument("--height", type=float, nargs=2, default=(0.5, 3.0))
    args = parser.parse_args(script_args())
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    try:
        bpy.ops.import_scene.gltf(filepath=args.glb)
    except Exception as exc:  # noqa: BLE001
        add("import", False, str(exc))
        emit("validate", checks=checks)
        return
    rigs = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.parent in rigs]
    add("import", len(rigs) == 1 and bool(meshes), f"{len(rigs)} armature, {len(meshes)} skinned meshes")
    if len(rigs) != 1:
        emit("validate", checks=checks)
        return
    rig = rigs[0]
    add("bones", len(rig.data.bones) == args.expect_bones, f"{len(rig.data.bones)} bones")

    body = next((m for m in meshes if m.name == "Body"), None)
    keys = body.data.shape_keys.key_blocks[1:] if body is not None and body.data.shape_keys else []
    add("body_shape_keys", len(keys) == FACE_COUNT, f"{len(keys)} shape keys on Body")

    missing_groups = []
    for obj in meshes:
        bone_groups = {g.index for g in obj.vertex_groups if g.name in rig.data.bones}
        orphans = sum(1 for v in obj.data.vertices
                      if not any(g.group in bone_groups and g.weight > 0 for g in v.groups))
        if orphans:
            missing_groups.append(f"{obj.name}:{orphans}")
    add("weighted_vertices", not missing_groups,
        "every vertex has a bone influence" if not missing_groups else ", ".join(missing_groups))

    materials = sorted({s.material.name for o in meshes for s in o.material_slots if s.material})
    add("materials", len(materials) >= 7, ", ".join(materials))

    def extent():
        deps = bpy.context.evaluated_depsgraph_get()
        lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
        for obj in meshes:
            ev = obj.evaluated_get(deps)
            mesh = ev.to_mesh()
            for v in mesh.vertices:
                p = obj.matrix_world @ v.co
                lo = Vector(map(min, lo, p))
                hi = Vector(map(max, hi, p))
            ev.to_mesh_clear()
        return lo, hi

    lo, hi = extent()
    height = hi.z - lo.z
    add("height", args.height[0] <= height <= args.height[1],
        f"{height:.3f} m (expected {args.height[0]}-{args.height[1]} m)")

    # Raise both arms; a vertex left behind (no or wrong influence) would stretch the bounds.
    for side in ("l", "r"):
        pb = rig.pose.bones.get(f"upperarm_{side}")
        if pb:
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = Quaternion((1, 0, 0), math.radians(-60))
    bpy.context.view_layer.update()
    plo, phi = extent()
    growth = max((phi - plo)[i] - (hi - lo)[i] for i in range(3))
    add("posed_bounds", growth < 0.6 * height, f"bounds grow by {growth:.3f} m with arms rotated")
    emit("validate", checks=checks, height_m=round(height, 4), bones=len(rig.data.bones),
         materials=materials)


main()
