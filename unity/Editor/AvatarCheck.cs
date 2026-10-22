using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace TalkingAvatarKit.Editor
{
    /// <summary>
    /// Validates imported kit avatars and renders preview images.
    ///
    /// Batch mode (used by <c>python -m tak export fbx --unity-check</c>):
    /// <code>Unity -batchmode -quit -projectPath P -executeMethod TalkingAvatarKit.Editor.AvatarCheck.RunBatch
    ///     -takReport report.json -takPreviews previews/ -takPipelines builtin,urp</code>
    /// Menu: Tools > Talking Avatar Kit > Validate Avatars.
    /// </summary>
    public static class AvatarCheck
    {
        const string UrpAssetFolder = "Assets/TalkingAvatarKitCheck";
        static readonly List<string> LogErrors = new List<string>();
        /// <summary>Diagnostic (-takColdRender): asynchronous shader compilation and no warm-up frame, as before the fix.</summary>
        static bool ColdRender;

        // ------------------------------------------------------------------ entry points

        [MenuItem("Tools/Talking Avatar Kit/Validate Avatars")]
        static void ValidateMenu()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            var dir = Path.Combine("Temp", "TalkingAvatarKit");
            var report = ValidateAll(dir);
            var path = Path.Combine(dir, "report.json");
            File.WriteAllText(path, MiniJson.Serialize(report));
            var ok = report.TryGetValue("ok", out var v) && v is bool b && b;
            Debug.Log($"Talking Avatar Kit: validation {(ok ? "passed" : "FAILED")}; report and previews in {Path.GetFullPath(dir)}");
        }

        [MenuItem("Tools/Talking Avatar Kit/Reimport Avatars")]
        static void ReimportMenu()
        {
            foreach (var model in FindAvatars()) ReimportAvatar(model);
        }

        /// <summary>Batch-mode entry point; exits the editor with 0 (all valid), 1 (problems) or 2 (error).</summary>
        public static void RunBatch()
        {
            var reportPath = Arg("-takReport") ?? "tak-unity-report.json";
            var previews = Arg("-takPreviews") ?? "tak-previews";
            var pipelines = (Arg("-takPipelines") ?? "builtin").Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);
            var report = new Dictionary<string, object>
            {
                ["unity_version"] = Application.unityVersion,
                ["color_space"] = PlayerSettings.colorSpace.ToString(),
                ["graphics_device"] = SystemInfo.graphicsDeviceType.ToString(),
            };
            var code = 0;
            ColdRender = Environment.GetCommandLineArgs().Contains("-takColdRender");
            if (ColdRender) report["cold_render"] = true;
            Application.logMessageReceived += OnLog;
            try
            {
                if (PlayerSettings.colorSpace != ColorSpace.Linear)
                {
                    PlayerSettings.colorSpace = ColorSpace.Linear;
                    report["color_space"] = "Linear";
                }
                var results = new Dictionary<string, object>();
                var allOk = true;
                foreach (var pipeline in pipelines)
                {
                    LogErrors.Clear();
                    var setup = SetPipeline(pipeline.Trim());
                    var models = FindAvatars();
                    foreach (var model in models) ReimportAvatar(model);
                    var result = ValidateAll(previews, pipeline.Trim());
                    result["pipeline_setup"] = setup;
                    result["log_errors"] = new List<object>(LogErrors.Distinct().Take(40));
                    results[pipeline.Trim()] = result;
                    allOk &= result["ok"] is bool ok && ok;
                }
                report["pipelines"] = results;
                if (results.TryGetValue("builtin", out var b) && results.TryGetValue("urp", out var u))
                {
                    var cross = ComparePipelines((Dictionary<string, object>)b, (Dictionary<string, object>)u);
                    report["cross_pipeline"] = cross;
                    allOk &= cross["ok"] is bool crossOk && crossOk;
                }
                report["ok"] = allOk;
                code = allOk ? 0 : 1;
            }
            catch (Exception e)
            {
                report["ok"] = false;
                report["error"] = e.ToString();
                code = 2;
            }
            finally
            {
                Application.logMessageReceived -= OnLog;
            }
            var dir = Path.GetDirectoryName(Path.GetFullPath(reportPath));
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            File.WriteAllText(reportPath, MiniJson.Serialize(report));
            EditorApplication.Exit(code);
        }

        /// <summary>Largest allowed difference (0-255, mean over RGB) between the pipelines' mean colour of a material region.</summary>
        public const double RegionTolerance = 40.0;
        /// <summary>Regions smaller than this many pixels are not compared (lashes, brows, mouth interior).</summary>
        public const long RegionMinPixels = 400;

        /// <summary>
        /// Compare, per avatar, view and material, the mean colour of the material's pixels in the built-in and
        /// URP previews. Lighting models differ a little; a missing or wrong texture, a broken shader variant or
        /// a material set up as a mirror changes a region's mean colour far more than that.
        /// </summary>
        public static Dictionary<string, object> ComparePipelines(Dictionary<string, object> builtin, Dictionary<string, object> urp)
        {
            var ok = true;
            var avatars = new Dictionary<string, object>();
            var ba = AvatarSidecar.Obj(builtin, "avatars");
            var ua = AvatarSidecar.Obj(urp, "avatars");
            foreach (var slug in ba.Keys.Intersect(ua.Keys))
            {
                var views = new Dictionary<string, object>();
                var bp = AvatarSidecar.Obj((Dictionary<string, object>)ba[slug], "previews");
                var up = AvatarSidecar.Obj((Dictionary<string, object>)ua[slug], "previews");
                foreach (var view in bp.Keys.Intersect(up.Keys))
                {
                    var bm = AvatarSidecar.Obj((Dictionary<string, object>)bp[view], "materials");
                    var um = AvatarSidecar.Obj((Dictionary<string, object>)up[view], "materials");
                    if (bm.Count == 0 || um.Count == 0) continue;
                    var worst = 0.0;
                    var worstName = "";
                    var compared = 0;
                    var failed = new List<object>();
                    foreach (var mat in bm.Keys.Intersect(um.Keys))
                    {
                        var x = (Dictionary<string, object>)bm[mat];
                        var y = (Dictionary<string, object>)um[mat];
                        if (AvatarSidecar.Num(x, "pixels") < RegionMinPixels || AvatarSidecar.Num(y, "pixels") < RegionMinPixels) continue;
                        var mx = AvatarSidecar.Arr(x, "mean");
                        var my = AvatarSidecar.Arr(y, "mean");
                        var d = Enumerable.Range(0, 3).Average(i => Math.Abs((double)mx[i] - (double)my[i]));
                        compared++;
                        if (d > worst) { worst = d; worstName = mat; }
                        if (d > RegionTolerance) failed.Add($"{mat} {d:F0}");
                    }
                    ok &= failed.Count == 0;
                    views[view] = new Dictionary<string, object>
                    {
                        ["ok"] = failed.Count == 0,
                        ["regions"] = compared,
                        ["max_difference"] = Math.Round(worst, 1),
                        ["worst"] = worstName,
                        ["failed"] = failed,
                    };
                }
                avatars[slug] = views;
            }
            return new Dictionary<string, object> { ["ok"] = ok, ["tolerance"] = RegionTolerance, ["avatars"] = avatars };
        }

        static void OnLog(string message, string stack, LogType type)
        {
            if (type == LogType.Error || type == LogType.Exception || type == LogType.Assert)
                LogErrors.Add(message.Length > 400 ? message.Substring(0, 400) : message);
        }

        static string Arg(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (var i = 0; i < args.Length - 1; i++)
                if (args[i] == name) return args[i + 1];
            return null;
        }

        // ------------------------------------------------------------------ pipelines

        /// <summary>Switch to the built-in pipeline ("builtin") or a generated URP asset ("urp").</summary>
        public static Dictionary<string, object> SetPipeline(string pipeline)
        {
            var info = new Dictionary<string, object> { ["requested"] = pipeline };
            RenderPipelineAsset asset = null;
            if (pipeline == "urp")
            {
                asset = CreateUrpAsset(info);
                if (asset == null) throw new InvalidOperationException("URP is not available in this project: " + info["error"]);
            }
            GraphicsSettings.defaultRenderPipeline = asset;
            for (var level = 0; level < QualitySettings.names.Length; level++)
            {
                QualitySettings.SetQualityLevel(level, false);
                QualitySettings.renderPipeline = null;
            }
            AssetDatabase.SaveAssets();
            // Registering the new pipeline re-imports the avatars through their custom dependency.
            PipelineDependency.Register(refresh: true);
            info["active"] = MaterialSetup.Current().ToString();
            info["shader"] = MaterialSetup.ShaderName();
            var followed = new List<object>();
            foreach (var model in FindAvatars())
            {
                var sidecar = AvatarSidecar.ForModel(model);
                var mats = AssetDatabase.LoadAllAssetsAtPath(model).OfType<Material>().ToList();
                var ok = mats.Count > 0 && mats.All(m =>
                    sidecar.Materials.TryGetValue(m.name, out var spec) && m.shader != null && m.shader.name == MaterialSetup.ShaderFor(spec));
                if (!ok) followed.Add(Path.GetFileNameWithoutExtension(model));
            }
            info["reimported_by_dependency"] = followed.Count == 0;
            if (followed.Count > 0) info["not_reimported"] = followed;
            return info;
        }

        static RenderPipelineAsset CreateUrpAsset(Dictionary<string, object> info)
        {
            var path = UrpAssetFolder + "/URP.asset";
            var existing = AssetDatabase.LoadAssetAtPath<RenderPipelineAsset>(path);
            if (existing != null) return existing;
            var assetType = Type.GetType("UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset, Unity.RenderPipelines.Universal.Runtime");
            var dataType = Type.GetType("UnityEngine.Rendering.Universal.UniversalRendererData, Unity.RenderPipelines.Universal.Runtime");
            if (assetType == null || dataType == null)
            {
                info["error"] = "com.unity.render-pipelines.universal is not installed";
                return null;
            }
            if (!AssetDatabase.IsValidFolder(UrpAssetFolder)) AssetDatabase.CreateFolder("Assets", "TalkingAvatarKitCheck");
            var data = ScriptableObject.CreateInstance(dataType);
            AssetDatabase.CreateAsset(data, UrpAssetFolder + "/URP_Renderer.asset");
            var create = assetType.GetMethods().FirstOrDefault(m => m.Name == "Create" && m.IsStatic && m.GetParameters().Length == 1);
            if (create == null)
            {
                info["error"] = "UniversalRenderPipelineAsset.Create not found";
                return null;
            }
            var asset = (RenderPipelineAsset)create.Invoke(null, new object[] { data });
            AssetDatabase.CreateAsset(asset, path);
            AssetDatabase.SaveAssets();
            info["created"] = path;
            return asset;
        }

        // ------------------------------------------------------------------ discovery

        /// <summary>Model asset paths of every avatar (FBX with a sidecar) under Assets/.</summary>
        public static List<string> FindAvatars()
        {
            var models = new List<string>();
            foreach (var guid in AssetDatabase.FindAssets("t:Model", new[] { "Assets" }))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (File.Exists(AvatarSidecar.PathFor(path))) models.Add(path);
            }
            models.Sort(StringComparer.Ordinal);
            return models;
        }

        public static void ReimportAvatar(string modelPath)
        {
            var folder = Path.GetDirectoryName(modelPath)?.Replace('\\', '/');
            var textures = folder + "/textures";
            if (AssetDatabase.IsValidFolder(textures))
                AssetDatabase.ImportAsset(textures, ImportAssetOptions.ImportRecursive | ImportAssetOptions.ForceUpdate);
            AssetDatabase.ImportAsset(modelPath, ImportAssetOptions.ForceUpdate);
        }

        // ------------------------------------------------------------------ validation

        public static Dictionary<string, object> ValidateAll(string previewDir, string label = null)
        {
            label = label ?? (MaterialSetup.Current() == MaterialSetup.Pipeline.Universal ? "urp" : "builtin");
            var avatars = new Dictionary<string, object>();
            var ok = true;
            var models = FindAvatars();
            foreach (var model in models)
            {
                Dictionary<string, object> result;
                try
                {
                    result = Validate(model, previewDir, label);
                }
                catch (Exception e)
                {
                    result = new Dictionary<string, object> { ["ok"] = false, ["error"] = e.ToString() };
                }
                avatars[Path.GetFileNameWithoutExtension(model)] = result;
                ok &= result["ok"] is bool b && b;
            }
            return new Dictionary<string, object>
            {
                ["ok"] = ok && models.Count > 0,
                ["shader"] = MaterialSetup.ShaderName(),
                ["avatars"] = avatars,
            };
        }

        sealed class Checks
        {
            public readonly List<object> Items = new List<object>();
            public bool Ok = true;

            public void Add(string name, bool ok, string detail)
            {
                Items.Add(new Dictionary<string, object> { ["check"] = name, ["ok"] = ok, ["detail"] = detail });
                Ok &= ok;
            }
        }

        public static Dictionary<string, object> Validate(string modelPath, string previewDir, string label)
        {
            var sidecar = AvatarSidecar.ForModel(modelPath) ?? throw new InvalidOperationException("no sidecar for " + modelPath);
            var importer = (ModelImporter)AssetImporter.GetAtPath(modelPath);
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(modelPath);
            var avatar = AssetDatabase.LoadAllAssetsAtPath(modelPath).OfType<Avatar>().FirstOrDefault();
            var checks = new Checks();
            var info = new Dictionary<string, object> { ["model"] = modelPath };

            checks.Add("animation_type", importer.animationType == ModelImporterAnimationType.Human,
                importer.animationType.ToString());
            checks.Add("avatar", avatar != null && avatar.isValid && avatar.isHuman,
                avatar == null ? "no avatar" : $"isValid={avatar.isValid}, isHuman={avatar.isHuman}");

            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var inst = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            var animator = inst.GetComponent<Animator>();
            var transforms = new Dictionary<string, Transform>();
            foreach (var t in inst.GetComponentsInChildren<Transform>(true))
                if (!transforms.ContainsKey(t.name)) transforms[t.name] = t;

            // Human bones: every mapped bone resolves, every required bone is present, names match the sidecar.
            var mapped = 0;
            var missingRequired = new List<string>();
            var wrong = new List<string>();
            for (var i = 0; i < HumanTrait.BoneCount; i++)
            {
                var humanName = HumanTrait.BoneName[i];
                var t = animator != null && avatar != null && avatar.isHuman ? animator.GetBoneTransform((HumanBodyBones)i) : null;
                sidecar.Humanoid.TryGetValue(humanName, out var expected);
                if (t != null)
                {
                    mapped++;
                    if (expected != null && t.name != expected) wrong.Add($"{humanName}={t.name} (expected {expected})");
                }
                else if (HumanTrait.RequiredBone(i)) missingRequired.Add(humanName);
                else if (expected != null) wrong.Add($"{humanName} unmapped (expected {expected})");
            }
            checks.Add("human_bones", missingRequired.Count == 0 && wrong.Count == 0 && mapped == sidecar.Humanoid.Count,
                $"{mapped} of {HumanTrait.BoneCount} Mecanim bones mapped (sidecar {sidecar.Humanoid.Count})"
                + (missingRequired.Count > 0 ? "; missing required " + string.Join(", ", missingRequired) : "")
                + (wrong.Count > 0 ? "; " + string.Join(", ", wrong) : ""));

            // Blendshapes: exact names per mesh.
            var renderers = inst.GetComponentsInChildren<SkinnedMeshRenderer>(true);
            var shapeProblems = new List<string>();
            var shapeCounts = new Dictionary<string, object>();
            foreach (var r in renderers)
            {
                var mesh = r.sharedMesh;
                var names = new List<string>();
                for (var i = 0; mesh != null && i < mesh.blendShapeCount; i++) names.Add(mesh.GetBlendShapeName(i));
                shapeCounts[r.name] = names.Count;
                sidecar.BlendShapes.TryGetValue(r.name, out var expected);
                expected = expected ?? new List<string>();
                var missing = expected.Except(names).ToList();
                var extra = names.Except(expected).ToList();
                if (missing.Count > 0) shapeProblems.Add($"{r.name} missing {string.Join(",", missing.Take(5))}");
                if (extra.Count > 0) shapeProblems.Add($"{r.name} unexpected {string.Join(",", extra.Take(5))}");
            }
            foreach (var mesh in sidecar.BlendShapes.Keys)
                if (renderers.All(r => r.name != mesh)) shapeProblems.Add($"mesh {mesh} not imported");
            var blend = inst.GetComponent<AvatarBlendShapes>();
            var missingFace = blend != null ? blend.Missing(FaceShapes.Arkit.Concat(FaceShapes.Visemes)) : new List<string> { "AvatarBlendShapes component missing" };
            checks.Add("blendshapes", shapeProblems.Count == 0 && missingFace.Count == 0,
                string.Join(", ", shapeCounts.Where(p => (int)p.Value > 0).Select(p => $"{p.Key} {p.Value}"))
                + (missingFace.Count > 0 ? "; missing " + string.Join(",", missingFace.Take(8)) : "")
                + (shapeProblems.Count > 0 ? "; " + string.Join("; ", shapeProblems) : ""));
            info["blendshapes"] = shapeCounts;

            // Materials: assigned, expected shader, textures present.
            var shaderName = MaterialSetup.ShaderName();
            var matProblems = new List<string>();
            var matNames = new SortedSet<string>();
            foreach (var r in renderers)
            foreach (var m in r.sharedMaterials)
            {
                if (m == null) { matProblems.Add($"{r.name} has an empty slot"); continue; }
                matNames.Add(m.name);
                if (!sidecar.Materials.TryGetValue(m.name, out var spec)) { matProblems.Add($"{m.name} not in sidecar"); continue; }
                var expectedShader = MaterialSetup.ShaderFor(spec);
                if (m.shader == null || m.shader.name != expectedShader) matProblems.Add($"{m.name} uses {m.shader?.name}, expected {expectedShader}");
                if (spec.ContainsKey("base_color") && m.mainTexture == null) matProblems.Add($"{m.name} lacks its base colour texture");
                if (spec.ContainsKey("normal") && m.GetTexture("_BumpMap") == null) matProblems.Add($"{m.name} lacks its normal map");
                if (spec.ContainsKey("metallic_smoothness") && m.GetTexture("_MetallicGlossMap") == null) matProblems.Add($"{m.name} lacks its metallic-smoothness map");
                if (spec.ContainsKey("specular_smoothness") && m.GetTexture("_SpecGlossMap") == null) matProblems.Add($"{m.name} lacks its specular-smoothness map");
            }
            foreach (var name in sidecar.Materials.Keys)
                if (!matNames.Contains(name)) matProblems.Add($"material {name} not used");
            checks.Add("materials", matProblems.Count == 0,
                $"{matNames.Count} materials on {shaderName}" + (matProblems.Count > 0 ? "; " + string.Join("; ", matProblems) : ""));

            // Material properties: the right files in the right slots, plausible reflectance and smoothness, keywords.
            var propProblems = new List<string>();
            var seen = new HashSet<string>();
            foreach (var m in renderers.SelectMany(r => r.sharedMaterials).Where(m => m != null))
                if (seen.Add(m.name) && sidecar.Materials.TryGetValue(m.name, out var spec))
                    propProblems.AddRange(MaterialProblems(m, spec, sidecar));
            checks.Add("material_properties", propProblems.Count == 0,
                $"{seen.Count} materials: texture bindings, workflow, reflectance, smoothness, keywords"
                + (propProblems.Count > 0 ? "; " + string.Join("; ", propProblems.Take(12)) : ""));

            // Normal-map texture type and colour spaces from the sidecar.
            var texProblems = new List<string>();
            foreach (var pair in sidecar.Textures)
            {
                var ti = AssetImporter.GetAtPath(sidecar.AssetPath(pair.Key)) as TextureImporter;
                if (ti == null) { texProblems.Add($"{pair.Key} not imported"); continue; }
                if (AvatarSidecar.Bool(pair.Value, "normal_map") != (ti.textureType == TextureImporterType.NormalMap)) texProblems.Add($"{pair.Key} type {ti.textureType}");
                if ((AvatarSidecar.Str(pair.Value, "color_space") == "linear") == ti.sRGBTexture) texProblems.Add($"{pair.Key} sRGB={ti.sRGBTexture}");
            }
            checks.Add("textures", texProblems.Count == 0, $"{sidecar.Textures.Count} textures" + (texProblems.Count > 0 ? "; " + string.Join("; ", texProblems) : ""));

            // Scale and orientation.
            var armature = sidecar.Armature != null && transforms.TryGetValue(sidecar.Armature, out var arm) ? arm : null;
            var rootOk = inst.transform.localScale == Vector3.one && armature != null
                         && (armature.localScale - Vector3.one).magnitude < 1e-4f
                         && Quaternion.Angle(armature.localRotation, Quaternion.identity) < 0.01f;
            checks.Add("root_transform", rootOk, armature == null ? "armature node not found"
                : $"armature rotation {armature.localEulerAngles}, scale {armature.localScale}");
            var (lo, hi) = Bounds(renderers);
            var height = hi.y - lo.y;
            info["height_m"] = Math.Round(height, 4);
            checks.Add("scale", Mathf.Abs(height - sidecar.HeightM) < 0.02f && lo.y > -0.1f && lo.y < 0.1f,
                $"{height:F3} m tall (sidecar {sidecar.HeightM:F3} m), feet at y={lo.y:F3}");
            Transform Bone(HumanBodyBones b) => animator != null && avatar != null && avatar.isHuman ? animator.GetBoneTransform(b) : null;
            var foot = Bone(HumanBodyBones.LeftFoot);
            var toes = Bone(HumanBodyBones.LeftToes);
            var lHand = Bone(HumanBodyBones.LeftHand);
            var rHand = Bone(HumanBodyBones.RightHand);
            var head = Bone(HumanBodyBones.Head);
            var facing = foot != null && toes != null && toes.position.z > foot.position.z;
            var sides = lHand != null && rHand != null && lHand.position.x < 0f && rHand.position.x > 0f;
            checks.Add("orientation", facing && sides && head != null && head.position.y > 0.7f * height,
                facing && sides ? "upright, facing +Z, left hand on -X" : $"facing +Z: {facing}, left on -X: {sides}");

            // Rest pose matches the sidecar (the T-pose derivation depends on it).
            float maxPos = 0f, maxAngle = 0f;
            string worst = null;
            foreach (var e in sidecar.Skeleton.Skip(1))
            {
                if (!transforms.TryGetValue(e.Name, out var t)) { worst = "missing " + e.Name; maxPos = float.PositiveInfinity; break; }
                var dp = (t.localPosition - e.Position).magnitude;
                var da = Quaternion.Angle(t.localRotation, e.Rotation);
                if (dp > maxPos) maxPos = dp;
                if (da > maxAngle) { maxAngle = da; worst = e.Name; }
            }
            checks.Add("rest_skeleton", maxPos < 1e-3f && maxAngle < 0.5f,
                $"max position error {maxPos * 1000f:F2} mm, max rotation error {maxAngle:F2} deg ({worst})");

            // Previews: rest pose, face, face with a viseme and a blink, T-pose reference.
            Directory.CreateDirectory(previewDir);
            var slug = Path.GetFileNameWithoutExtension(modelPath);
            var stage = new PreviewStage(ColdRender);
            var images = new Dictionary<string, object>();
            var center = new Vector3(0f, (lo.y + hi.y) * 0.5f, 0f);
            images["full"] = stage.Shoot(inst, previewDir, $"{slug}_{label}_full", center, height * 1.08f, 512, 896, regions: true);
            if (head != null)
            {
                var face = head.position + new Vector3(0f, 0.04f, 0f);
                images["face"] = stage.Shoot(inst, previewDir, $"{slug}_{label}_face", face, 0.30f, 512, 512, regions: true);
                if (blend != null)
                {
                    blend.Rebuild();
                    blend.SetViseme(Viseme.aa, 1f);
                    blend.SetWeight("eyeBlinkLeft", 1f);
                    images["face_viseme_aa_blink"] = stage.Shoot(inst, previewDir, $"{slug}_{label}_face_aa_blink", face, 0.30f, 512, 512);
                    blend.ResetAll();
                }
            }

            // T-pose: pose the instance with the avatar's reference skeleton and measure the limbs.
            var skeleton = importer.humanDescription.skeleton;
            foreach (var sb in skeleton)
                if (transforms.TryGetValue(sb.name, out var t) && t != inst.transform)
                {
                    t.localPosition = sb.position;
                    t.localRotation = sb.rotation;
                }
            var limbs = new (HumanBodyBones from, HumanBodyBones to, Vector3 dir)[]
            {
                (HumanBodyBones.LeftUpperArm, HumanBodyBones.LeftLowerArm, Vector3.left),
                (HumanBodyBones.LeftLowerArm, HumanBodyBones.LeftHand, Vector3.left),
                (HumanBodyBones.LeftHand, HumanBodyBones.LeftMiddleProximal, Vector3.left),
                (HumanBodyBones.RightUpperArm, HumanBodyBones.RightLowerArm, Vector3.right),
                (HumanBodyBones.RightLowerArm, HumanBodyBones.RightHand, Vector3.right),
                (HumanBodyBones.RightHand, HumanBodyBones.RightMiddleProximal, Vector3.right),
                (HumanBodyBones.LeftUpperLeg, HumanBodyBones.LeftLowerLeg, Vector3.down),
                (HumanBodyBones.RightUpperLeg, HumanBodyBones.RightLowerLeg, Vector3.down),
            };
            var maxLimb = 0f;
            var worstLimb = "";
            foreach (var (from, to, dir) in limbs)
            {
                var a = Bone(from);
                var b = Bone(to);
                if (a == null || b == null) { maxLimb = 180f; worstLimb = from.ToString(); break; }
                var angle = Vector3.Angle(b.position - a.position, dir);
                if (angle > maxLimb) { maxLimb = angle; worstLimb = from.ToString(); }
            }
            checks.Add("t_pose", maxLimb < 2f,
                $"reference pose: arms, hands and legs within {maxLimb:F2} deg of the T-pose axes (worst {worstLimb})");
            images["t_pose"] = stage.Shoot(inst, previewDir, $"{slug}_{label}_tpose", center, height * 1.08f, 768, 768);
            stage.Dispose();
            UnityEngine.Object.DestroyImmediate(inst);

            var coverage = images.Values.OfType<Dictionary<string, object>>().ToList();
            var badShots = coverage.Where(s => !(s["ok"] is bool sb2 && sb2)).Select(s => s["file"] as string).ToList();
            checks.Add("previews", badShots.Count == 0,
                $"{coverage.Count} images" + (badShots.Count > 0 ? "; empty, error-shader pixels or first frame differs in " + string.Join(", ", badShots) : ""));

            info["previews"] = images;
            info["checks"] = checks.Items;
            info["ok"] = checks.Ok;
            return info;
        }

        /// <summary>Problems with one imported material compared with its sidecar entry (empty when it is set up right).</summary>
        public static List<string> MaterialProblems(Material m, Dictionary<string, object> spec, AvatarSidecar sidecar)
        {
            var problems = new List<string>();
            var urp = m.shader != null && m.shader.name == MaterialSetup.UrpLit;
            var specular = MaterialSetup.UsesSpecular(spec);

            void Bound(string key, string property)
            {
                var file = AvatarSidecar.Str(AvatarSidecar.Obj(spec, key), "file");
                if (file == null) return;
                var tex = m.HasProperty(property) ? m.GetTexture(property) : null;
                var path = tex != null ? AssetDatabase.GetAssetPath(tex) : null;
                if (path != sidecar.AssetPath(file)) problems.Add($"{m.name}.{property} is {path ?? "empty"}, expected {file}");
            }

            Bound("base_color", urp ? "_BaseMap" : "_MainTex");
            Bound("normal", "_BumpMap");
            Bound("metallic_smoothness", "_MetallicGlossMap");
            Bound("specular_smoothness", "_SpecGlossMap");
            if (spec.ContainsKey("base_color"))
            {
                var ti = AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(m.mainTexture)) as TextureImporter;
                if (ti != null && ti.textureType == TextureImporterType.NormalMap) problems.Add($"{m.name} base map is imported as a normal map");
            }
            var color = urp ? m.GetColor("_BaseColor") : m.GetColor("_Color");
            var expected = AvatarSidecar.ColorOf(spec, "base_color_factor", Color.white);
            if (Mathf.Abs(color.linear.r - expected.r) + Mathf.Abs(color.linear.g - expected.g) + Mathf.Abs(color.linear.b - expected.b) > 0.03f)
                problems.Add($"{m.name} base colour {color} does not match the sidecar");
            if (specular)
            {
                var f0 = m.GetColor("_SpecColor").linear.grayscale;
                if (f0 < 0.005f || f0 > 0.1f) problems.Add($"{m.name} specular reflectance {f0:F3} outside 0.005-0.1");
                if (urp && (m.GetFloat("_WorkflowMode") != 0f || !m.IsKeywordEnabled("_SPECULAR_SETUP")))
                    problems.Add($"{m.name} is not in the specular workflow");
            }
            else if (urp && m.GetFloat("_WorkflowMode") != 1f)
            {
                problems.Add($"{m.name} is not in the metallic workflow");
            }
            var hasMap = spec.ContainsKey("metallic_smoothness") || spec.ContainsKey("specular_smoothness");
            var smoothProperty = urp ? "_Smoothness" : hasMap ? "_GlossMapScale" : "_Glossiness";
            var smooth = m.GetFloat(smoothProperty);
            var expectedSmooth = hasMap ? 1.0 : AvatarSidecar.Num(spec, "smoothness", 0.5);
            if (Math.Abs(smooth - expectedSmooth) > 0.01) problems.Add($"{m.name}.{smoothProperty} {smooth:F2}, expected {expectedSmooth:F2}");
            if (!hasMap && smooth > 0.9f) problems.Add($"{m.name} smoothness {smooth:F2} would look like a mirror");
            if (urp && m.GetFloat("_Metallic") > 0.01f && AvatarSidecar.Num(spec, "metallic") < 0.01) problems.Add($"{m.name} is metallic");
            if (spec.ContainsKey("normal") != m.IsKeywordEnabled("_NORMALMAP")) problems.Add($"{m.name} _NORMALMAP keyword wrong");
            var alpha = AvatarSidecar.Str(spec, "alpha_mode") ?? "OPAQUE";
            if ((alpha == "MASK") != m.IsKeywordEnabled("_ALPHATEST_ON")) problems.Add($"{m.name} alpha-test keyword wrong for {alpha}");
            var blendKeyword = urp ? "_SURFACE_TYPE_TRANSPARENT" : "_ALPHABLEND_ON";
            if ((alpha == "BLEND") != m.IsKeywordEnabled(blendKeyword)) problems.Add($"{m.name} transparency keyword wrong for {alpha}");
            if (urp && AvatarSidecar.Bool(spec, "double_sided") != (m.GetFloat("_Cull") == 0f)) problems.Add($"{m.name} culling wrong");
            return problems;
        }

        static (Vector3 lo, Vector3 hi) Bounds(IEnumerable<SkinnedMeshRenderer> renderers)
        {
            var lo = Vector3.positiveInfinity;
            var hi = Vector3.negativeInfinity;
            var baked = new Mesh();
            foreach (var r in renderers)
            {
                r.BakeMesh(baked, true);
                var m = Matrix4x4.TRS(r.transform.position, r.transform.rotation, Vector3.one);
                foreach (var v in baked.vertices)
                {
                    var p = m.MultiplyPoint3x4(v);
                    lo = Vector3.Min(lo, p);
                    hi = Vector3.Max(hi, p);
                }
            }
            UnityEngine.Object.DestroyImmediate(baked);
            return (lo, hi);
        }

        /// <summary>
        /// Lights and a camera in the current scene; renders framed shots to PNG.
        ///
        /// Shaders are compiled synchronously while the stage exists: with the editor's asynchronous
        /// compilation the first frame that needs a new shader variant is drawn with a placeholder
        /// (cyan) shader and unfinished lighting state, which in URP gave black or mirror-like skin and
        /// blue hair in the first preview after a pipeline switch. Each shot is also rendered once to
        /// warm up, then saved, then rendered again: the saved frame must equal the next one.
        /// </summary>
        sealed class PreviewStage : IDisposable
        {
            static readonly Color Background = new Color(0.30f, 0.32f, 0.36f, 1f);
            readonly List<GameObject> _objects = new List<GameObject>();
            readonly Camera _camera;
            readonly bool _asyncWas;
            readonly bool _cold;
            readonly Material _maskOn;
            readonly Material _maskOff;

            /// <param name="cold">Diagnostic: keep asynchronous shader compilation and skip the warm-up frame.</param>
            public PreviewStage(bool cold = false)
            {
                _cold = cold;
                _asyncWas = ShaderUtil.allowAsyncCompilation;
                if (!cold) ShaderUtil.allowAsyncCompilation = false;
                RenderSettings.ambientMode = AmbientMode.Flat;
                RenderSettings.ambientLight = new Color(0.42f, 0.42f, 0.45f);
                RenderSettings.skybox = null;
                AddLight("Key", new Vector3(-0.45f, -0.45f, -1f), 1.25f, new Color(1f, 0.97f, 0.93f), true);
                AddLight("Fill", new Vector3(0.7f, -0.15f, -1f), 0.45f, new Color(0.9f, 0.93f, 1f), false);
                AddLight("Rim", new Vector3(0.2f, -0.3f, 1f), 0.5f, Color.white, false);
                var go = new GameObject("PreviewCamera");
                _objects.Add(go);
                _camera = go.AddComponent<Camera>();
                _camera.clearFlags = CameraClearFlags.SolidColor;
                _camera.backgroundColor = Background;
                _camera.fieldOfView = 20f;
                _camera.nearClipPlane = 0.02f;
                _camera.farClipPlane = 50f;
                var unlit = Shader.Find(MaterialSetup.Current() == MaterialSetup.Pipeline.Universal
                    ? "Universal Render Pipeline/Unlit" : "Unlit/Color");
                _maskOn = MaskMaterial(unlit, Color.white);
                _maskOff = MaskMaterial(unlit, Color.black);
            }

            static Material MaskMaterial(Shader shader, Color color)
            {
                var m = new Material(shader) { hideFlags = HideFlags.HideAndDontSave };
                m.SetColor("_BaseColor", color);
                m.SetColor("_Color", color);
                return m;
            }

            void AddLight(string name, Vector3 direction, float intensity, Color color, bool shadows)
            {
                var go = new GameObject(name);
                _objects.Add(go);
                var light = go.AddComponent<Light>();
                light.type = LightType.Directional;
                light.intensity = intensity;
                light.color = color;
                light.shadows = shadows ? LightShadows.Soft : LightShadows.None;
                go.transform.rotation = Quaternion.LookRotation(direction.normalized);
            }

            /// <summary>
            /// Frame <paramref name="span"/> metres (vertical) around <paramref name="target"/>, seen from +Z.
            /// Skinned meshes are baked first (current bones and blendshape weights), because edit-mode
            /// skinning is not refreshed by an explicit camera render. With <paramref name="regions"/> the
            /// result also lists, per material, the mean colour of the pixels it covers (from a mask render).
            /// </summary>
            public Dictionary<string, object> Shoot(GameObject avatar, string dir, string name, Vector3 target, float span,
                int width, int height, bool regions = false)
            {
                var baked = new List<MeshRenderer>();
                var hidden = new List<SkinnedMeshRenderer>();
                foreach (var smr in avatar.GetComponentsInChildren<SkinnedMeshRenderer>())
                {
                    if (!smr.enabled) continue;
                    var mesh = new Mesh { name = smr.name + "_baked" };
                    smr.BakeMesh(mesh, true);
                    var go = new GameObject(smr.name + "_baked");
                    go.transform.SetPositionAndRotation(smr.transform.position, smr.transform.rotation);
                    go.AddComponent<MeshFilter>().sharedMesh = mesh;
                    var mr = go.AddComponent<MeshRenderer>();
                    mr.sharedMaterials = smr.sharedMaterials;
                    baked.Add(mr);
                    smr.enabled = false;
                    hidden.Add(smr);
                }
                try
                {
                    var distance = span * 0.5f / Mathf.Tan(_camera.fieldOfView * 0.5f * Mathf.Deg2Rad);
                    _camera.transform.position = target + new Vector3(0f, 0f, distance);
                    _camera.transform.rotation = Quaternion.LookRotation(Vector3.back);
                    var (result, pixels) = Beauty(dir, name, width, height);
                    if (regions) result["materials"] = MaterialMeans(baked, pixels, width, height);
                    return result;
                }
                finally
                {
                    foreach (var mr in baked)
                    {
                        UnityEngine.Object.DestroyImmediate(mr.GetComponent<MeshFilter>().sharedMesh);
                        UnityEngine.Object.DestroyImmediate(mr.gameObject);
                    }
                    foreach (var smr in hidden) smr.enabled = true;
                }
            }

            (Dictionary<string, object>, Color32[]) Beauty(string dir, string name, int width, int height)
            {
                double warmup = 0;
                Color32[] first = null;
                if (!_cold) first = Pixels(width, height, 4);
                var pixels = Pixels(width, height, 4);
                var file = Path.Combine(dir, name + ".png");
                var tex = new Texture2D(width, height, TextureFormat.RGBA32, false, false);
                tex.SetPixels32(pixels);
                File.WriteAllBytes(file, tex.EncodeToPNG());
                UnityEngine.Object.DestroyImmediate(tex);
                var next = Pixels(width, height, 4);
                int covered = 0, magenta = 0;
                double change = 0;
                Color32 bg = pixels[0];
                for (var i = 0; i < pixels.Length; i++)
                {
                    var p = pixels[i];
                    if (Mathf.Abs(p.r - bg.r) + Mathf.Abs(p.g - bg.g) + Mathf.Abs(p.b - bg.b) > 12) covered++;
                    if (p.r > 220 && p.b > 220 && p.g < 40) magenta++;
                    change += Diff(p, next[i]);
                    if (first != null) warmup += Diff(p, first[i]);
                }
                var coverage = (float)covered / pixels.Length;
                var frameChange = covered > 0 ? change / covered : 0.0;
                return (new Dictionary<string, object>
                {
                    ["file"] = Path.GetFileName(file),
                    ["coverage"] = Math.Round(coverage, 3),
                    ["error_shader_pixels"] = magenta,
                    ["frame_change"] = Math.Round(frameChange, 2),
                    ["warmup_change"] = Math.Round(covered > 0 ? warmup / covered : 0.0, 2),
                    ["ok"] = coverage > 0.05f && magenta < pixels.Length / 1000 && frameChange < 1.0,
                }, pixels);
            }

            static double Diff(Color32 a, Color32 b) =>
                (Mathf.Abs(a.r - b.r) + Mathf.Abs(a.g - b.g) + Mathf.Abs(a.b - b.b)) / 3.0;

            /// <summary>Mean colour of the beauty pixels covered by each material (opaque mask renders, no MSAA).</summary>
            Dictionary<string, object> MaterialMeans(List<MeshRenderer> renderers, Color32[] beauty, int width, int height)
            {
                var originals = renderers.ToDictionary(r => r, r => r.sharedMaterials);
                var names = originals.Values.SelectMany(m => m).Where(m => m != null).Select(m => m.name).Distinct().OrderBy(n => n).ToList();
                var result = new Dictionary<string, object>();
                try
                {
                    foreach (var matName in names)
                    {
                        foreach (var r in renderers)
                            r.sharedMaterials = originals[r].Select(m => m != null && m.name == matName ? _maskOn : _maskOff).ToArray();
                        var mask = Pixels(width, height, 1);
                        long n = 0, sr = 0, sg = 0, sb = 0;
                        for (var i = 0; i < mask.Length; i++)
                        {
                            if (mask[i].r < 128) continue;
                            n++;
                            sr += beauty[i].r;
                            sg += beauty[i].g;
                            sb += beauty[i].b;
                        }
                        if (n == 0) continue;
                        result[matName] = new Dictionary<string, object>
                        {
                            ["pixels"] = n,
                            ["mean"] = new List<object> { Math.Round((double)sr / n, 1), Math.Round((double)sg / n, 1), Math.Round((double)sb / n, 1) },
                        };
                    }
                }
                finally
                {
                    foreach (var pair in originals) pair.Key.sharedMaterials = pair.Value;
                }
                return result;
            }

            Color32[] Pixels(int width, int height, int msaa)
            {
                var desc = new RenderTextureDescriptor(width, height, RenderTextureFormat.ARGB32, 24) { msaaSamples = msaa, sRGB = true };
                var rt = RenderTexture.GetTemporary(desc);
                _camera.targetTexture = rt;
                _camera.aspect = (float)width / height;
#if UNITY_2023_2_OR_NEWER
                if (GraphicsSettings.currentRenderPipeline != null)
                {
                    var request = new RenderPipeline.StandardRequest { destination = rt };
                    if (RenderPipeline.SupportsRenderRequest(_camera, request)) RenderPipeline.SubmitRenderRequest(_camera, request);
                    else _camera.Render();
                }
                else
                {
                    _camera.Render();
                }
#else
                _camera.Render();
#endif
                var previous = RenderTexture.active;
                RenderTexture.active = rt;
                var tex = new Texture2D(width, height, TextureFormat.RGBA32, false, false);
                tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                tex.Apply();
                RenderTexture.active = previous;
                _camera.targetTexture = null;
                RenderTexture.ReleaseTemporary(rt);
                var pixels = tex.GetPixels32();
                UnityEngine.Object.DestroyImmediate(tex);
                for (var i = 0; i < pixels.Length; i++) pixels[i].a = 255;
                return pixels;
            }

            public void Dispose()
            {
                foreach (var go in _objects) UnityEngine.Object.DestroyImmediate(go);
                UnityEngine.Object.DestroyImmediate(_maskOn);
                UnityEngine.Object.DestroyImmediate(_maskOff);
                ShaderUtil.allowAsyncCompilation = _asyncWas;
            }
        }
    }
}
