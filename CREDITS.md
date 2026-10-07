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

All three packs are CC0 1.0 (public domain dedication), from the MakeHuman Community:

| Pack | Archive | sha256 of the archive used for the shipped avatars |
|---|---|---|
| [MakeHuman system assets](https://static.makehumancommunity.org/assets/assetpacks/makehuman_system_assets.html) | https://files2.makehumancommunity.org/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip | `b542127a8e25547c7c29c19f2d1d2adb9a664c80396ecd694095dbc8028a0107` |
| [Visemes 02](https://static.makehumancommunity.org/assets/assetpacks/visemes02.html) | https://files2.makehumancommunity.org/functional/visemes02.zip | `a69ab6fb95ddd5f56f70acc7e859f5f9c6ae613c527d577ea1571eff2183d29e` |
| [Faceunits 01](https://static.makehumancommunity.org/assets/assetpacks/faceunits01.html) | https://files2.makehumancommunity.org/functional/faceunits01.zip | `d113107bd7eb59f3af4df6fc0ec29bfcc593f496d0b336aec14f086a80ce7146` |

The avatars embed meshes, targets and (resized, colour-adjusted) textures derived from these packs.

### Blender

- Version used for the shipped avatars: 5.2.2 LTS (any Blender 4.2 or newer is expected to work)
- Source: https://www.blender.org/download/ (installed by the user; not bundled)
- Licence: GPL-2.0-or-later. Runs the build, validation and pose-check scripts in `blender/` in background mode.

### Khronos glTF exporter for Blender (glTF-Blender-IO)

- Version: the one bundled with Blender (5.2.40 for the shipped avatars, recorded in each `manifest.json`)
- Source: https://github.com/KhronosGroup/glTF-Blender-IO
- Licence: Apache-2.0. Writes the GLB files.
