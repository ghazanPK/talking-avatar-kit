namespace TalkingAvatarKit
{
    /// <summary>The 15 Meta/Oculus visemes, in the order of <see cref="FaceShapes.Visemes"/>.</summary>
    public enum Viseme
    {
        sil, PP, FF, TH, DD, kk, CH, SS, nn, RR, aa, E, I, O, U
    }

    /// <summary>Blendshape names every talking-avatar-kit avatar carries.</summary>
    public static class FaceShapes
    {
        /// <summary>The 52 ARKit face blendshapes in Apple's documented order.</summary>
        public static readonly string[] Arkit =
        {
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
        };

        /// <summary>The 15 viseme blendshapes (viseme_sil ... viseme_U), indexed by <see cref="Viseme"/>.</summary>
        public static readonly string[] Visemes =
        {
            "viseme_sil", "viseme_PP", "viseme_FF", "viseme_TH", "viseme_DD", "viseme_kk", "viseme_CH",
            "viseme_SS", "viseme_nn", "viseme_RR", "viseme_aa", "viseme_E", "viseme_I", "viseme_O",
            "viseme_U",
        };

        public static string Name(Viseme viseme) => Visemes[(int)viseme];
    }
}
