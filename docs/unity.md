# FBX export and Unity

The avatars ship as GLB for the web. `python -m tak export fbx` converts them to FBX for game engines, with a sidecar file that the kit's Unity package (`unity/`) reads to set every avatar up as a Humanoid character with working materials and named blendshapes for lip-sync.

## Export

Requires Python 3.10+ and Blender 4.2 or newer (found as for the build: `--blender PATH`, the Studio setting `blender_path`, the `BLENDER` environment variable, `PATH`, the standard install folders).

```sh
python -m tak export fbx rowan              # one avatar
python -m tak export fbx --all              # every avatars/<slug>/<slug>.glb
python -m tak export fbx --all --out DIR    # somewhere else than build/export/
```

Each avatar is written to `build/export/<slug>/` (git-ignored):

| File | Content |
|---|---|
| `<slug>.fbx` | FBX 7.4 binary: the shipped GLB's meshes, 53-bone rig, all blendshapes, materials |
| `textures/` | The GLB's textures (bytes unchanged) and one derived Unity map per material with a roughness texture; the FBX references them by relative path |
| `<slug>.tak.json` | Sidecar: licence and credit, bone map, rest skeleton in Unity space, blendshapes per mesh, materials, texture roles |
| `LICENSE.md` | The avatar licence |

Progress is printed as JSON lines and a final `{"result": ...}` line (the same protocol as `build`). After writing the FBX the command re-imports it in Blender and checks bones (53, no leaf bones), shape keys per mesh, height, facing direction, object scales, materials and texture paths, and scans the FBX for absolute paths. Blender's output goes to `build/export/logs/`, outside the avatar folders, so each `build/export/<slug>/` can be zipped as it is. Options: `--no-verify`, `--blender PATH`, `--debug`.

### FBX settings

The export starts from the shipped GLB (not an MPFB rebuild), so the FBX has exactly the geometry, weights and blendshapes of the web avatar.

- **Scale:** "FBX All" scaling with unit scale applied. The file is in centimetres; Unity's *Convert Units* turns that into 1 unit = 1 m with scale 1 on every object.
- **Axes:** Y up, -Z forward. The avatar stands upright and faces +Z in Unity. Blender's *Apply Transform* option does not work for armatures, so the export rotates the armature and mesh data to Y-up and gives the armature object the opposite rotation; in the FBX the two cancel and Unity sees an identity root, with no 90-degree rotation on any object.
- **Armature:** `Armature` node with the `Root` bone under it, the 53 game_engine bones with their Blender orientations, no leaf (`_end`) bones, bind pose = the GLB's A-pose.
- **Meshes:** split normals, tangents (MikkTSpace), vertex colours (sRGB), shape keys with their normals. Every mesh keeps its exact blendshape names: `Body` has all 52 ARKit shapes and 15 visemes, `Eyes`, `Eyebrows`, `Eyelashes`, `Teeth` and `Tongue` carry the subsets that move them.
- **Materials:** one per slot (`skin`, `eyes`, `eyebrows`, `eyelashes`, `teeth`, `tongue`, `hair` and the clothing slots, for example `top`, `bottom`, `outfit`, `shoes`) with base colour (and alpha) and normal map, so any FBX reader shows a textured character. Roughness, alpha modes, sidedness and the reflectance of the glTF extensions are in the sidecar, because FBX has no slot for them.

### Sidecar

`<slug>.tak.json` (`"schema": "talking-avatar-kit/fbx-sidecar"`, version 1):

- `license`: `id`, `url`, `credit`, `attribution` (the credit line to show), `credits` (third-party garment and hair credits), `components` (per-part licences when the manifest lists them);
- `rig`: `bones` (53), `humanoid` (Unity human bone name to game_engine bone, 52 entries; `Root` is unmapped, the rig has no eye or jaw bones), `skeleton` (every transform in Unity space: local position, rotation as x, y, z, w, world position and bone end);
- `blendshapes`: `arkit`, `visemes`, `meshes` (names per mesh);
- `materials`: per slot the meshes using it, `alpha_mode` (`OPAQUE`, `MASK` with `alpha_cutoff`, `BLEND`), `double_sided`, `base_color_factor` (linear), `metallic`, `roughness`, `smoothness`, `specular_f0`, and texture files relative to the FBX folder;
- `textures`: every file with its roles, colour space and whether it is a normal map;
- `source`, `fbx`, `units`, `meshes`: provenance (GLB and FBX sha256, Blender and exporter versions, export settings), height and bounds, vertex and triangle counts.

## Import into Unity

The Unity package lives in `unity/` (UPM layout: `package.json`, `Runtime/`, `Editor/` with assembly definitions). Unity 2022.3 or newer; checked with Unity 6000.3.

1. Add the package, either
   - *Window > Package Manager > + > Add package from git URL*: `https://github.com/ghazanPK/talking-avatar-kit.git?path=unity`, or
   - *Add package from disk* and pick `unity/package.json` in a clone of the kit.
2. Copy an exported avatar folder (`build/export/<slug>/` with its `textures/`) anywhere under `Assets/`.

`python -m tak export fbx --all --unity PROJECT` does both for an existing project: it copies the package into `PROJECT/Packages/` and the avatars into `PROJECT/Assets/TalkingAvatarKit/Avatars/<slug>/`.

Any model with a `<name>.tak.json` next to it is set up by the package's importer:

- **Model:** scale factor 1 with *Convert Units* (1 unit = 1 m), blendshapes and their normals imported, normals imported, tangents calculated (MikkTSpace), no cameras, lights or animation.
- **Rig:** *Animation Type* Humanoid, *Create From This Model*, with a HumanDescription built from the sidecar map: hips, spine, chest, upper chest, neck, head, shoulders, arms, hands, legs, feet, toes and all 30 finger bones (52 of Unity's 55 human bones; eyes and jaw have no bones on this rig).
- **A-pose:** Mecanim treats the pose stored in the avatar description as the character's T-pose. The importer derives one from the A-pose bind (like *Enforce T-Pose*): upper arms, forearms, hands (aimed at the middle finger) and the four fingers point straight out to the sides, thighs and shins straight down; the thumbs and the rest of the skeleton keep their rest rotations. The mesh bind pose is unchanged; only the avatar's reference pose differs, so humanoid animations from other characters retarget without lowered arms.
- **Materials:** built from the sidecar when the model imports. With the Universal Render Pipeline active they use *Universal Render Pipeline/Lit*, otherwise *Standard*. Skin, hair, eyebrows, eyelashes, teeth and tongue use the specular workflow (`Standard (Specular setup)` in the built-in pipeline) with the glTF reflectance, because Unity's metallic workflow fixes it at 4% and makes skin look glossy; the derived map in `textures/` holds the reflectance (RGB) and smoothness (A). `MASK` becomes alpha clipping with the cutoff, `BLEND` becomes transparent (URP) or *Fade* (Standard), `double_sided` turns culling off in URP. Switching the render pipeline re-imports the avatars. Materials stay inside the FBX asset; use *Materials > Extract Materials* in the model's Inspector to edit them.
- **Textures:** normal maps are imported as *Normal map*, roughness and derived maps as linear or sRGB as listed in the sidecar.
- **Prefab components:** `AvatarBlendShapes` (lip-sync helper) and `TalkingAvatarInfo` (name, licence, attribution for your credits screen) are added to the model's root.

To configure an avatar by hand instead, write `tak:manual` into the model importer's *User Data* (Inspector in Debug mode); the package then leaves that file alone. *Tools > Talking Avatar Kit > Reimport Avatars* re-imports every kit avatar, *Validate Avatars* runs the checks below and writes a report and preview images to `Temp/TalkingAvatarKit/`.

## Lip-sync helper

`TalkingAvatarKit.AvatarBlendShapes` finds every skinned mesh under the avatar and drives a blendshape by name on all meshes that have it, so a viseme opens the jaw on the body, teeth and tongue together and a blink closes the lashes with the lids. Weights are 0 to 1.

```csharp
using TalkingAvatarKit;
using UnityEngine;

public class SayAh : MonoBehaviour
{
    AvatarBlendShapes face;

    void Start() => face = GetComponent<AvatarBlendShapes>();

    void Update()
    {
        face.SetViseme(Viseme.aa, Mathf.PingPong(Time.time * 2f, 1f));
        face.SetWeight("eyeBlinkLeft", Time.time % 4f < 0.15f ? 1f : 0f);
    }
}
```

Other members: `SetVisemes(weights)` (15 values in `Viseme` order), `GetWeight(name)`, `Find(name)` (every renderer and blendshape index, for your own animation code), `AvatarBlendShapes.IndexOf(renderer, name)`, `Has(name)`, `Names`, `Missing(names)`, `ResetAll()` and `Rebuild()` (after swapping meshes). `FaceShapes.Arkit` and `FaceShapes.Visemes` list the 52 ARKit and 15 viseme names.

## Batch check

```sh
python -m tak export fbx --all --unity-check                     # export, then check (built-in and URP)
python -m tak export fbx --all --skip-export --unity-check --pipeline urp
```

The check creates a scratch Unity project in `build/unity-check/project/` (reused on later runs), embeds the package, copies the exports and runs Unity with `-batchmode -quit -executeMethod TalkingAvatarKit.Editor.AvatarCheck.RunBatch`. For each render pipeline (`--pipeline builtin|urp|both`, default both; URP is generated from the package bundled with the editor) it re-imports every avatar and checks:

- the model imports as Humanoid and the avatar is valid and human;
- all 52 mapped bones resolve to the sidecar's bones and every required Mecanim bone is present;
- each mesh has exactly the sidecar's blendshape names, and all 52 ARKit shapes and 15 visemes are found;
- every renderer has its materials on the expected shader with base colour, normal and smoothness maps assigned, and textures are imported with the right type and colour space;
- each material property matches the sidecar: the exact texture file in each slot (a normal map is never the base map), base colour, workflow (specular with a reflectance between 0.005 and 0.1, or metallic), smoothness (no mirror-like values), alpha and normal-map keywords, culling;
- the root and `Armature` have no rotation and scale 1, the height matches the GLB, feet are at y = 0, the avatar faces +Z with its left hand on -X;
- the imported rest skeleton matches the sidecar (positions and rotations);
- in the avatar's reference pose the arms, hands and legs lie on the T-pose axes;
- preview renders are not empty, have no error-shader pixels and are stable: each shot is rendered once to warm up (with synchronous shader compilation), saved, and rendered again, and the saved frame must equal the next one;
- with both pipelines, the mean colour of every material's region in the full-body and face previews (found with a mask render per material) differs by at most 40 of 255 between built-in and URP. Lighting models differ by under 15 for the shipped avatars; a wrong texture, a broken shader variant or a mirror-like material moves a region by far more.

It writes `build/unity-check/report.json`, `unity.log` and `previews/<slug>_<pipeline>_{full,face,face_aa_blink,tpose}.png` (full body, face, face with the `viseme_aa` viseme and a left blink, and the T-pose reference), prints the summary in the final JSON line and exits non-zero when a check fails.

Unity is found through `--unity-exe PATH`, the `UNITY` environment variable, the user setting `unity_path`, the Unity Hub install folders (`%ProgramFiles%\Unity\Hub\Editor\<version>\Editor\Unity.exe` on Windows, `/Applications/Unity/Hub/Editor/<version>/Unity.app` on macOS, `~/Unity/Hub/Editor/<version>/Editor/Unity` on Linux) and finally `PATH`. Under WSL a Windows `Unity.exe` works. Batch mode needs an activated licence (a Unity Personal licence activated in Unity Hub works); when the editor cannot start, the result names the licensing or compile error found in the log.

`tests/test_export_tools.py` runs a real export and a Unity check of Rowan when `BLENDER` and `UNITY` are set.

## Known limits

- **Materials are approximations of the glTF look.** Unity Lit has no sheen, so the skin and hair sheen is dropped; the eyes' clearcoat becomes plain smoothness; the teeth and tongue darkening toward the throat is stored as vertex colour, which Lit ignores, so the mouth interior is brighter than on the web. The built-in *Standard* shader has no double-sided mode, so the inside of garments at cuffs and collars is culled there (URP renders both sides).
- **Hair cards** are alpha-tested (`MASK`), so dense card hair such as Amina's curls looks coarse at close range in both pipelines.
- **HDRP** is not handled; with HDRP active the importer falls back to *Standard* materials (convert them with HDRP's material upgrader).
- **T-pose reference:** thumbs, clavicles and feet keep their rest rotations; adjust them in the Avatar configuration if a retargeted animation needs it.
- **No eye or jaw bones:** eye gaze and jaw opening are blendshapes (`eyeLook*`, `jawOpen`, visemes); Mecanim's eye and jaw muscles have no effect.
- **Unity owns the converted materials:** they are rebuilt on every import from the sidecar; extract them to keep manual edits.
- **Other engines:** the FBX opens in other FBX readers (textures by relative path, 1 m units, Y up), but only Unity has an importer in this kit.
