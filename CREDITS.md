# Credits

Third-party software and assets used by talking-avatar-kit, with source, version, licence and checksums.

## Studio

### three.js

- Version: 0.186.1 (r186)
- Source: npm registry tarball https://registry.npmjs.org/three/-/three-0.186.1.tgz
  (sha256 `8cd068708ea44f2c73c944b1cead2ba2f0d5c15c8fc194e5700f4e4f4a033fe7`, matches the registry's published sha512 integrity)
- Licence: MIT, copied to `studio/vendor/three/LICENSE`
- Vendored files (unmodified) in `studio/vendor/three/`, sha256:

| File | From the package | sha256 |
|---|---|---|
| `LICENSE` | `LICENSE` | `8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc` |
| `three.module.js` | `build/three.module.js` | `9052042d676cb0fdc1ddfefe193053f34b7ac0513a616fdac4535d49987812ea` |
| `three.core.js` | `build/three.core.js` | `9edde002b066a9a05676a6127f67735b62baf399bdea529f2f7e31657da769e6` |
| `addons/loaders/GLTFLoader.js` | `examples/jsm/loaders/GLTFLoader.js` | `131c0f78c01d19368ae495caa65b3adaa10487810a36a05bb5901b769a35ac16` |
| `addons/controls/OrbitControls.js` | `examples/jsm/controls/OrbitControls.js` | `3d79d07ecb686b4e5d93232eedab255331c1beef711e13164eaa1f68655a5f2b` |
| `addons/environments/RoomEnvironment.js` | `examples/jsm/environments/RoomEnvironment.js` | `55f466192cc84298755a424c5e040345006b2ee1455589b3b54126c2ea4123f4` |
| `addons/utils/BufferGeometryUtils.js` | `examples/jsm/utils/BufferGeometryUtils.js` | `9fb63427ce6641fa14fd0baff9cc4d1b5f9c3d85fd084bf2e90e803c44ec1797` |
| `addons/utils/SkeletonUtils.js` | `examples/jsm/utils/SkeletonUtils.js` | `b1632a703206c3d830de9fcbe515696770d04b71a15ee6b50afa6d2c3298c86f` |

The viewport's image-based lighting is generated at run time by three.js `RoomEnvironment`; no HDRI files are bundled.

## Avatar pipeline

Tools and assets used to build the avatars in `avatars/`. Nothing in this section is vendored: `python -m tak setup` downloads MPFB and the asset packs from their official sources into the git-ignored `.tak/` folder and records the sha256 of each archive in `.tak/install.json`. The avatars themselves are CC BY 4.0, see [avatars/LICENSE.md](avatars/LICENSE.md).

### MPFB (MakeHuman Plugin For Blender)

- Version: 2.0.17, by Joel Palmius and the MakeHuman Community
- Source: GitHub tag archive https://github.com/makehumancommunity/mpfb2/archive/refs/tags/v2.0.17.zip
  (sha256 `d08e726c798fdc4eefb02b06b6c4efe37d40b5439777e53cf96dce0e5073297d`); the `src/mpfb` folder is installed as a Blender extension
- Licence: GPL-3.0-or-later. Used as a tool to generate characters; not distributed with the kit, and its code is not part of the avatar files.

### MakeHuman asset packs

All packs come from the MakeHuman Community. The system assets, face-target packs and the community packs marked CC0 are CC0 1.0 (public domain dedication); the packs marked CC BY are "CC-BY" as their pages and `packs/<name>.json` state, and every asset the avatars take from them is credited below, in the avatar's `manifest.json` (`credits`, `attribution`) and in the GLB's `asset.copyright`.

| Pack | Licence | Archive | sha256 of the archive used for the shipped avatars |
|---|---|---|---|
| [MakeHuman system assets](https://static.makehumancommunity.org/assets/assetpacks/makehuman_system_assets.html) | CC0 | https://files2.makehumancommunity.org/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip | `b542127a8e25547c7c29c19f2d1d2adb9a664c80396ecd694095dbc8028a0107` |
| [Visemes 02](https://static.makehumancommunity.org/assets/assetpacks/visemes02.html) | CC0 | https://files2.makehumancommunity.org/functional/visemes02.zip | `a69ab6fb95ddd5f56f70acc7e859f5f9c6ae613c527d577ea1571eff2183d29e` |
| [Faceunits 01](https://static.makehumancommunity.org/assets/assetpacks/faceunits01.html) | CC0 | https://files2.makehumancommunity.org/functional/faceunits01.zip | `d113107bd7eb59f3af4df6fc0ec29bfcc593f496d0b336aec14f086a80ce7146` |
| [Skins 02](https://static.makehumancommunity.org/assets/assetpacks/skins02.html) (natural male skins) | CC0 | https://files2.makehumancommunity.org/asset_packs/skins02/skins02_cc0.zip | `1613f1ef3afca53094511d26620ed7cf1d2dedc29ed3d384d60bdebe250698ae` |
| [Shirts 01](https://static.makehumancommunity.org/assets/assetpacks/shirts01.html) | CC0 | https://files2.makehumancommunity.org/asset_packs/shirts01/shirts01_cc0.zip | `a5a723b0e84a109bb190fcfeac7f1de4138d875da3e30fe5b3340eac9f38bcd3` |
| [Pants 01](https://static.makehumancommunity.org/assets/assetpacks/pants01.html) | CC0 | https://files2.makehumancommunity.org/asset_packs/pants01/pants01_cc0.zip | `e4e0ec60db34f279be291a83cfd7b342a7c5cf09bb7676682a5f39f4f6ac4ad9` |
| [Suits 01](https://static.makehumancommunity.org/assets/assetpacks/suits01.html) | CC0 | https://files2.makehumancommunity.org/asset_packs/suits01/suits01_cc0.zip | `2b1d8676f3863b188e9eea98c1d8f234543d54c440e791d92b819f8ee1861f19` |
| [Dress 03](https://static.makehumancommunity.org/assets/assetpacks/dress03.html) | CC BY | https://files2.makehumancommunity.org/asset_packs/dress03/dress03_cc-by.zip | `d35487edda8347ac8d0250207007c18056d7aaac404e91946bf9cf1399f2bcd8` |
| [Hair 02](https://static.makehumancommunity.org/assets/assetpacks/hair02.html) | CC BY | https://files2.makehumancommunity.org/asset_packs/hair02/hair02_ccby.zip | `c681e5efd37df4007a52253a8d071aedbfe3b614f199d8dae4ae76d5bd7d95c9` |
| [Hair 03](https://static.makehumancommunity.org/assets/assetpacks/hair03.html) | CC BY | https://files2.makehumancommunity.org/asset_packs/hair03/hair03_ccby.zip | `776c277cb6bcebc32907e05fa94d119e48742cdc1c34183996fc3e65e17a2740` |
| [Shirts 02](https://static.makehumancommunity.org/assets/assetpacks/shirts02.html) | CC BY | https://files2.makehumancommunity.org/asset_packs/shirts02/shirts02_ccby.zip | `d711ca9f73212de855257ac08422e1e0ccb802e5231315c2a360d0fcfea5033e` |
| [Skirts 02](https://static.makehumancommunity.org/assets/assetpacks/skirts02.html) | CC BY | https://files2.makehumancommunity.org/asset_packs/skirts02/skirts02_cc-by.zip | `20958a4669d88efc8295e2a4f5c97677f97ca47607478ee99e1a141525cff5b3` |

The avatars embed meshes, targets and (resized, colour-adjusted) textures derived from these packs.

Community assets in the shipped avatars (author, pack, licence):

| Avatar | Part | Asset | Author | Pack | Licence |
|---|---|---|---|---|---|
| Rowan | skin | `mindfront_skin_male_african_middleage` | Mindfront | skins02 | CC0 |
| Rowan | top | `namuhekam_male_polo_shirt` | namuhekam | shirts01 | CC0 |
| Rowan | bottom | `cortu_cargo_pants` | Cortu | pants01 | CC0 |
| Mira | outfit | `toigo_female_double-breasted_suit` | MargaretToigo | suits01 | CC0 |
| Amina | outfit | `mindfront_f_dress_09` | Mindfront | dress03 | CC BY |
| Amina | hair | `punkduck_alpha7_curly` | punkduck | hair03 | CC BY |
| Elena | bottom | `punkduck_skirt_native_american_fashion` | punkduck | skirts02 | CC BY |
| Elena | top | `mindfront_lusekofta` | Mindfront | shirts02 | CC BY |
| Elena | hair | `elvs_50s_updo` | Elvaerwyn | hair02 | CC BY |

Everything else (bodies, system skins, eyes, brows, lashes, teeth, tongue, Min-jun's outfit and every pair of shoes) comes from the MakeHuman system assets (CC0).

Community skin used by Rowan: *skin male african middleage* (`mindfront_skin_male_african_middleage`, 2048 px colour, normal and specular maps) by **Mindfront**, CC0 1.0, http://www.makehumancommunity.org/node/526 (shipped in Skins 02). Mira uses the MakeHuman system skin `young_asian_female`. Each avatar's `manifest.json` records its skin's author, licence and source under `skin.asset`.

### Skin detail tiles

`assets/detail/skin/` (face pores, body skin, palm skin and lip height tiles, light and dark skin colour variation, roughness variation; 1024 px) are part of this kit, CC BY 4.0, credit "talking-avatar-kit by Ghazanfar Ali". They were generated on 2026-10-08 with an image generator from text prompts recorded by the author and processed with `blender/prepare_detail.py` (luminance, seam repair, resampling, contrast normalisation); `provenance.json` there lists the sha256 of each source image and output. Procedural alternatives for every slot are generated by `blender/tak_blender/skinmaps.py`.

### Blender

- Version used for the shipped avatars: 5.2.2 LTS (any Blender 4.2 or newer is expected to work)
- Source: https://www.blender.org/download/ (installed by the user; not bundled)
- Licence: GPL-2.0-or-later. Runs the build, validation and pose-check scripts in `blender/` in background mode.

### Khronos glTF exporter for Blender (glTF-Blender-IO)

- Version: the one bundled with Blender (5.2.40 for the shipped avatars, recorded in each `manifest.json`)
- Source: https://github.com/KhronosGroup/glTF-Blender-IO
- Licence: Apache-2.0. Writes the GLB files.

## FBX export and Unity package

Nothing in this section is vendored.

### Blender FBX importer and exporter (io_scene_fbx)

- Version: the one bundled with Blender (5.15.0 with Blender 5.2.2 LTS; recorded in each exported `<slug>.tak.json`)
- Source: bundled with Blender, https://projects.blender.org/blender/blender (scripts/addons_core/io_scene_fbx)
- Licence: GPL-2.0-or-later. Used as a tool by `blender/export_fbx.py` to write and re-import the FBX files; none of its code is part of the kit or of the exported files. `blender/tak_blender/fbx.py` wraps one of its internal functions at run time so texture paths in the FBX stay relative.

### Unity

- Version used for the checks: Unity 6000.3.25f1 with the Universal Render Pipeline package bundled with that editor
- Source: https://unity.com/download (installed by the user; not bundled)
- Licence: Unity Editor Software Terms (proprietary). `unity/` is an original MIT package that uses the public Unity editor and engine APIs; it contains no Unity code or assets. `python -m tak export fbx --unity-check` runs an installed editor in batch mode.

## Fabric and pattern library

`assets/fabrics/` (15 tileable fabrics: greyscale albedo, tangent-space normal map, optional roughness variation) and `assets/patterns/` (5 tileable pattern masks) are part of this kit, CC BY 4.0, credit "talking-avatar-kit by Ghazanfar Ali". The source swatches were generated on 2026-10-08 with an image generator from text prompts recorded by the author and processed with `tak/pipeline/fabrics.py` (luminance, flat-field correction, alignment of the weave between albedo and height, seam repair by offsetting and quilting along minimum-error cuts, periodic resampling, normal maps from height at the real patch size; pattern masks snapped to exact palettes and cropped to whole periods). `fabrics.json` and `patterns.json` list the real patch size of every tile and the sha256 of each source image and output. The processing tool uses [NumPy](https://numpy.org) (BSD-3-Clause) and [Pillow](https://python-pillow.org) (MIT-CMU); neither is needed to use the library.

## Speech (optional)

Nothing in this section is vendored. `python -m tak speech setup` installs the packages from PyPI (PyTorch from the official CPU wheel index) into the git-ignored `.tak/speech-venv`, and the model and voices are downloaded from the Hugging Face Hub into the git-ignored `.tak/models/` on first use; `.tak/speech-install.json` records the installed versions and the sha256 of every downloaded model file. The talking rig (`studio/js/talking/`) and the phoneme-to-viseme conversion (`tak/speech/`) are part of this kit (MIT).

| Component | Version tested | Source | Licence | Use |
|---|---|---|---|---|
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) model and voices | v1.0 (`kokoro-v1_0.pth` sha256 `496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4`) | Hugging Face Hub `hexgrad/Kokoro-82M` | Apache-2.0 | Text-to-speech weights, downloaded on first use |
| [kokoro](https://github.com/hexgrad/kokoro) | 0.9.4 | PyPI | Apache-2.0 | Inference library; reports the predicted phoneme durations used for lip-sync |
| [misaki](https://github.com/hexgrad/misaki) | 0.9.4 | PyPI | Apache-2.0 | Grapheme-to-phoneme conversion (English dictionaries, Japanese and Mandarin extras) |
| [PyTorch](https://pytorch.org) | 2.14.1 (CPU) | https://download.pytorch.org/whl/cpu | BSD-3-Clause | Runs Kokoro |
| [spaCy](https://spacy.io) and `en_core_web_sm` | 3.8.16, 3.8.0 | PyPI, spaCy model release | MIT | English tokenisation for misaki |
| [phonemizer-fork](https://pypi.org/project/phonemizer-fork/) with [espeak-ng](https://github.com/espeak-ng/espeak-ng) (through `espeakng-loader`) | 3.3.2, 0.2.4 | PyPI | GPL-3.0 | G2P for Spanish, French, Hindi, Italian and Portuguese; installed as tools, not distributed with the kit |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub), [soundfile](https://github.com/bastibe/python-soundfile), NumPy | as resolved by pip | PyPI | Apache-2.0, BSD-3-Clause, BSD-3-Clause | Model download, audio |
