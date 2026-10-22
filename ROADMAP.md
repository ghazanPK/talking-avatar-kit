# Roadmap

Goal: prepared virtual-human avatars that are free to use, talk out of the box on the web, and drop into game engines, with tooling to rebuild them and add more.

Approach:

- **Built avatars first:** the repository ships finished characters; the build tooling reproduces and extends them.
- **Harness over core code:** reuse established open-source tools (MPFB for character building, Kokoro for speech, Blender exporters) wherever possible, installed from official sources and credited.
- **One local server:** the Studio and the Talk demo run from `python -m tak`; heavier tools (speech, Blender, Unity checks) are optional add-ons.

## Done

- [x] Studio: avatar library, viewer, blendshape inspector, test poses, reference renders, build jobs, tool checks
- [x] Five prepared avatars (Rowan, Mira, Amina, Elena, Min-jun) with ARKit and viseme blendshapes, credited parts, reproducible build recipes
- [x] Skin detail (community skins, baked pore and wrinkle maps) and eye treatment
- [x] Talking: Kokoro text-to-speech, phoneme-to-viseme timeline, three.js talking rig with blinks, gaze, breathing and moods, Talk demo page
- [x] FBX export and Unity package (Humanoid import, URP or Standard materials, lip-sync helper), with an automated Unity batch check
- [x] Fabric and pattern library for clothing variants

## Next (v0.1 release)

- [ ] GitHub Release with one download per avatar (GLB, FBX, textures, credit line) and an avatar card (height, polygon count, blendshapes, licence)
- [ ] Lip-sync for any audio file through forced alignment, which also covers languages without a Kokoro voice (for example Korean)
- [ ] Drop-in web component (`<talking-avatar>`) with plain HTML and framework examples
- [ ] Citation file and archived release DOI

## Then (v0.2)

- [ ] Animation library: idle, talking gestures, wave, nod, point, sit, walk; Mixamo-compatible bone-name export so common animation libraries apply
- [ ] Load motion files in the Studio and play them on any avatar, including fingers
- [ ] Unity sample scene: talking avatar driven by the speech timeline, idle loop
- [ ] Chat example: text from any language model streamed to speech over a WebSocket (model-agnostic)
- [ ] Lighter variants: compressed meshes and textures, 512 / 1k / 2k texture sets for mobile and VR

## Later

- [ ] VRM 1.0 export
- [ ] Outfit and colour variants as presets (casual, business, clinical) with tints and patterns
- [ ] Webcam face puppeteering (face landmarks to ARKit blendshapes)
- [ ] Online viewer with pre-recorded speech samples
- [ ] Create: parameter ranges and presets to build new avatars in one step, with automatic quality gates
- [ ] Props and interactions: schema for grasp points, approach positions and hand poses; inverse-kinematics interactions baked to clips (sit, pick up, open)
- [ ] More engines and formats, each decided when reached: Unreal FBX, USD / USDZ, Godot, BVH motion clips

## Distribution

GitHub Releases first; Unity package by git URL; other channels decided with the engine and format work.
