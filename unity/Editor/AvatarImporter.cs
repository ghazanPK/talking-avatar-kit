using System.IO;
using UnityEditor;
using UnityEditor.AssetImporters;
using UnityEngine;

namespace TalkingAvatarKit.Editor
{
    /// <summary>
    /// Import settings for talking-avatar-kit FBX files: any model with a <c>&lt;name&gt;.tak.json</c>
    /// sidecar next to it. Sets Humanoid with the game_engine bone map and a T-pose reference,
    /// keeps blendshapes (with their normals), uses the file's metre scale, builds URP Lit or
    /// Standard materials from the textures, and adds the lip-sync helper to the prefab.
    ///
    /// To manage an avatar's import settings by hand, put <c>tak:manual</c> in the model
    /// importer's User Data field (Inspector, Debug mode); the importer then leaves it alone.
    /// </summary>
    public sealed class AvatarImporter : AssetPostprocessor
    {
        const int Version = 4;
        public const string ManualFlag = "tak:manual";

        public override uint GetVersion() => Version;

        static bool Manual(AssetImporter importer) =>
            importer != null && importer.userData != null && importer.userData.Contains(ManualFlag);

        void OnPreprocessModel()
        {
            if (!(assetImporter is ModelImporter importer) || Manual(importer)) return;
            var sidecarPath = AvatarSidecar.PathFor(assetPath);
            context.DependsOnSourceAsset(sidecarPath);
            var sidecar = Load();
            if (sidecar == null) return;

            importer.globalScale = 1f;
            importer.useFileScale = true; // FBX in centimetres -> 1 unit = 1 m, scale 1
            importer.bakeAxisConversion = false; // the FBX is already Y-up with the space transform baked
            importer.importBlendShapes = true;
            importer.importNormals = ModelImporterNormals.Import;
            importer.importBlendShapeNormals = ModelImporterNormals.Import;
            importer.importTangents = ModelImporterTangents.CalculateMikk;
            importer.importVisibility = false;
            importer.importCameras = false;
            importer.importLights = false;
            importer.importAnimation = false;
            importer.optimizeGameObjects = false;
            importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
            importer.materialLocation = ModelImporterMaterialLocation.InPrefab;
            importer.animationType = ModelImporterAnimationType.Human;
            importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
            importer.humanDescription = HumanoidSetup.Build(sidecar, Path.GetFileNameWithoutExtension(assetPath));
        }

        void OnPreprocessTexture()
        {
            if (!(assetImporter is TextureImporter importer) || Manual(importer)) return;
            var file = Path.GetFileName(assetPath);
            foreach (var sidecar in AvatarSidecar.ForTexture(assetPath))
            {
                var key = Path.GetFileName(Path.GetDirectoryName(assetPath)) + "/" + file;
                if (!sidecar.Textures.TryGetValue(key, out var info)) continue;
                context.DependsOnSourceAsset(sidecar.Path);
                var normal = AvatarSidecar.Bool(info, "normal_map");
                var linear = AvatarSidecar.Str(info, "color_space") == "linear";
                importer.textureType = normal ? TextureImporterType.NormalMap : TextureImporterType.Default;
                importer.sRGBTexture = !linear;
                importer.mipmapEnabled = true;
                importer.maxTextureSize = Mathf.Max(importer.maxTextureSize, 4096);
                if (!normal && !linear && file.EndsWith(".png")) importer.alphaIsTransparency = true;
                return;
            }
        }

        void OnPreprocessMaterialDescription(MaterialDescription description, Material material, AnimationClip[] clips)
        {
            if (Manual(assetImporter)) return;
            var sidecar = Load();
            if (sidecar == null || !sidecar.Materials.TryGetValue(description.materialName, out var spec)) return;
            context.DependsOnCustomDependency(PipelineDependency.Name);
            MaterialSetup.Apply(material, spec, relative =>
            {
                var path = sidecar.AssetPath(relative);
                if (!File.Exists(path)) return null;
                context.DependsOnArtifact(path);
                return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            });
        }

        void OnPostprocessModel(GameObject root)
        {
            if (Manual(assetImporter)) return;
            var sidecar = Load();
            if (sidecar == null) return;
            if (root.GetComponent<AvatarBlendShapes>() == null) root.AddComponent<AvatarBlendShapes>();
            var info = root.GetComponent<TalkingAvatarInfo>() ?? root.AddComponent<TalkingAvatarInfo>();
            info.slug = sidecar.Slug;
            info.displayName = sidecar.Name;
            info.licenseId = sidecar.LicenseId;
            info.licenseUrl = sidecar.LicenseUrl;
            info.attribution = sidecar.Attribution;
        }

        AvatarSidecar Load()
        {
            try
            {
                return AvatarSidecar.ForModel(assetPath);
            }
            catch (System.Exception e)
            {
                Debug.LogError($"Talking Avatar Kit: cannot read the sidecar of {assetPath}: {e.Message}");
                return null;
            }
        }
    }

    /// <summary>
    /// Avatar materials depend on the active render pipeline (URP Lit or Standard); switching the
    /// pipeline in Graphics settings re-imports them.
    /// </summary>
    [InitializeOnLoad]
    public static class PipelineDependency
    {
        public const string Name = "talking-avatar-kit/render-pipeline";
        static string _current;

        static PipelineDependency()
        {
            Register(refresh: false);
            EditorApplication.update += Poll;
        }

        static void Poll()
        {
            if (MaterialSetup.ShaderName() != _current) Register(refresh: true);
        }

        /// <summary>Record the current pipeline; with <paramref name="refresh"/> re-import affected avatars.</summary>
        public static void Register(bool refresh)
        {
            _current = MaterialSetup.ShaderName();
            AssetDatabase.RegisterCustomDependency(Name, Hash128.Compute(_current));
            if (refresh) AssetDatabase.Refresh();
        }
    }
}
