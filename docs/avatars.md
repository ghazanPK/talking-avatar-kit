# Avatars: setup, build and checks

The kit ships two prepared avatars, **Rowan** and **Mira**, in `avatars/<slug>/`:

| File | Content |
|---|---|
| `spec.json` | Character specification: MakeHuman body values, skin, eyes, hair, clothing, material settings, checks |
| `<slug>.glb` | glTF 2.0 binary for three.js and other glTF viewers |
| `manifest.json` | Licence and credit, generator versions, bone names, morph target names, material slots, sha256, size |
| `preview.png` | Full-body preview render |

Everything in `avatars/` is CC BY 4.0, see [../avatars/LICENSE.md](../avatars/LICENSE.md). You only need the steps below to rebuild the avatars or to make new ones from a spec.

## What a built avatar contains

- **Skeleton:** MPFB `game_engine` rig, 53 bones (`Root`, `pelvis`, `spine_01..03`, `neck_01`, `head`, clavicles, arms, all finger joints, legs). Rest pose: A-pose, metres, +Y up, the character faces +Z.
- **Skin weights:** at most four influences per vertex, normalised. Corrected around the thumb base, thumb joints, knuckles, wrists, elbows and shoulders, and on the outfit around the shoulders and elbows (see *Corrections* below).
- **Face:** the 52 ARKit blendshapes and the 15 viseme targets (`viseme_sil`, `viseme_PP`, ..., `viseme_U`) on the `Body` mesh. The same targets are carried by the meshes they move: `Eyes` (eye look), `Eyebrows`, `Eyelashes` (blinks, squints, brows), `Teeth` and `Tongue` (jaw, visemes, `tongueOut`). Drive a target by name on every mesh that has it. All default weights are zero (neutral face).
- **Meshes and material slots:** `Body` (`skin`), `Eyes` (`eyes`), `Eyebrows` (`eyebrows`), `Eyelashes` (`eyelashes`), `Teeth` (`teeth`), `Tongue` (`tongue`), `Hair` (`hair`), and one mesh per clothing slot (`Outfit`/`outfit`, `Shoes`/`shoes`).
- **Materials:** glTF metallic-roughness with extensions three.js supports:
  - skin: albedo texture (2048 px), a tiled pore/crease detail normal map (`KHR_texture_transform`), lowered specular (`KHR_materials_specular`, `KHR_materials_ior` 1.4) and a faint sheen (`KHR_materials_sheen`) instead of a plastic highlight;
  - eyes: calmed sclera, brown iris colour corrected for readability, glossy clearcoat for the wet highlight (`KHR_materials_clearcoat`);
  - teeth and tongue: dimmer albedo and a vertex-colour occlusion (`COLOR_0`) that darkens toward the throat, so they do not glow inside the mouth;
  - eyebrows and eyelashes: alpha blended (`BLEND`), with colour bled into transparent texels to avoid light fringes; hair: alpha tested (`MASK`, cutoff 0.4) and double-sided;
  - clothing: colour from the spec, the garment's normal map, double-sided.
- **Size:** about 5 MB per avatar (textures: skin 2048 px, others 1024 px or less; JPEG where no alpha is needed; sparse morph targets).

## Requirements

- Python 3.10 or newer (standard library only).
- Blender 4.2 or newer (the shipped avatars were built with 5.2.2 LTS).
- About 1 GB of free disk space for the MPFB profile and the asset packs.

The pipeline finds Blender through, in order: `--blender PATH`, the Studio setting `blender_path`, the `BLENDER` environment variable, `PATH`, and the standard install folders. Under WSL a Windows `blender.exe` works; file arguments are converted to Windows paths automatically.

## Setup

```sh
python -m tak setup
```

This installs, into the git-ignored `.tak/blender-user/` Blender profile (your normal Blender configuration is not touched):

- MPFB 2.0.17 from its official GitHub release archive, as a Blender extension;
- the MakeHuman CC0 packs *MakeHuman system assets*, *Visemes 02* and *Faceunits 01* from makehumancommunity.org.

Archives are cached in `.tak/downloads/`, their sha256 values are recorded in `.tak/install.json`, and a background Blender run then enables MPFB and lists the installed packs. Running setup again skips anything already installed with the same archive.

Options:

- `--packs-dir DIR`: use archives you already downloaded (`makehuman_system_assets_cc0.zip`, `visemes02.zip`, `faceunits01.zip`, and optionally `mpfb2-v2.0.17.zip`) instead of downloading them. The Studio setting `packs_dir` sets a default.
- `--blender PATH`: the Blender executable for the verification run.
- `--no-verify`: skip the Blender verification.

The Studio setting `mpfb_profile_dir` points the pipeline at another Blender user folder that already contains MPFB and the packs.

## Check

```sh
python -m tak check          # JSON: Python, Blender (path, version), MPFB, packs, profile, "ready"
python -m tak check --deep   # also starts Blender and enables MPFB
```

## Build

```sh
python -m tak build rowan
python -m tak build --all
```

For each avatar the build runs `blender/build_avatar.py` in background Blender, validates the result and, only when validation passes, copies `<slug>.glb` and `preview.png` into `avatars/<slug>/` and writes `manifest.json`. Work files and logs stay in `.tak/work/` and `.tak/logs/`. A build takes well under a minute per avatar.

Progress is printed as JSON lines, one object per line, followed by a final result line; the Studio's job log shows the same lines:

```json
{"stage": "face", "message": "loading ARKit and viseme targets", "progress": 0.28}
{"stage": "publish", "message": "wrote avatars/rowan/rowan.glb (4820252 bytes) and manifest.json", "progress": 1.0}
{"result": {"ok": true, "avatars": {"rowan": {"ok": true, "glb": "avatars/rowan/rowan.glb", "...": "..."}}}}
```

The exit code is 0 when every avatar built and validated. Options: `--blender PATH`, `--no-validate`, `--no-preview`, `--keep-blend` (keeps the working `.blend` in `.tak/work/<slug>/`), `--debug` (tracebacks on stderr).

## Validate

```sh
python -m tak.pipeline validate --all                 # structure checks + Blender re-import
python -m tak.pipeline validate rowan --static-only   # no Blender needed
```

The structure checks read the GLB directly: one skin with the 53 game_engine joints, all 67 face targets on `Body` and only known names elsewhere, zero default morph weights, every mesh skinned with normalised weights (at most four influences), the expected material slots and alpha modes, embedded textures, bind-pose height within the spec's `checks.height_m`, and file size within `checks.max_bytes`. The re-import check loads the GLB in background Blender (`blender/validate.py`), checks bones, shape keys, materials, height and that every vertex has a bone influence, and rotates the arms to catch stray vertices. A failed check gives a non-zero exit code.

## Pose and face check renders

`blender/pose_check.py` renders close-ups of a GLB in extreme poses (arms raised and forward, elbow at 120 degrees, wrist flexion and extension, fist, open hand, pointing, thumb opposition) and face states (neutral, jaw open, a viseme, blink, smile, eye look, raised brows, eye and mouth close-ups, back and side views of the hair):

```sh
blender -b --factory-startup --python blender/pose_check.py -- \
    --glb avatars/rowan/rowan.glb --out-dir build/pose-check/rowan [--only fist,closeup_eyes] [--size 640]
```

Rotation axes are derived from the rest skeleton, so the same script works for any avatar with this rig. Use it to compare a change against the previous GLB.

## Writing a spec

```json
{
  "schema_version": 1,
  "slug": "rowan",
  "name": "Rowan",
  "description": "Middle-aged African man in a slate work suit",
  "body": {"gender": 1.0, "age": 0.73, "muscle": 0.57, "weight": 0.58, "height": 0.62,
           "proportions": 0.47, "cupsize": 0.5, "firmness": 0.5,
           "race": {"african": 1.0, "asian": 0.0, "caucasian": 0.0}},
  "rig": "game_engine",
  "skin": {"material": "middleage_african_male", "roughness": 0.58, "specular": 0.36,
           "detail_normal_strength": 0.3, "tint": [1.0, 1.0, 1.0]},
  "eyes": {"mesh": "high-poly", "material": "brown"},
  "eyebrows": {"asset": "eyebrow004"},
  "eyelashes": {"asset": "eyelashes01"},
  "teeth": {"asset": "teeth_shape01"},
  "tongue": {"asset": "tongue01"},
  "hair": {"asset": "short04", "roughness": 0.62},
  "clothes": [
    {"asset": "male_worksuit01", "slot": "outfit", "base_color": [0.17, 0.23, 0.29], "roughness": 0.78, "keep_texture": false},
    {"asset": "shoes03", "slot": "shoes", "roughness": 0.45}
  ],
  "face": {"arkit": true, "visemes": "meta"},
  "textures": {"default_max": 1024, "skin_max": 2048, "eyes_max": 512},
  "checks": {"height_m": [1.85, 2.05], "max_bytes": 10000000}
}
```

- `body`: MakeHuman macro values between 0 and 1.
- Asset names are MakeHuman/MPFB asset names (folder names in the installed packs), never paths: skins (`young_asian_female`, ...), eyes `high-poly` or `low-poly` with an eye material (`brown`, `blue`, `green`, ...), eyebrows `eyebrow001`-`eyebrow012`, eyelashes `eyelashes01`-`04`, teeth `teeth_base`, `teeth_shape01`-`05`, hair (`short01`-`04`, `bob01`, `ponytail01`, `long01`, `braid01`, `afro01`, ...), clothes and shoes.
- `skin.tint`: optional albedo multipliers; `skin.specular`: Principled specular level (0.5 is the glTF default).
- `clothes[].base_color`: linear RGB (the glTF `baseColorFactor`). With `keep_texture: false` the garment uses this colour and keeps its normal map; otherwise the colour multiplies the garment texture. Slots: `outfit`, `top`, `bottom`, `shoes`, `hat`, `accessory`, each at most once.
- `checks`: the validator's height range (bind pose, shoes to hair) and size limit.

Put a new spec in `avatars/<slug>/spec.json` and run `python -m tak build <slug>`. The `slug` must match the folder name.

## Corrections applied by the build

- **Skin weights** (`blender/tak_blender/rigfix.py`): before clothes are fitted, the hand-off between the bones of each joint is spread over a wider band with Laplacian smoothing restricted to those bones, inside a sphere around the joint: thumb base (hand, thumb_01, thumb_02), thumb middle joint, knuckles (hand, finger_01, finger_02), wrist, elbow and shoulder (clavicle, upperarm, spine_03). Clothes then inherit the corrected weights; the outfit is smoothed again around shoulders and elbows so raised arms do not tear the armpit into fins.
- **Garment overlap**: sock and shoe vertices that poke through trouser legs are pushed under them.
- **Face targets on parts**: MakeHuman face targets move only the body; the build maps each target onto eyes, brows, lashes, teeth and tongue through their MakeHuman fitting data, so lashes close with a blink, the eyes turn, and lower teeth and tongue follow the jaw.
- **Eyes**: the outer eye shell of the high-poly MakeHuman eyes (meant for alpha blending, opaque in glTF) is removed; the eyeball's clearcoat provides the highlight.
