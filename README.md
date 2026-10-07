# talking-avatar-kit

Prepared virtual-human avatars for the web: rigged, with facial blendshapes, built reproducibly and inspected in a local Studio.

## Current state

- **Avatars:** two prepared avatars, Rowan and Mira, in `avatars/<slug>/` (GLB, manifest, spec, preview). Each has a 53-bone humanoid rig (A-pose), the 52 ARKit facial blendshapes and 15 viseme targets, and physically based materials.
- **Studio:** a local web app to browse avatars, view them under tone-mapped lighting with camera presets, drive blendshapes, apply test poses, capture reference renders, run build jobs and check installed tools.
- **Pipeline:** headless Blender builds avatars from `spec.json` with MPFB, then validates the result (skeleton, blendshapes, materials, height, size, Blender re-import).

Lip-sync, motion-file playback, customisation and avatar creation are not implemented yet; see [ROADMAP.md](ROADMAP.md).

## Quick start

Requires Python 3.10 or newer (standard library only).

```sh
python -m tak studio
```

This serves the Studio at a local address (default port 8750) and opens it. The bundled avatars need nothing else.

To rebuild or create avatars you also need Blender 4.2 or newer:

```sh
python -m tak setup        # install MPFB and the CC0 MakeHuman asset packs into .tak/
python -m tak check        # report Python, Blender and MPFB status
python -m tak build --all  # rebuild every avatar in avatars/
```

Details: [docs/studio.md](docs/studio.md) and [docs/avatars.md](docs/avatars.md).

## Repository contents

| Path | Purpose |
|---|---|
| `avatars/` | Prepared avatars and their specifications |
| `studio/` | Studio web app (plain ES modules; three.js vendored in `studio/vendor/three/`) |
| `tak/` | Python package: CLI, local Studio server, jobs, settings, tool discovery |
| `tak/pipeline/` | Setup, build and validation commands |
| `blender/` | Scripts that run inside Blender |
| `tests/` | Tests (`python -m pytest`); the real Blender build test runs only when Blender is available |
| `docs/` | Studio and avatar guides |
| `ROADMAP.md`, `RELEASE_NOTES.md` | Planned work and released changes |
| `CREDITS.md` | Third-party tools and assets |

## Licence

Code: MIT, see [LICENSE](LICENSE). Avatars and other assets: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), free to use, modify and redistribute in any format, including source files, with credit; see [avatars/LICENSE.md](avatars/LICENSE.md). Third-party tools and assets: [CREDITS.md](CREDITS.md).
