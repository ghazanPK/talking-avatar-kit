using System.Collections.Generic;
using UnityEngine;

namespace TalkingAvatarKit.Editor
{
    /// <summary>
    /// Builds the Mecanim <see cref="HumanDescription"/> for a kit avatar.
    ///
    /// The avatars are bound in an A-pose. Mecanim treats the skeleton pose stored in the
    /// HumanDescription as the character's T-pose, so this class derives a T-pose from the
    /// sidecar's rest skeleton (what "Enforce T-Pose" does in the Avatar editor): arms,
    /// hands and fingers point straight out along the shoulder line, legs straight down.
    /// The mesh bind pose is untouched; only the avatar's reference pose changes.
    /// </summary>
    public static class HumanoidSetup
    {
        /// <summary>The MPFB game_engine bone for each Unity human bone (used when a sidecar has no map).</summary>
        public static readonly Dictionary<string, string> DefaultMap = BuildDefaultMap();

        static Dictionary<string, string> BuildDefaultMap()
        {
            var map = new Dictionary<string, string>
            {
                ["Hips"] = "pelvis", ["Spine"] = "spine_01", ["Chest"] = "spine_02", ["UpperChest"] = "spine_03",
                ["Neck"] = "neck_01", ["Head"] = "head",
            };
            foreach (var (side, s) in new[] { ("Left", "l"), ("Right", "r") })
            {
                map[side + "Shoulder"] = "clavicle_" + s;
                map[side + "UpperArm"] = "upperarm_" + s;
                map[side + "LowerArm"] = "lowerarm_" + s;
                map[side + "Hand"] = "hand_" + s;
                map[side + "UpperLeg"] = "thigh_" + s;
                map[side + "LowerLeg"] = "calf_" + s;
                map[side + "Foot"] = "foot_" + s;
                map[side + "Toes"] = "ball_" + s;
                foreach (var (finger, bone) in new[] { ("Thumb", "thumb"), ("Index", "index"), ("Middle", "middle"), ("Ring", "ring"), ("Little", "pinky") })
                {
                    map[$"{side} {finger} Proximal"] = $"{bone}_01_{s}";
                    map[$"{side} {finger} Intermediate"] = $"{bone}_02_{s}";
                    map[$"{side} {finger} Distal"] = $"{bone}_03_{s}";
                }
            }
            return map;
        }

        /// <summary>World-space direction each bone gets in the T-pose (Unity space: the avatar faces +Z, its left is -X).</summary>
        public static Dictionary<string, Vector3> TPoseDirections()
        {
            var d = new Dictionary<string, Vector3>();
            foreach (var (s, x) in new[] { ("l", Vector3.left), ("r", Vector3.right) })
            {
                d["upperarm_" + s] = x;
                d["lowerarm_" + s] = x;
                d["hand_" + s] = x;
                foreach (var finger in new[] { "index", "middle", "ring", "pinky" })
                    for (var j = 1; j <= 3; j++) d[$"{finger}_0{j}_{s}"] = x;
                d["thigh_" + s] = Vector3.down;
                d["calf_" + s] = Vector3.down;
            }
            return d;
        }

        public static HumanDescription Build(AvatarSidecar sidecar, string rootName, bool enforceTPose = true)
        {
            var map = sidecar.Humanoid.Count > 0 ? sidecar.Humanoid : DefaultMap;
            var bones = new HashSet<string>(sidecar.Bones);
            var human = new List<HumanBone>();
            foreach (var humanName in HumanTrait.BoneName)
            {
                if (!map.TryGetValue(humanName, out var bone) || !bones.Contains(bone)) continue;
                var hb = new HumanBone { humanName = humanName, boneName = bone };
                hb.limit.useDefaultValues = true;
                human.Add(hb);
            }
            var skeleton = enforceTPose ? TPoseSkeleton(sidecar, rootName) : RestSkeleton(sidecar, rootName);
            return new HumanDescription
            {
                human = human.ToArray(),
                skeleton = skeleton,
                upperArmTwist = 0.5f,
                lowerArmTwist = 0.5f,
                upperLegTwist = 0.5f,
                lowerLegTwist = 0.5f,
                armStretch = 0.05f,
                legStretch = 0.05f,
                feetSpacing = 0f,
                hasTranslationDoF = false,
            };
        }

        static string EntryName(AvatarSidecar sidecar, int index, string rootName) =>
            index == 0 && sidecar.Skeleton[0].Parent == null ? rootName : sidecar.Skeleton[index].Name;

        public static SkeletonBone[] RestSkeleton(AvatarSidecar sidecar, string rootName)
        {
            var result = new SkeletonBone[sidecar.Skeleton.Count];
            for (var i = 0; i < result.Length; i++)
            {
                var e = sidecar.Skeleton[i];
                result[i] = new SkeletonBone
                {
                    name = EntryName(sidecar, i, rootName), position = e.Position, rotation = e.Rotation, scale = e.Scale,
                };
            }
            return result;
        }

        /// <summary>Rest skeleton with limb rotations changed so the avatar stands in a T-pose.</summary>
        /// <summary>Bones aimed at a child joint instead of along their own axis (the hand points at the middle finger).</summary>
        public static readonly Dictionary<string, string> AimAt = new Dictionary<string, string>
        {
            ["hand_l"] = "middle_01_l", ["hand_r"] = "middle_01_r",
        };

        public static SkeletonBone[] TPoseSkeleton(AvatarSidecar sidecar, string rootName)
        {
            var entries = sidecar.Skeleton;
            var targets = TPoseDirections();
            var worldPos = new Dictionary<string, Vector3>();
            foreach (var e in entries) worldPos[e.Name] = e.WorldPosition;
            var restWorld = new Dictionary<string, Quaternion>();
            var poseWorld = new Dictionary<string, Quaternion>();
            var result = new SkeletonBone[entries.Count];
            for (var i = 0; i < entries.Count; i++)
            {
                var e = entries[i];
                var parentRest = e.Parent != null && restWorld.TryGetValue(e.Parent, out var pr) ? pr : Quaternion.identity;
                var parentPose = e.Parent != null && poseWorld.TryGetValue(e.Parent, out var pp) ? pp : Quaternion.identity;
                var rest = parentRest * e.Rotation;
                restWorld[e.Name] = rest;
                var local = e.Rotation;
                var pose = parentPose * local;
                Vector3? aim = AimAt.TryGetValue(e.Name, out var child) && worldPos.TryGetValue(child, out var cp)
                    ? cp : e.WorldTail;
                if (targets.TryGetValue(e.Name, out var target) && aim.HasValue)
                {
                    var restDir = aim.Value - e.WorldPosition;
                    if (restDir.sqrMagnitude > 1e-10f)
                    {
                        // The bone's direction in its own frame stays fixed; rotate the frame so it points at the target.
                        var dirLocal = Quaternion.Inverse(rest) * restDir.normalized;
                        var current = pose * dirLocal;
                        pose = Quaternion.FromToRotation(current, target) * pose;
                        local = Quaternion.Inverse(parentPose) * pose;
                    }
                }
                poseWorld[e.Name] = pose;
                result[i] = new SkeletonBone
                {
                    name = EntryName(sidecar, i, rootName), position = e.Position, rotation = Normalize(local), scale = e.Scale,
                };
            }
            return result;
        }

        static Quaternion Normalize(Quaternion q)
        {
            var m = Mathf.Sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
            return m > 0f ? new Quaternion(q.x / m, q.y / m, q.z / m, q.w / m) : Quaternion.identity;
        }
    }
}
