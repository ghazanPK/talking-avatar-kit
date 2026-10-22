using System.Collections.Generic;
using UnityEngine;

namespace TalkingAvatarKit
{
    /// <summary>
    /// Drives a blendshape by name on every skinned mesh of the avatar that has it
    /// (a viseme moves the body, teeth and tongue together; a blink moves the body and lashes).
    /// Weights are 0..1 here and scaled to each blendshape's full weight (100 for FBX imports).
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Talking Avatar Kit/Avatar Blend Shapes")]
    public sealed class AvatarBlendShapes : MonoBehaviour
    {
        /// <summary>One blendshape on one renderer.</summary>
        public readonly struct Target
        {
            public readonly SkinnedMeshRenderer Renderer;
            public readonly int Index;
            public readonly float FullWeight;

            public Target(SkinnedMeshRenderer renderer, int index, float fullWeight)
            {
                Renderer = renderer;
                Index = index;
                FullWeight = fullWeight;
            }
        }

        static readonly Target[] None = new Target[0];
        readonly Dictionary<string, Target[]> _targets = new Dictionary<string, Target[]>();
        int[][] _visemeCache;

        void Awake() => Rebuild();

        /// <summary>Rescan the child renderers (call after swapping meshes or clothes).</summary>
        public void Rebuild()
        {
            var lists = new Dictionary<string, List<Target>>();
            foreach (var renderer in GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                var mesh = renderer.sharedMesh;
                if (mesh == null) continue;
                for (var i = 0; i < mesh.blendShapeCount; i++)
                {
                    var name = mesh.GetBlendShapeName(i);
                    var frames = mesh.GetBlendShapeFrameCount(i);
                    var full = frames > 0 ? mesh.GetBlendShapeFrameWeight(i, frames - 1) : 100f;
                    if (!lists.TryGetValue(name, out var list)) lists[name] = list = new List<Target>();
                    list.Add(new Target(renderer, i, full));
                }
            }
            _targets.Clear();
            foreach (var pair in lists) _targets[pair.Key] = pair.Value.ToArray();
            _visemeCache = null;
        }

        void EnsureBuilt()
        {
            if (_targets.Count == 0) Rebuild();
        }

        /// <summary>All blendshape names found on the avatar.</summary>
        public IEnumerable<string> Names
        {
            get { EnsureBuilt(); return _targets.Keys; }
        }

        public bool Has(string blendShape)
        {
            EnsureBuilt();
            return _targets.ContainsKey(blendShape);
        }

        /// <summary>Every renderer/index pair that carries this blendshape (empty if none).</summary>
        public IReadOnlyList<Target> Find(string blendShape)
        {
            EnsureBuilt();
            return _targets.TryGetValue(blendShape, out var t) ? t : None;
        }

        /// <summary>Blendshape index on one renderer, or -1.</summary>
        public static int IndexOf(SkinnedMeshRenderer renderer, string blendShape)
        {
            return renderer != null && renderer.sharedMesh != null
                ? renderer.sharedMesh.GetBlendShapeIndex(blendShape)
                : -1;
        }

        /// <summary>Set a blendshape (0..1) on every mesh that has it. Returns false if no mesh has it.</summary>
        public bool SetWeight(string blendShape, float weight)
        {
            EnsureBuilt();
            if (!_targets.TryGetValue(blendShape, out var targets)) return false;
            foreach (var t in targets)
                if (t.Renderer != null) t.Renderer.SetBlendShapeWeight(t.Index, weight * t.FullWeight);
            return true;
        }

        /// <summary>Current weight (0..1) of a blendshape, read from the first mesh that has it.</summary>
        public float GetWeight(string blendShape)
        {
            EnsureBuilt();
            if (!_targets.TryGetValue(blendShape, out var targets) || targets.Length == 0) return 0f;
            var t = targets[0];
            return t.Renderer != null && t.FullWeight != 0f ? t.Renderer.GetBlendShapeWeight(t.Index) / t.FullWeight : 0f;
        }

        public bool SetViseme(Viseme viseme, float weight) => SetWeight(FaceShapes.Name(viseme), weight);

        /// <summary>Set all 15 visemes at once (weights indexed by <see cref="Viseme"/>).</summary>
        public void SetVisemes(IReadOnlyList<float> weights)
        {
            EnsureBuilt();
            var count = Mathf.Min(weights.Count, FaceShapes.Visemes.Length);
            for (var v = 0; v < count; v++) SetWeight(FaceShapes.Visemes[v], weights[v]);
        }

        /// <summary>Set every blendshape on the avatar to zero (neutral face).</summary>
        public void ResetAll()
        {
            EnsureBuilt();
            foreach (var targets in _targets.Values)
            foreach (var t in targets)
                if (t.Renderer != null) t.Renderer.SetBlendShapeWeight(t.Index, 0f);
        }

        /// <summary>Names from <paramref name="expected"/> the avatar does not have.</summary>
        public List<string> Missing(IEnumerable<string> expected)
        {
            EnsureBuilt();
            var missing = new List<string>();
            foreach (var name in expected)
                if (!_targets.ContainsKey(name)) missing.Add(name);
            return missing;
        }
    }
}
