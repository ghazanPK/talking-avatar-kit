"""Render pose and face check images of a built GLB (run inside background Blender).

    blender -b --factory-startup --python blender/pose_check.py -- \
        --glb avatars/rowan/rowan.glb --out-dir build/pose-check/rowan [--only fist,face_neutral]

Poses bend the rig to extremes that expose skin-weight problems (arms raised,
elbow at 120 degrees, fist, open hand, pointing, thumb opposition, wrist bends)
and face shots exercise the morph targets. Rotation axes are computed from
the rest skeleton, so the script does not depend on bone roll conventions.
"""
import argparse
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
from mathutils import Matrix, Quaternion, Vector  # noqa: E402

from tak_blender import emit, render, script_args  # noqa: E402

FINGERS = ("index", "middle", "ring", "pinky")


def import_glb(path):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for obj in list(bpy.data.objects):
        # The importer adds a bone display shape that is not part of the avatar.
        if obj.type == "MESH" and obj.parent is None:
            bpy.data.objects.remove(obj, do_unlink=True)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    return rig, meshes


class Poser:
    """Applies rotations given in armature space (axis, degrees) to pose bones."""

    def __init__(self, rig):
        self.rig = rig
        self.rest = {b.name: b.matrix_local.copy() for b in rig.data.bones}

    def reset(self):
        for pb in self.rig.pose.bones:
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = Quaternion()
            pb.location = (0, 0, 0)
        bpy.context.view_layer.update()

    def head(self, name):
        return self.rest[name].to_translation()

    def tail_dir(self, name):
        return (self.rest[name].to_3x3() @ Vector((0, 1, 0))).normalized()

    def rotate(self, name, axis, degrees):
        """Rotate bone ``name`` about an armature-space axis through its head (local to parent motion)."""
        rest = self.rest[name].to_3x3()
        q_arm = Quaternion(Vector(axis).normalized(), math.radians(degrees))
        local = (rest.inverted() @ q_arm.to_matrix() @ rest).to_quaternion()
        pb = self.rig.pose.bones[name]
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = local @ pb.rotation_quaternion

    def aim(self, name, direction):
        """Rotate a bone (from rest) so it points along an armature-space direction."""
        current = self.tail_dir(name)
        q = current.rotation_difference(Vector(direction).normalized())
        axis, angle = q.to_axis_angle()
        self.rotate(name, axis, math.degrees(angle))

    def side_sign(self, side):
        return 1.0 if self.head(f"upperarm_{side}").x > 0 else -1.0

    def palm_normal(self, side):
        """Unit vector pointing out of the palm (the side fingers curl toward)."""
        across = self.head(f"index_01_{side}") - self.head(f"pinky_01_{side}")
        along = self.tail_dir(f"middle_01_{side}")
        normal = across.cross(along).normalized()
        return normal if side == "r" else -normal

    def curl_axis(self, side, bone):
        # Fingers bend toward the palm: rotate about (direction x palm normal).
        return self.tail_dir(bone).cross(self.palm_normal(side)).normalized()


def pose_arms_up(p, side):
    s = p.side_sign(side)
    p.aim(f"upperarm_{side}", (s * 0.45, 0.0, 1.0))  # raised above the shoulder
    p.rotate(f"clavicle_{side}", (0, 1, 0), -s * 15)


def pose_arms_forward(p, side):
    s = p.side_sign(side)
    p.aim(f"upperarm_{side}", (s * 0.12, -1.0, 0.05))  # reaching forward


def pose_elbow(p, side, degrees=120):
    axis = p.tail_dir(f"upperarm_{side}").cross(p.tail_dir(f"lowerarm_{side}"))
    if axis.length < 1e-3:
        axis = Vector((1, 0, 0))
    p.rotate(f"lowerarm_{side}", axis, degrees - math.degrees(p.tail_dir(f"upperarm_{side}").angle(p.tail_dir(f"lowerarm_{side}"))))


def pose_wrist(p, side, degrees):
    p.rotate(f"hand_{side}", p.curl_axis(side, f"hand_{side}"), degrees)


def pose_fist(p, side):
    for finger in FINGERS:
        for joint, angle in ((1, 70), (2, 95), (3, 70)):
            bone = f"{finger}_0{joint}_{side}"
            p.rotate(bone, p.curl_axis(side, bone), angle)
    pose_thumb_opposition(p, side, amount=1.0, target="middle", lift=0.05)


def pose_open(p, side):
    spread = {"index": 10, "middle": 0, "ring": -9, "pinky": -18}
    for finger in FINGERS:
        bone = f"{finger}_01_{side}"
        p.rotate(bone, p.palm_normal(side), spread[finger] * p.side_sign(side))
        p.rotate(bone, p.curl_axis(side, bone), -12)
    p.rotate(f"thumb_01_{side}", p.palm_normal(side), 25 * p.side_sign(side))


def pose_point(p, side):
    for finger in ("middle", "ring", "pinky"):
        for joint, angle in ((1, 80), (2, 95), (3, 65)):
            bone = f"{finger}_0{joint}_{side}"
            p.rotate(bone, p.curl_axis(side, bone), angle)
    pose_thumb_opposition(p, side, amount=0.9, target="middle", lift=0.04)


def pose_thumb_opposition(p, side, amount=1.0, target="pinky", lift=0.035):
    """Swing the thumb across the palm toward the base of the ring/pinky finger.

    thumb_01 (the metacarpal) is aimed at a point in front of the palm, rolled
    so the pad faces the fingers, and the two distal joints flex toward it.
    """
    palm = p.palm_normal(side)
    base = p.head(f"thumb_01_{side}")
    goal = p.head(f"{target}_01_{side}") + palm * lift
    rest_dir = p.tail_dir(f"thumb_01_{side}")
    goal_dir = (goal - base).normalized()
    # The metacarpal swings about half way; the distal joints do the rest.
    direction = rest_dir.slerp(goal_dir, 0.55 * amount)
    p.aim(f"thumb_01_{side}", direction)
    # Pronate the thumb about its own axis so the pad turns toward the fingers.
    p.rotate(f"thumb_01_{side}", direction, -30 * amount * p.side_sign(side))
    toward = (p.head(f"{target}_01_{side}") - base).normalized()
    for joint, angle in ((2, 40), (3, 50)):
        bone = f"thumb_0{joint}_{side}"
        axis = p.tail_dir(bone).cross(toward + palm)
        p.rotate(bone, axis, angle * amount)


POSES = {
    "rest": [],
    "arms_up": [lambda p: pose_arms_up(p, "l"), lambda p: pose_arms_up(p, "r")],
    "arms_forward": [lambda p: pose_arms_forward(p, "l"), lambda p: pose_arms_forward(p, "r")],
    "elbow_120": [lambda p: pose_elbow(p, "l"), lambda p: pose_elbow(p, "r")],
    "wrist_flex": [lambda p: pose_wrist(p, "l", 70), lambda p: pose_wrist(p, "r", 70)],
    "wrist_extend": [lambda p: pose_wrist(p, "l", -60), lambda p: pose_wrist(p, "r", -60)],
    "fist": [lambda p: pose_fist(p, "l"), lambda p: pose_fist(p, "r")],
    "open_hand": [lambda p: pose_open(p, "l"), lambda p: pose_open(p, "r")],
    "point": [lambda p: pose_point(p, "l"), lambda p: pose_point(p, "r")],
    "thumb_opposition": [lambda p: pose_thumb_opposition(p, "l"), lambda p: pose_thumb_opposition(p, "r")],
}

# Pose -> cameras ("view", subject). Subjects: body, shoulder_l, elbow_l, hand_l (palm/back), face.
SHOTS = {
    "rest": [("front", "body"), ("front", "hand_l"), ("palm", "hand_l")],
    "arms_up": [("front", "body"), ("front", "shoulder_l"), ("back", "shoulder_l")],
    "arms_forward": [("side", "shoulder_l"), ("front", "body")],
    "elbow_120": [("front", "elbow_l"), ("side", "elbow_l")],
    "wrist_flex": [("front", "hand_l"), ("side", "hand_l")],
    "wrist_extend": [("front", "hand_l")],
    "fist": [("front", "hand_l"), ("palm", "hand_l"), ("back", "hand_l")],
    "open_hand": [("palm", "hand_l"), ("back", "hand_l")],
    "point": [("front", "hand_l"), ("palm", "hand_l")],
    "thumb_opposition": [("palm", "hand_l"), ("front", "hand_l")],
}

FACE_SHOTS = {
    "face_neutral": {},
    "face_jaw_open": {"jawOpen": 1.0},
    "face_viseme_aa": {"viseme_aa": 1.0},
    "face_blink": {"eyeBlinkLeft": 1.0, "eyeBlinkRight": 1.0},
    "face_smile": {"mouthSmileLeft": 1.0, "mouthSmileRight": 1.0, "cheekSquintLeft": 0.5, "cheekSquintRight": 0.5},
    "face_look_left": {"eyeLookOutLeft": 1.0, "eyeLookInRight": 1.0},
    "face_brows_up": {"browInnerUp": 1.0, "browOuterUpLeft": 1.0, "browOuterUpRight": 1.0, "eyeWideLeft": 0.6, "eyeWideRight": 0.6},
    "face_back": {},
    "face_side": {},
    "closeup_eyes": {},
    "closeup_mouth": {"jawOpen": 0.55, "mouthFunnel": 0.2},
}


def set_morphs(meshes, values):
    for obj in meshes:
        keys = obj.data.shape_keys
        if not keys:
            continue
        for key in keys.key_blocks[1:]:
            key.value = values.get(key.name, 0.0)


def bone_world(rig, name, tail=False):
    pb = rig.pose.bones[name]
    return rig.matrix_world @ (pb.tail if tail else pb.head)


def shot_camera(scene, rig, p, view, subject, height):
    if subject == "body":
        target = Vector((0, 0, height * 0.55))
        dist = height * 2.4
    elif subject == "face":
        target = (bone_world(rig, "head") + bone_world(rig, "head", True)) / 2 - Vector((0, 0, 0.06))
        dist = 0.75
    elif subject in ("eyes", "mouth"):
        head = (bone_world(rig, "head") + bone_world(rig, "head", True)) / 2
        target = head + Vector((0, -0.08, -0.012 if subject == "eyes" else -0.11))
        dist = 0.3
    elif subject.startswith("shoulder"):
        target = bone_world(rig, "upperarm_l")
        dist = 0.9
    elif subject.startswith("elbow"):
        target = bone_world(rig, "lowerarm_l")
        dist = 0.7
    else:
        target = (bone_world(rig, "hand_l") + bone_world(rig, "middle_02_l")) / 2
        dist = 0.45
    if view == "front":
        offset = Vector((0.15, -1, 0.05))
    elif view == "back":
        offset = Vector((0.1, 1, 0.1))
    elif view == "side":
        offset = Vector((1, -0.15, 0.05))
    else:  # palm: look at the palm of the left hand
        rest_palm = p.palm_normal("l")
        hand = rig.pose.bones["hand_l"]
        rot = (hand.matrix @ p.rest["hand_l"].inverted()).to_3x3()
        palm = (rig.matrix_world.to_3x3() @ (rot @ rest_palm)).normalized()
        # Lean out to the character's left so the camera never ends up inside the torso.
        offset = palm + Vector((1.3 * p.side_sign("l"), -0.4, 0.0))
    cam_loc = target + offset.normalized() * dist
    for obj in [o for o in scene.objects if o.type == "CAMERA"]:
        bpy.data.objects.remove(obj, do_unlink=True)
    lens = 50 if subject == "body" else 60
    return render.camera(scene, cam_loc, target, lens=lens)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--only", default="", help="comma-separated pose or face shot names")
    parser.add_argument("--size", type=int, default=640)
    args = parser.parse_args(script_args())
    only = {s for s in args.only.split(",") if s}
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rig, meshes = import_glb(Path(args.glb))
    scene = bpy.context.scene
    p = Poser(rig)
    lo, hi = render.bounds(meshes)
    height = hi.z - lo.z
    render.setup_lights(scene, scale=max(height / 1.8, 0.5), center=(0, 0, height * 0.7))
    render.setup_render(scene, args.size, args.size, samples=24)
    written = []

    for name, ops in POSES.items():
        if only and name not in only:
            continue
        p.reset()
        set_morphs(meshes, {})
        for op in ops:
            op(p)
        bpy.context.view_layer.update()
        for view, subject in SHOTS[name]:
            shot_camera(scene, rig, p, view, subject, height)
            path = out / f"{name}__{subject}_{view}.png"
            render.render_to(scene, path)
            written.append(path.name)

    p.reset()
    bpy.context.view_layer.update()
    for name, values in FACE_SHOTS.items():
        if only and name not in only:
            continue
        set_morphs(meshes, values)
        bpy.context.view_layer.update()
        subject = name.split("_", 1)[1] if name.startswith("closeup_") else "face"
        view = {"face_back": "back", "face_side": "side"}.get(name, "front")
        shot_camera(scene, rig, p, view, subject, height)
        path = out / f"{name}.png"
        render.render_to(scene, path)
        written.append(path.name)
    emit("pose_check", images=written)


main()
