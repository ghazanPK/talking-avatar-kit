using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace TalkingAvatarKit.Editor
{
    /// <summary>
    /// Turns a sidecar material entry (glTF metallic-roughness values and the exported textures)
    /// into a URP Lit material when the Universal Render Pipeline is active, otherwise Standard.
    /// </summary>
    public static class MaterialSetup
    {
        public const string UrpLit = "Universal Render Pipeline/Lit";
        public const string Standard = "Standard";

        public enum Pipeline { BuiltIn, Universal, Other }

        public static Pipeline Current()
        {
            var asset = GraphicsSettings.currentRenderPipeline;
            if (asset == null) return Pipeline.BuiltIn;
            return asset.GetType().Name.Contains("Universal") ? Pipeline.Universal : Pipeline.Other;
        }

        public const string StandardSpecular = "Standard (Specular setup)";

        /// <summary>Name of the shader family the importer uses in the current pipeline (URP Lit or Standard).</summary>
        public static string ShaderName()
        {
            if (Current() == Pipeline.Universal && Shader.Find(UrpLit) != null) return UrpLit;
            return Standard;
        }

        /// <summary>
        /// Dielectrics exported with KHR_materials_ior/specular carry <c>specular_f0</c> and use the
        /// specular workflow (Unity's metallic workflow fixes the reflectance at 0.04).
        /// </summary>
        public static bool UsesSpecular(Dictionary<string, object> spec) => spec.ContainsKey("specular_f0");

        /// <summary>Exact shader name for one material entry.</summary>
        public static string ShaderFor(Dictionary<string, object> spec)
        {
            var family = ShaderName();
            return family == Standard && UsesSpecular(spec) ? StandardSpecular : family;
        }

        public static void Apply(Material m, Dictionary<string, object> spec, Func<string, Texture2D> loadTexture)
        {
            var shaderName = ShaderFor(spec);
            var shader = Shader.Find(shaderName);
            if (shader == null)
            {
                Debug.LogWarning($"Talking Avatar Kit: shader '{shaderName}' not found; material {m.name} left as imported.");
                return;
            }
            if (Current() == Pipeline.Other)
                Debug.LogWarning("Talking Avatar Kit: the active render pipeline is neither URP nor built-in; using Standard materials.");
            m.shader = shader;

            Texture2D Tex(string key)
            {
                var entry = AvatarSidecar.Obj(spec, key);
                var file = AvatarSidecar.Str(entry, "file");
                return string.IsNullOrEmpty(file) ? null : loadTexture(file);
            }

            var baseMap = Tex("base_color");
            var normal = Tex("normal");
            var specular = UsesSpecular(spec);
            var ms = Tex(specular ? "specular_smoothness" : "metallic_smoothness");
            var f0 = Mathf.LinearToGammaSpace((float)AvatarSidecar.Num(spec, "specular_f0", 0.04));
            var specColor = new Color(f0, f0, f0, 1f);
            // glTF factors are linear; Unity colour properties are given in sRGB (gamma) space.
            var color = AvatarSidecar.ColorOf(spec, "base_color_factor", Color.white);
            var gammaColor = new Color(Mathf.LinearToGammaSpace(color.r), Mathf.LinearToGammaSpace(color.g),
                Mathf.LinearToGammaSpace(color.b), color.a);
            var metallic = (float)AvatarSidecar.Num(spec, "metallic", 0);
            var smoothness = (float)AvatarSidecar.Num(spec, "smoothness", 0.5);
            var normalScale = (float)AvatarSidecar.Num(AvatarSidecar.Obj(spec, "normal"), "scale", 1);
            var alphaMode = AvatarSidecar.Str(spec, "alpha_mode") ?? "OPAQUE";
            var cutoff = (float)AvatarSidecar.Num(spec, "alpha_cutoff", 0.5);
            var doubleSided = AvatarSidecar.Bool(spec, "double_sided");

            if (shaderName == UrpLit)
                SetupUrp(m, baseMap, gammaColor, normal, normalScale, ms, metallic, smoothness, specular, specColor,
                    alphaMode, cutoff, doubleSided);
            else
                SetupStandard(m, baseMap, gammaColor, normal, normalScale, ms, metallic, smoothness, specular, specColor,
                    alphaMode, cutoff);
            m.doubleSidedGI = doubleSided;
        }

        static void SetupUrp(Material m, Texture2D baseMap, Color color, Texture2D normal, float normalScale, Texture2D ms,
            float metallic, float smoothness, bool specular, Color specColor, string alphaMode, float cutoff, bool doubleSided)
        {
            m.SetFloat("_WorkflowMode", specular ? 0f : 1f);
            if (specular) m.EnableKeyword("_SPECULAR_SETUP");
            if (baseMap != null) { m.SetTexture("_BaseMap", baseMap); m.SetTexture("_MainTex", baseMap); }
            m.SetColor("_BaseColor", color);
            m.SetColor("_Color", color);
            if (normal != null)
            {
                m.SetTexture("_BumpMap", normal);
                m.SetFloat("_BumpScale", normalScale);
                m.EnableKeyword("_NORMALMAP");
            }
            m.SetFloat("_Metallic", metallic);
            m.SetColor("_SpecColor", specColor);
            m.SetFloat("_SmoothnessTextureChannel", 0f);
            if (ms != null)
            {
                m.SetTexture(specular ? "_SpecGlossMap" : "_MetallicGlossMap", ms);
                m.SetFloat("_Smoothness", 1f);
                m.EnableKeyword("_METALLICSPECGLOSSMAP");
            }
            else
            {
                m.SetFloat("_Smoothness", smoothness);
            }
            m.SetFloat("_Cull", doubleSided ? (float)CullMode.Off : (float)CullMode.Back);
            m.SetFloat("_AlphaToMask", 0f);
            switch (alphaMode)
            {
                case "BLEND":
                    m.SetFloat("_Surface", 1f);
                    m.SetFloat("_Blend", 0f);
                    m.SetFloat("_AlphaClip", 0f);
                    m.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
                    m.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
                    m.SetFloat("_SrcBlendAlpha", (float)BlendMode.One);
                    m.SetFloat("_DstBlendAlpha", (float)BlendMode.OneMinusSrcAlpha);
                    m.SetFloat("_ZWrite", 0f);
                    m.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
                    m.SetOverrideTag("RenderType", "Transparent");
                    m.SetShaderPassEnabled("DepthOnly", false);
                    m.renderQueue = (int)RenderQueue.Transparent;
                    break;
                case "MASK":
                    m.SetFloat("_Surface", 0f);
                    m.SetFloat("_AlphaClip", 1f);
                    m.SetFloat("_Cutoff", cutoff);
                    m.SetFloat("_SrcBlend", (float)BlendMode.One);
                    m.SetFloat("_DstBlend", (float)BlendMode.Zero);
                    m.SetFloat("_ZWrite", 1f);
                    m.EnableKeyword("_ALPHATEST_ON");
                    m.SetOverrideTag("RenderType", "TransparentCutout");
                    m.renderQueue = (int)RenderQueue.AlphaTest;
                    break;
                default:
                    m.SetFloat("_Surface", 0f);
                    m.SetFloat("_AlphaClip", 0f);
                    m.SetFloat("_SrcBlend", (float)BlendMode.One);
                    m.SetFloat("_DstBlend", (float)BlendMode.Zero);
                    m.SetFloat("_ZWrite", 1f);
                    m.SetOverrideTag("RenderType", "Opaque");
                    m.renderQueue = (int)RenderQueue.Geometry;
                    break;
            }
        }

        static void SetupStandard(Material m, Texture2D baseMap, Color color, Texture2D normal, float normalScale, Texture2D ms,
            float metallic, float smoothness, bool specular, Color specColor, string alphaMode, float cutoff)
        {
            if (baseMap != null) m.SetTexture("_MainTex", baseMap);
            m.SetColor("_Color", color);
            if (normal != null)
            {
                m.SetTexture("_BumpMap", normal);
                m.SetFloat("_BumpScale", normalScale);
                m.EnableKeyword("_NORMALMAP");
            }
            m.SetFloat("_Metallic", metallic);
            m.SetColor("_SpecColor", specColor);
            m.SetFloat("_SmoothnessTextureChannel", 0f);
            m.SetFloat("_Glossiness", smoothness);
            if (ms != null)
            {
                m.SetTexture(specular ? "_SpecGlossMap" : "_MetallicGlossMap", ms);
                m.SetFloat("_GlossMapScale", 1f);
                m.EnableKeyword(specular ? "_SPECGLOSSMAP" : "_METALLICGLOSSMAP");
            }
            switch (alphaMode)
            {
                case "BLEND": // Standard "Fade"
                    m.SetFloat("_Mode", 2f);
                    m.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
                    m.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
                    m.SetFloat("_ZWrite", 0f);
                    m.EnableKeyword("_ALPHABLEND_ON");
                    m.SetOverrideTag("RenderType", "Transparent");
                    m.renderQueue = (int)RenderQueue.Transparent;
                    break;
                case "MASK":
                    m.SetFloat("_Mode", 1f);
                    m.SetFloat("_Cutoff", cutoff);
                    m.SetFloat("_SrcBlend", (float)BlendMode.One);
                    m.SetFloat("_DstBlend", (float)BlendMode.Zero);
                    m.SetFloat("_ZWrite", 1f);
                    m.EnableKeyword("_ALPHATEST_ON");
                    m.SetOverrideTag("RenderType", "TransparentCutout");
                    m.renderQueue = (int)RenderQueue.AlphaTest;
                    break;
                default:
                    m.SetFloat("_Mode", 0f);
                    m.SetOverrideTag("RenderType", "Opaque");
                    m.renderQueue = -1;
                    break;
            }
        }
    }
}
