# Avatars: setup, build and checks

The kit ships five prepared avatars, **Rowan**, **Mira**, **Amina**, **Elena** and **Min-jun**, in `avatars/<slug>/`. Each is reproduced by `python -m tak build <slug>` from its `spec.json` (its build recipe):

| File | Content |
|---|---|
| `spec.json` | Build recipe: MakeHuman body values, skin, eyes, face parts, hair, garments per slot with their packs and credits, material look, checks |
| `<slug>.glb` | glTF 2.0 binary for three.js and other glTF viewers |
| `manifest.json` | Licence and credit, generator versions, bone names, morph target names, material slots, sha256, size |
| `preview.png` | Full-body preview render |

Everything in `avatars/` is CC BY 4.0, see [../avatars/LICENSE.md](../avatars/LICENSE.md); Amina's and Elena's CC BY community garments and hair keep their own credit lines (in each manifest). You only need the steps below to rebuild the avatars or to make new ones from a spec.

| Avatar | Look | Body (gender, age, height macro) | Outfit (slot: asset, pack) | Hair |
|---|---|---|---|---|
| Rowan | kit (Mindfront skin, baked detail maps) | 1.0, 0.73, 0.62; 1.989 m | shoes: `shoes03`; bottom: `cortu_cargo_pants` (pants01, CC0); top: `namuhekam_male_polo_shirt` (shirts01, CC0), recoloured green | `short04` |
| Mira | kit (baked detail maps, tint) | 0.0, 0.40, 0.50; 1.413 m | shoes: `shoes04`; outfit: `toigo_female_double-breasted_suit` (suits01, CC0) | `ponytail01` |
| Amina | mpfb | 0.0, 0.50, 0.56; 1.770 m | shoes: `shoes04`; outfit: `mindfront_f_dress_09` (dress03, CC BY) | `punkduck_alpha7_curly` (hair03, CC BY) |
| Elena | mpfb | 0.0, 0.92, 0.48; 1.646 m | shoes: `shoes06`; bottom: `punkduck_skirt_native_american_fashion` (skirts02, CC BY); top: `mindfront_lusekofta` (shirts02, CC BY) | `elvs_50s_updo` (hair02, CC BY), recoloured silver |
| Min-jun | mpfb | 1.0, 0.75, 0.53; 1.652 m | shoes: `shoes01`; outfit: `male_casualsuit05` | `short03` |

All five use the eye treatment below; the full body values, face parts and material settings are in each spec.

## What a built avatar contains

- **Skeleton:** MPFB `game_engine` rig, 53 bones (`Root`, `pelvis`, `spine_01..03`, `neck_01`, `head`, clavicles, arms, all finger joints, legs). Rest pose: A-pose, metres, +Y up, the character faces +Z.
- **Skin weights:** at most four influences per vertex, normalised. Corrected around the thumb base, thumb joints, knuckles, wrists, elbows and shoulders, and on the outfit around the shoulders and elbows (see *Corrections* below).
- **Face:** the 52 ARKit blendshapes and the 15 viseme targets (`viseme_sil`, `viseme_PP`, ..., `viseme_U`) on the `Body` mesh. The same targets are carried by the meshes they move: `Eyes` (eye look), `Eyebrows`, `Eyelashes` (blinks, squints, brows), `Teeth` and `Tongue` (jaw, visemes, `tongueOut`). Drive a target by name on every mesh that has it. All default weights are zero (neutral face).
- **Meshes and material slots:** `Body` (`skin`), `Eyes` (`eyes`), `Eyebrows` (`eyebrows`), `Eyelashes` (`eyelashes`), `Teeth` (`teeth`), `Tongue` (`tongue`), `Hair` (`hair`), and one mesh per clothing slot (`Outfit`/`outfit` or `Top`/`top` and `Bottom`/`bottom`, `Shoes`/`shoes`).
- **Materials:** glTF metallic-roughness with extensions three.js supports:
  - skin: baked albedo, normal and roughness maps (see *Skin maps* below: the MakeHuman skin texture with padded UV islands, colour variation and region tints; the skin's own normal map plus region-dependent pore and wrinkle detail; region-dependent roughness), lowered specular (`KHR_materials_specular`, `KHR_materials_ior` 1.4) and a faint sheen (`KHR_materials_sheen`, warm on Mira for a softer edge) instead of a plastic highlight;
  - eyes: calmed sclera, brown iris colour corrected for readability, glossy clearcoat for the wet highlight (`KHR_materials_clearcoat`);
  - teeth and tongue: dimmer albedo and a vertex-colour occlusion (`COLOR_0`) that darkens toward the throat, so they do not glow inside the mouth;
  - eyebrows and eyelashes: alpha blended (`BLEND`), with colour bled into transparent texels to avoid light fringes; hair: alpha tested (`MASK`, cutoff 0.4) and double-sided;
  - clothing: the garment's own colour and normal maps (optionally recoloured), a fabric roughness, double-sided.
  - with `"look": "mpfb"` (Amina, Elena, Min-jun) skin, brows, lashes, teeth, tongue and hair keep the materials MPFB makes from the MakeHuman assets (named by role, texture alpha only on brows, lashes and hair); the eyes still get the kit treatment.
- **Size:** about 4.7 to 6.5 MB per avatar (textures: skin albedo and normal 2048 px, skin roughness 1024 px, others 1024 px or less; JPEG where no alpha is needed; sparse morph targets).

## Requirements

- Python 3.10 or newer (standard library only).
- Blender 4.2 or newer (the shipped avatars were built with 5.2.2 LTS).
- About 2.5 GB of free disk space for the MPFB profile, the asset packs and their cached archives (about 1.2 GB of downloads, dress03 alone 486 MB).

The pipeline finds Blender through, in order: `--blender PATH`, the Studio setting `blender_path`, the `BLENDER` environment variable, `PATH`, and the standard install folders. Under WSL a Windows `blender.exe` works; file arguments are converted to Windows paths automatically.

## Setup

```sh
python -m tak setup
```

This installs, into the git-ignored `.tak/blender-user/` Blender profile (your normal Blender configuration is not touched):

- MPFB 2.0.17 from its official GitHub release archive, as a Blender extension;
- every MakeHuman pack the five avatar specs use, from makehumancommunity.org (the table is `PACKS` in `tak/pipeline/__init__.py`; each archive's sha256 is pinned):

| Pack | Archive | Licence | Used for |
|---|---|---|---|
| MakeHuman system assets | `makehuman_system_assets_cc0.zip` | CC0 | base mesh, targets, system skins, eyes, brows, lashes, teeth, tongue, system hair, clothes and shoes |
| Visemes 02, Faceunits 01 | `visemes02.zip`, `faceunits01.zip` | CC0 | the 15 viseme and 52 ARKit targets |
| Skins 02 | `skins02_cc0.zip` | CC0 | Rowan's skin (Mindfront) |
| Shirts 01, Pants 01 | `shirts01_cc0.zip`, `pants01_cc0.zip` | CC0 | Rowan's polo shirt (namuhekam) and cargo trousers (Cortu) |
| Suits 01 | `suits01_cc0.zip` | CC0 | Mira's suit (MargaretToigo) |
| Dress 03, Hair 03 | `dress03_cc-by.zip`, `hair03_ccby.zip` | CC BY | Amina's dress (Mindfront) and hair (punkduck) |
| Hair 02, Shirts 02, Skirts 02 | `hair02_ccby.zip`, `shirts02_ccby.zip`, `skirts02_cc-by.zip` | CC BY | Elena's hair (Elvaerwyn), sweater (Mindfront) and skirt (punkduck) |

Archives are cached in `.tak/downloads/`; their sha256 and licence are recorded in `.tak/install.json`, and a background Blender run then enables MPFB and lists the installed packs. Running setup again skips every pack already installed from the pinned archive, without needing the archive again. Each pack's `packs/<name>.json` names the author and licence of every asset; the build copies them into the manifest (`source_assets.parts`).

Options:

- `--packs-dir DIR`: use archives you already downloaded (the file names above, and optionally `mpfb2-v2.0.17.zip`) instead of downloading them; an archive with another name is found by its sha256. The Studio setting `packs_dir` sets a default.
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
python -m tak build rowan              # one avatar, into build/rebuild/rowan/
python -m tak build --all              # all five
python -m tak build --all --install    # also replace avatars/<slug>/ once each build validates
```

For each avatar the build runs `blender/build_avatar.py` in background Blender, validates the result and, only when validation passes, writes `<slug>.glb`, `manifest.json` and `preview.png` (a Blender render) to `build/rebuild/<slug>/` (`--out DIR` for another folder). `avatars/` is only touched with `--install`, which copies the GLB and manifest into `avatars/<slug>/` and keeps an existing `preview.png`. Work files and logs stay in `.tak/work/` and `.tak/logs/`. A build takes about a minute per avatar.

Rebuilds are reproducible: with the pinned packs, MPFB 2.0.17 and Blender 5.2.2 a build gives the same sha256 as the shipped `avatars/<slug>/<slug>.glb` (the shipped files are these builds). Compare a changed spec's rebuild with the shipped avatar in the Studio by adding `build/rebuild` to the extra avatar folders (setting `extra_avatar_dirs`).

Progress is printed as JSON lines, one object per line, followed by a final result line; the Studio's job log shows the same lines:

```json
{"stage": "face", "message": "loading ARKit and viseme targets", "progress": 0.28}
{"stage": "publish", "message": "wrote build/rebuild/rowan/rowan.glb (5420552 bytes) and manifest.json", "progress": 1.0}
{"result": {"ok": true, "avatars": {"rowan": {"ok": true, "glb": "build/rebuild/rowan/rowan.glb", "installed": null, "...": "..."}}}}
```

The exit code is 0 when every avatar built and validated. Options: `--out DIR`, `--install` (needs validation), `--blender PATH`, `--no-validate`, `--no-preview`, `--keep-blend` (keeps the working `.blend` in `.tak/work/<slug>/`), `--debug` (tracebacks on stderr).

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

Elena's recipe (`avatars/elena/spec.json`) as an example of the community-asset keys:

```json
{
  "schema_version": 1,
  "slug": "elena",
  "name": "Elena",
  "description": "Older Caucasian woman, silver updo, patterned knit sweater, long skirt",
  "persona": "An unhurried retired lecturer with a story for every question.",
  "body": {"gender": 0.0, "age": 0.92, "muscle": 0.38, "weight": 0.54, "height": 0.48,
           "proportions": 0.55, "cupsize": 0.46, "firmness": 0.38,
           "race": {"african": 0.0, "asian": 0.0, "caucasian": 1.0}},
  "rig": "game_engine",
  "look": "mpfb",
  "skin": {"material": "old_caucasian_female"},
  "eyes": {"mesh": "low-poly", "material": "brown"},
  "eyebrows": {"asset": "eyebrow009"},
  "eyelashes": {"asset": "eyelashes03"},
  "teeth": {"asset": "teeth_shape04"},
  "tongue": {"asset": "tongue01"},
  "hair": {"asset": "elvs_50s_updo", "pack": "hair02", "recolor": [0.80, 0.79, 0.78],
           "credit": "hair elvs_50s_updo by Elvaerwyn (MakeHuman community, hair02), CC BY"},
  "clothes": [
    {"asset": "shoes06", "slot": "shoes", "roughness": 0.45},
    {"asset": "punkduck_skirt_native_american_fashion", "pack": "skirts02", "slot": "bottom", "roughness": 0.82,
     "credit": "skirt punkduck_skirt_native_american_fashion by punkduck (MakeHuman, skirts02), CC BY"},
    {"asset": "mindfront_lusekofta", "pack": "shirts02", "slot": "top", "roughness": 0.82,
     "credit": "sweater mindfront_lusekofta by Mindfront (MakeHuman community, shirts02), CC BY"}
  ],
  "face": {"arkit": true, "visemes": "meta"},
  "textures": {"default_max": 1024, "skin_max": 2048, "eyes_max": 512},
  "checks": {"height_m": [1.58, 1.72], "max_bytes": 10000000}
}
```

Rowan's and Mira's specs show the kit look (`"look": "kit"`) with skin detail maps and regions.

- `body`: MakeHuman macro values between 0 and 1.
- `persona` (optional): one line on who the character is; copied into the manifest.
- `look` (optional, default `kit`): `kit` builds the kit's skin (baked albedo, normal and roughness maps with region detail, see *Skin maps*), cards, mouth parts and hair materials; `mpfb` keeps MPFB's own materials from the MakeHuman assets for skin, brows, lashes, teeth, tongue and hair (`roughness`, `recolor` and `base_color` on those parts still apply). Eyes always get the kit eye treatment, garments always keep their own textures unless `keep_texture` is false.
- `pack` (hair and garments): the community pack an asset comes from, one of the packs `python -m tak setup` installs (system assets need no `pack`). An asset from a CC BY pack must carry `credit`, the line the manifest's `credits` and `attribution` list and the GLB's copyright repeats; the validator rejects a CC BY asset without one.
- `attribution_note` (optional): an extra sentence for the manifest's attribution (Rowan and Mira name their CC0 community outfits there).
- Asset names are MakeHuman/MPFB asset names (folder names in the installed packs), never paths: skins (`young_asian_female`, ...), eyes `high-poly` or `low-poly` with an eye material (`brown`, `blue`, `green`, ...), eyebrows `eyebrow001`-`eyebrow012`, eyelashes `eyelashes01`-`04`, teeth `teeth_base`, `teeth_shape01`-`05`, hair (`short01`-`04`, `bob01`, `ponytail01`, `long01`, `braid01`, `afro01`, ...), clothes and shoes.
- `skin`: `material` is a MakeHuman skin name (system or community skin); `tint`: optional albedo multipliers; `roughness`: base roughness; `specular`: Principled specular level (0.5 is the glTF default); optional `base_normal_strength` (the skin's own normal map, default 1), `specular_map_strength` (how much the skin's own specular map lowers roughness, default 0.25), `cavity` (albedo darkening in detail recesses, default 0.08), `sheen` and `sheen_color`; `detail` and `regions`: see *Skin maps*.
- `textures.skin_max`, `skin_normal_max`, `skin_roughness_max`: sizes of the baked skin albedo, normal and roughness maps.
- `clothes`: listed inner layer first (shoes, bottom, top); slots `outfit`, `top`, `bottom`, `shoes`, `hat`, `accessory`, each at most once. Per garment:
  - `roughness`: fabric roughness where the garment has no roughness map (defaults: top and bottom 0.82, outfit 0.8, shoes 0.45);
  - `recolor`: linear RGB; the garment texture takes this colour and keeps its weave and folds as shading (Rowan's green polo); `base_color` multiplies the texture instead, and with `keep_texture: false` the garment is plain `base_color` with its normal map;
  - `cover`: how the body under it is removed: `auto` (default: the garment's MakeHuman delete groups, and ray casting for garments that have none), `raycast` (always ray-cast as well) or `none`;
  - `tucked` (top only): the top's hem goes inside the trousers instead of over them.
- `hair.recolor`: as for garments (Elena's silver updo).
- `layering` (optional, default true): push trousers or a skirt beneath the top and shoes beneath the trouser legs, skirt or outfit (see *Corrections*).
- `weights` (optional): `{"body": true, "garments": true}` switch the body and garment skin-weight corrections.
- `checks`: the validator's height range (bind pose, shoes to hair) and size limit.

Put a new spec in `avatars/<slug>/spec.json` and run `python -m tak build <slug>`. The `slug` must match the folder name.

## Skin maps

The skin is one glTF material, so everything region-dependent is baked by `blender/tak_blender/skinmaps.py` into its three textures in UV space. The look was tuned in the Studio (three.js, AgX and Khronos Neutral tone mapping).

**Regions.** Before MPFB removes its helper geometry, the build derives soft per-vertex weights from the MakeHuman body: the MakeHuman vertex groups (`lips`, `ears`, finger and toe nails), the joint helpers (eyes, mouth, elbows, knees, finger joints; sizes are measured in eye distances) and the rig's skin weights (hands, feet). The regions are `face`, `lips`, `palms` (palms and soles), `body` (a partition: these four sum to one) and the overlapping `cheeks`, `nose`, `forehead`, `chin`, `under_eye`, `ears`, `knuckles`, `elbows`, `knees`, `nails`. They are rasterised into UV space and padded across island borders, so they work for any MakeHuman body.

**Detail slots** (`skin.detail.<slot>`), each a seamless square tile:

| Slot | Applied to | Effect |
|---|---|---|
| `face_pores_height` | face region | height, converted to normal-map slopes |
| `body_skin_height` | body region | height |
| `palm_skin_height` | palms and soles | height |
| `lips_height` | lips | height |
| `color_variation` | whole skin | low-strength albedo multiply (relative colour deviation of the tile) |
| `roughness_variation` | whole skin | roughness offset |

Settings per slot: `source` (`"procedural"`, a built-in tile generated from a fixed seed, or a repository-relative PNG/JPEG path), `strength` (slope scale for heights, relative albedo change for colour, roughness amplitude), `tile_mm` (the size one tile covers on the body, converted to repeats with the region's measured UV scale) or `tiling` (repeats across the UV square), `rotate` (0/90/180/270; the MakeHuman UV layout lays the head on its side, so face-up lip tiles use 90), `repair_seams` (default true for files: offset-and-blend seam repair, variance preserving) and `seed` (procedural). Height and roughness tiles are converted to luminance and normalised, so any grey level or contrast works. Heights are combined with the skin's own normal map (if the MakeHuman skin has one) by adding slopes; recesses also darken the albedo slightly (`cavity`).

**Region settings** (`skin.regions.<region>`): `tint` (albedo multiplier at full weight, scaled by `amount`), `roughness` (offset at full weight) and `detail` (multiplier of the detail strength). Defaults: redder cheeks, nose and ears, a slightly cool under-eye, darker knuckles, elbows and knees; oilier forehead, nose and chin, glossier lips and nails, matte cheeks, rougher palms, knuckles, elbows and knees; more pore detail on the nose, cheeks and chin, less under the eyes.

**Shipped tiles.** `assets/detail/skin/` holds the tiles the shipped avatars use (CC BY 4.0, see [../assets/detail/skin/provenance.json](../assets/detail/skin/provenance.json)). They were prepared from generated source images with

```sh
blender -b --factory-startup --python blender/prepare_detail.py -- --in RAW_FOLDER --out assets/detail/skin [--size 1024]
```

which converts height and roughness tiles to luminance, repairs the seams, resamples to 1024 px (Fourier resampling keeps them seamless) and normalises the contrast. To use your own tiles, put them under `assets/` and point the slots at them; `--dump-maps DIR` on `blender/build_avatar.py` writes the region masks and baked maps as PNG for inspection.

## Corrections applied by the build

- **Skin weights** (`blender/tak_blender/rigfix.py`): before clothes are fitted, the hand-off between the bones of each joint is spread over a wider band with Laplacian smoothing restricted to those bones, inside a sphere around the joint: thumb base (hand, thumb_01, thumb_02), thumb middle joint, knuckles (hand, finger_01, finger_02), wrist, elbow and shoulder (clavicle, upperarm, spine_03). Clothes then inherit the corrected weights; the outfit is smoothed again around shoulders and elbows so raised arms do not tear the armpit into fins.
- **Body under garments** (`blender/tak_blender/cover.py`): MPFB's delete groups of the garments are baked, which removes the skin MakeHuman garments declare as covered. Community garments without a delete list (Rowan's polo and cargo trousers) get one by ray casting: every body face with the garment within 6 cm outside it is removed, keeping two rings of faces along each hem so a lifted arm or a turned head never opens a hole. No skin shows through in the arms-raised and elbows-bent test poses.
- **Garment overlap** (`scene.layer`): garments are fitted one at a time, so trousers or a skirt are pushed 5 mm beneath the top where they overlap (or a `tucked` top beneath the trousers), and shoe and sock vertices beneath the trouser legs, skirt or outfit.
- **Macro shapes**: the MakeHuman proportion keys are baked into the body's basis, so a glTF or FBX viewer shows the real body inside clothes fitted to it.
- **Face targets on parts**: MakeHuman face targets move only the body; the build maps each target onto eyes, brows, lashes, teeth and tongue through their MakeHuman fitting data, so lashes close with a blink, the eyes turn, and lower teeth and tongue follow the jaw.
- **Eyes**: the outer eye shell of the high-poly MakeHuman eyes (meant for alpha blending, opaque in glTF) is removed; the eyeball's clearcoat provides the highlight. Every avatar's eye texture gets the brown iris and calmer sclera (`textures.tune_eye`), and the `eyes` material is marked `extras.tak_eye_treatment`, so `python -m tak.pipeline.glb_eyes` (the same treatment for a GLB built elsewhere) leaves built avatars unchanged.
