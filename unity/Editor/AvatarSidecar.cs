using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace TalkingAvatarKit.Editor
{
    /// <summary>
    /// The <c>&lt;slug&gt;.tak.json</c> sidecar written by <c>python -m tak export fbx</c> next to each FBX.
    /// Its presence marks an FBX as a talking-avatar-kit avatar.
    /// </summary>
    public sealed class AvatarSidecar
    {
        public const string Suffix = ".tak.json";
        public const string Schema = "talking-avatar-kit/fbx-sidecar";

        public sealed class SkeletonEntry
        {
            public string Name;
            public string Parent;
            public Vector3 Position;
            public Quaternion Rotation;
            public Vector3 Scale = Vector3.one;
            public Vector3 WorldPosition;
            public Vector3? WorldTail;
        }

        public string Path;
        public string Folder;
        public string Slug;
        public string Name;
        public string LicenseId;
        public string LicenseUrl;
        public string Attribution;
        public float HeightM;
        public string Armature;
        public List<string> Bones = new List<string>();
        public Dictionary<string, string> Humanoid = new Dictionary<string, string>();
        public List<SkeletonEntry> Skeleton = new List<SkeletonEntry>();
        public Dictionary<string, List<string>> BlendShapes = new Dictionary<string, List<string>>();
        public List<string> Arkit = new List<string>();
        public List<string> Visemes = new List<string>();
        public Dictionary<string, Dictionary<string, object>> Materials = new Dictionary<string, Dictionary<string, object>>();
        public Dictionary<string, Dictionary<string, object>> Textures = new Dictionary<string, Dictionary<string, object>>();

        public static string PathFor(string modelPath)
        {
            var dir = System.IO.Path.GetDirectoryName(modelPath) ?? "";
            var stem = System.IO.Path.GetFileNameWithoutExtension(modelPath);
            return (dir.Length > 0 ? dir + "/" : "") + stem + Suffix;
        }

        /// <summary>The sidecar of a model asset, or null when the model is not a kit avatar.</summary>
        public static AvatarSidecar ForModel(string modelPath)
        {
            var path = PathFor(modelPath).Replace('\\', '/');
            return File.Exists(path) ? Load(path) : null;
        }

        /// <summary>Sidecars in the folder above a texture's folder (avatars keep textures in textures/).</summary>
        public static IEnumerable<AvatarSidecar> ForTexture(string texturePath)
        {
            var texDir = System.IO.Path.GetDirectoryName(texturePath);
            var avatarDir = texDir != null ? System.IO.Path.GetDirectoryName(texDir) : null;
            if (string.IsNullOrEmpty(avatarDir) || !Directory.Exists(avatarDir)) yield break;
            foreach (var file in Directory.GetFiles(avatarDir, "*" + Suffix))
            {
                AvatarSidecar sidecar = null;
                try { sidecar = Load(file.Replace('\\', '/')); }
                catch (Exception e) { Debug.LogWarning($"Talking Avatar Kit: cannot read {file}: {e.Message}"); }
                if (sidecar != null) yield return sidecar;
            }
        }

        public static AvatarSidecar Load(string path)
        {
            var root = MiniJson.Parse(File.ReadAllText(path)) as Dictionary<string, object>
                       ?? throw new FormatException("sidecar is not a JSON object");
            if (Str(root, "schema") != Schema) throw new FormatException($"{path} is not a {Schema} file");
            var s = new AvatarSidecar
            {
                Path = path,
                Folder = System.IO.Path.GetDirectoryName(path)?.Replace('\\', '/') ?? "",
                Slug = Str(root, "slug"),
                Name = Str(root, "name"),
            };
            var lic = Obj(root, "license");
            s.LicenseId = Str(lic, "id");
            s.LicenseUrl = Str(lic, "url");
            s.Attribution = Str(lic, "attribution");
            s.HeightM = (float)Num(Obj(root, "units"), "height_m");
            var rig = Obj(root, "rig");
            s.Armature = Str(rig, "armature");
            foreach (var b in Arr(rig, "bones")) s.Bones.Add(b as string);
            foreach (var pair in Obj(rig, "humanoid")) s.Humanoid[pair.Key] = pair.Value as string;
            foreach (var item in Arr(rig, "skeleton"))
            {
                var e = (Dictionary<string, object>)item;
                var entry = new SkeletonEntry
                {
                    Name = Str(e, "name"),
                    Parent = Str(e, "parent"),
                    Position = Vec3(e, "position"),
                    Rotation = Quat(e, "rotation"),
                    Scale = e.ContainsKey("scale") ? Vec3(e, "scale") : Vector3.one,
                    WorldPosition = e.ContainsKey("world_position") ? Vec3(e, "world_position") : Vector3.zero,
                };
                if (e.ContainsKey("world_tail")) entry.WorldTail = Vec3(e, "world_tail");
                s.Skeleton.Add(entry);
            }
            var shapes = Obj(root, "blendshapes");
            foreach (var pair in Obj(shapes, "meshes"))
            {
                var list = new List<string>();
                foreach (var n in (List<object>)pair.Value) list.Add(n as string);
                s.BlendShapes[pair.Key] = list;
            }
            foreach (var n in Arr(shapes, "arkit")) s.Arkit.Add(n as string);
            foreach (var n in Arr(shapes, "visemes")) s.Visemes.Add(n as string);
            foreach (var pair in Obj(root, "materials"))
                s.Materials[pair.Key] = (Dictionary<string, object>)pair.Value;
            foreach (var item in Arr(root, "textures"))
            {
                var t = (Dictionary<string, object>)item;
                s.Textures[Str(t, "file")] = t;
            }
            return s;
        }

        /// <summary>Asset path of a file named in the sidecar (relative to the FBX folder).</summary>
        public string AssetPath(string relative) => Folder + "/" + relative;

        // ------------------------------------------------------------------ JSON helpers

        public static string Str(Dictionary<string, object> d, string key) =>
            d != null && d.TryGetValue(key, out var v) ? v as string : null;

        public static double Num(Dictionary<string, object> d, string key, double fallback = 0)
        {
            if (d == null || !d.TryGetValue(key, out var v)) return fallback;
            switch (v)
            {
                case double x: return x;
                case float or int or long: return Convert.ToDouble(v, CultureInfo.InvariantCulture);
                default: return fallback;
            }
        }

        public static bool Bool(Dictionary<string, object> d, string key) =>
            d != null && d.TryGetValue(key, out var v) && v is bool b && b;

        public static Dictionary<string, object> Obj(Dictionary<string, object> d, string key) =>
            d != null && d.TryGetValue(key, out var v) && v is Dictionary<string, object> o ? o : new Dictionary<string, object>();

        public static List<object> Arr(Dictionary<string, object> d, string key) =>
            d != null && d.TryGetValue(key, out var v) && v is List<object> l ? l : new List<object>();

        static float F(object o) => o is double d ? (float)d : Convert.ToSingle(o, CultureInfo.InvariantCulture);

        static Vector3 Vec3(Dictionary<string, object> d, string key)
        {
            var a = Arr(d, key);
            return new Vector3(F(a[0]), F(a[1]), F(a[2]));
        }

        static Quaternion Quat(Dictionary<string, object> d, string key)
        {
            var a = Arr(d, key);
            return new Quaternion(F(a[0]), F(a[1]), F(a[2]), F(a[3]));
        }

        public static Color ColorOf(Dictionary<string, object> d, string key, Color fallback)
        {
            var a = Arr(d, key);
            if (a.Count < 3) return fallback;
            return new Color(F(a[0]), F(a[1]), F(a[2]), a.Count > 3 ? F(a[3]) : 1f);
        }
    }
}
