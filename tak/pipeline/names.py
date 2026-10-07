"""Canonical names shared by the build, the validator and the manifest."""

# ARKit face blendshapes (52), in Apple's documented order.
ARKIT = (
    "eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft",
    "eyeSquintLeft", "eyeWideLeft", "eyeBlinkRight", "eyeLookDownRight", "eyeLookInRight",
    "eyeLookOutRight", "eyeLookUpRight", "eyeSquintRight", "eyeWideRight", "jawForward",
    "jawLeft", "jawRight", "jawOpen", "mouthClose", "mouthFunnel", "mouthPucker", "mouthLeft",
    "mouthRight", "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthDimpleLeft", "mouthDimpleRight", "mouthStretchLeft", "mouthStretchRight",
    "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper", "mouthPressLeft",
    "mouthPressRight", "mouthLowerDownLeft", "mouthLowerDownRight", "mouthUpperUpLeft",
    "mouthUpperUpRight", "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft",
    "browOuterUpRight", "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "noseSneerLeft",
    "noseSneerRight", "tongueOut",
)

# Meta/Oculus viseme names (15); the kit keeps these names for its lip-sync tables.
VISEMES = (
    "viseme_sil", "viseme_PP", "viseme_FF", "viseme_TH", "viseme_DD", "viseme_kk", "viseme_CH",
    "viseme_SS", "viseme_nn", "viseme_RR", "viseme_aa", "viseme_E", "viseme_I", "viseme_O",
    "viseme_U",
)

FACE = ARKIT + VISEMES

# MPFB game_engine rig: 53 bones (Unreal-style names).
GAME_ENGINE_BONES = (
    "Root", "pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head",
    *(f"{b}_{s}" for s in ("l", "r") for b in (
        "clavicle", "upperarm", "lowerarm", "hand",
        "thumb_01", "thumb_02", "thumb_03", "index_01", "index_02", "index_03",
        "middle_01", "middle_02", "middle_03", "ring_01", "ring_02", "ring_03",
        "pinky_01", "pinky_02", "pinky_03",
        "thigh", "calf", "foot", "ball")),
)

# Material slots every avatar has; clothing adds its spec slots (outfit, shoes, ...).
BASE_MATERIALS = ("skin", "eyes", "eyebrows", "eyelashes", "teeth", "tongue", "hair")
ALPHA_MODES = {"eyebrows": "BLEND", "eyelashes": "BLEND", "hair": "MASK"}

# Meshes that carry face targets (subset per mesh; the body carries all 67).
FACE_MESHES = ("Body", "Eyes", "Eyebrows", "Eyelashes", "Teeth", "Tongue")
