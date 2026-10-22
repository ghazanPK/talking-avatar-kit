# talking-avatar-kit

Prepared virtual-human avatars that talk: rigged characters with facial blendshapes, a three.js talking rig with local text-to-speech, a web demo with its own server, and Unity-ready FBX export.

## Current state

- **Avatars:** five prepared avatars in `avatars/<slug>/` (GLB, manifest, preview): Rowan, Mira, Amina, Elena and Min-jun. Each has a 53-bone humanoid rig (A-pose), the 52 ARKit facial blendshapes and 15 viseme targets, and physically based materials. Credits and licences are in each manifest. Rowan and Mira also carry their build `spec.json`.
- **Talking:** text goes to the local Kokoro text-to-speech model; its predicted phoneme durations become a 15-viseme lip-sync track. The three.js rig (`studio/js/talking/rig.js`) plays the audio and drives mouth, blinks, gaze, breathing, head motion and moods from the audio clock. The `/api/speech/say` endpoint returns audio plus a timeline (words, phonemes, visemes, keyframes) usable by any engine. Voices: US and UK English, Spanish, French, Hindi, Italian, Brazilian Portuguese (Japanese and Mandarin with extra setup). Korean is not covered by Kokoro.
- **Demo and Studio:** one local server. The Talk page picks an avatar, voice, speed and mood and speaks typed text. The Studio browses avatars, drives blendshapes, applies test poses, captures reference renders, runs build jobs and checks installed tools.
- **FBX and Unity:** `python -m tak export fbx` converts avatars to Unity-ready FBX (metres, Y up, facing +Z, blendshapes on every mesh they move, textures and a sidecar with licence, bone map, blendshapes and materials). The Unity package in `unity/` imports them as Humanoid characters with URP Lit or Standard materials and a component that drives visemes and ARKit shapes by name. An optional batch check validates the import in Unity and renders previews.
- **Pipeline:** headless Blender builds avatars from `spec.json` with MPFB and validates the result. Skin uses CC0 MakeHuman community skins with baked region detail from tiles in `assets/detail/skin/`.

Body-motion playback, customisation and avatar creation are not implemented yet; see [ROADMAP.md](ROADMAP.md).

## Quick start

Requires Python 3.10 or newer (standard library only for the Studio and demo).

```sh
python -m tak speech setup   # once: Kokoro and CPU PyTorch into .tak/speech-venv (about 1.5 GB)
python -m tak demo           # opens the talking demo
```

The first sentence downloads the Kokoro model (about 330 MB) into `.tak/models/`; model weights are never committed. `python -m tak studio` opens the Studio (the Talk page is linked from it).

FBX and Unity (Blender 4.2 or newer; Unity optional):

```sh
python -m tak export fbx --all                 # FBX, textures and sidecar into build/export/<slug>/
python -m tak export fbx --all --unity-check   # also import and validate in Unity batch mode
```

In Unity: Package Manager, Add package from git URL: `https://github.com/ghazanPK/talking-avatar-kit.git?path=unity`, then add the exported folders to your project.

Rebuilding avatars from their specifications (Blender 4.2 or newer):

```sh
python -m tak setup        # install MPFB and the CC0 MakeHuman asset packs into .tak/
python -m tak check        # report Python, Blender and MPFB status
python -m tak build rowan  # rebuild one avatar from avatars/rowan/spec.json
```

Details: [docs/talking.md](docs/talking.md), [docs/unity.md](docs/unity.md), [docs/studio.md](docs/studio.md), [docs/avatars.md](docs/avatars.md).

## Repository contents

| Path | Purpose |
|---|---|
| `avatars/` | Prepared avatars, manifests and previews |
| `studio/` | Studio and Talk pages (plain ES modules; three.js vendored in `studio/vendor/three/`); talking rig in `studio/js/talking/` |
| `tak/` | Python package: CLI, local server, jobs, settings, tool discovery |
| `tak/speech/` | Optional Kokoro speech: setup, worker, phoneme-to-viseme timeline |
| `tak/pipeline/` | Setup, build, validation and FBX/Unity export commands |
| `blender/` | Scripts that run inside Blender |
| `unity/` | Unity package: FBX avatar importer (Humanoid, materials), lip-sync helper, batch check |
| `assets/detail/skin/` | Seamless skin detail tiles used by the build, with provenance |
| `assets/fabrics/`, `assets/patterns/` | Seamless fabric swatches and pattern masks, with provenance |
| `tests/` | Tests (`python -m pytest`); Blender, Unity and Kokoro tests run only when those tools are installed |
| `docs/` | Guides |
| `ROADMAP.md`, `RELEASE_NOTES.md` | Planned work and released changes |
| `CREDITS.md` | Third-party tools and assets |

## Licence

Code: MIT, see [LICENSE](LICENSE). Avatars and other assets: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), free to use, modify and redistribute in any format, including source files, with credit; see [avatars/LICENSE.md](avatars/LICENSE.md) and each avatar's manifest for part credits. Third-party tools and assets: [CREDITS.md](CREDITS.md).
