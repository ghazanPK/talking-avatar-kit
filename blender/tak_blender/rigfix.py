"""Bind-pose and skin-weight corrections for the MPFB game_engine rig.

``correct_body`` runs on the body right after the rig is added and before the
proxies are fitted, so clothes interpolate their weights from the corrected
body. ``correct_clothes`` then evens out garment weights under the shoulders
and around the elbows, where a sleeve vertex can be bound to torso vertices
and tear into thin fins when the arm is raised.

MPFB's game_engine weights hinge some joints too sharply for real-time use:
the thumb base (thenar) folds at one edge loop in opposition, knuckles pinch
in a fist, and wrists, elbows and shoulders crease at a single loop. Each fix
spreads the hand-off between the bones of a joint over a wider band with
Laplacian smoothing restricted to those bones, inside a sphere around the
joint. Weights of other bones are left untouched; every vertex ends with at
most four normalised influences.
"""
import numpy as np

from . import weights as W

FINGERS = ("index", "middle", "ring", "pinky")

# (name, bones whose weights are blended, joint bone whose head is the centre,
#  radius as a fraction of body height, smoothing iterations, factor)
BODY_FIXES = (
    ("thumb_base", ("hand", "thumb_01", "thumb_02"), "thumb_01", 0.030, 10, 0.5),
    ("thumb_middle", ("thumb_01", "thumb_02", "thumb_03"), "thumb_02", 0.016, 4, 0.5),
    ("wrist", ("lowerarm", "hand"), "hand", 0.030, 6, 0.5),
    ("elbow", ("upperarm", "lowerarm"), "lowerarm", 0.045, 6, 0.5),
    ("shoulder", ("clavicle", "upperarm", "spine_03"), "upperarm", 0.060, 8, 0.5),
)
KNUCKLE_FIX = (0.016, 4, 0.45)  # radius fraction, iterations, factor
CLOTHES_FIXES = (
    ("shoulder", ("clavicle", "upperarm", "spine_03", "spine_02"), "upperarm", 0.085, 12, 0.6),
    ("elbow", ("upperarm", "lowerarm"), "lowerarm", 0.05, 6, 0.5),
)


def _heads(rig):
    mw = rig.matrix_world
    return {b.name: np.array(mw @ b.head_local) for b in rig.data.bones}


def _positions(obj):
    co = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mw = np.array(obj.matrix_world)
    return co @ mw[:3, :3].T + mw[:3, 3]


class _Smoother:
    def __init__(self, obj, rig, height):
        self.obj = obj
        self.bones = [b.name for b in rig.data.bones]
        self.col = {name: i for i, name in enumerate(self.bones)}
        self.weights = W.weight_matrix(obj, self.bones)
        self.before = self.weights.copy()
        self.adjacency = W.neighbours(obj.data)
        self.pos = _positions(obj)
        self.heads = _heads(rig)
        self.height = height

    def apply(self, cols, centre_bone, radius, iterations, factor, below=False):
        cols = [self.col[c] for c in cols if c in self.col]
        involved = self.weights[:, cols].sum(axis=1) > 0.02
        centre = self.heads[centre_bone]
        near = np.linalg.norm(self.pos - centre, axis=1) < radius * self.height
        mask = involved & near
        if below:
            mask &= self.pos[:, 2] < centre[2]
        if mask.any():
            self.weights = W.smooth(self.weights, self.adjacency, mask, iterations=iterations,
                                    factor=factor, columns=cols)
        return int(mask.sum())

    def joint_fixes(self, fixes, report, prefix="", below=()):
        for side in ("l", "r"):
            for name, group, joint, radius, iterations, factor in fixes:
                cols = [b if b.startswith("spine") else f"{b}_{side}" for b in group]
                report[f"{prefix}{name}_{side}"] = self.apply(cols, f"{joint}_{side}", radius,
                                                              iterations, factor, below=name in below)

    def finish(self, report, key="vertices_changed"):
        self.weights = W.limit_and_normalize(self.weights, limit=4)
        changed = np.abs(self.weights - self.before).max(axis=1) > 1e-3
        W.write_weights(self.obj, self.bones, self.weights)
        report[key] = int(changed.sum())
        return report


def body_height(obj):
    pos = _positions(obj)
    return float(pos[:, 2].max() - pos[:, 2].min())


def correct_body(base, rig):
    report = {}
    smoother = _Smoother(base, rig, body_height(base))
    smoother.joint_fixes(BODY_FIXES, report)
    radius, iterations, factor = KNUCKLE_FIX
    for side in ("l", "r"):
        report[f"knuckles_{side}"] = sum(
            smoother.apply((f"hand_{side}", f"{finger}_01_{side}", f"{finger}_02_{side}"),
                           f"{finger}_01_{side}", radius, iterations, factor)
            for finger in FINGERS)
    return smoother.finish(report)


def correct_clothes(obj, rig, height):
    report = {}
    smoother = _Smoother(obj, rig, height)
    # Only the underarm side of the shoulder: the collar and shoulder top must keep
    # following the body they cover.
    smoother.joint_fixes(CLOTHES_FIXES, report, below=("shoulder",))
    return smoother.finish(report)
