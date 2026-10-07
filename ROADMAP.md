# Roadmap

Goal: choose a preset or a range of parameters, press **Create**, and receive a finished avatar: rigged, with facial blendshapes and lip-sync, customisable, and ready for the web.

Approach:

- **Web first:** three.js is the target for every feature. Game engines and other formats come later; each output is decided when it is reached.
- **Studio:** a local web app is the single place to run and check every feature. It is backed by a local Python service that drives headless Blender, alignment tools and exporters. A static viewer stays available for embedding.
- **Harness over core code:** reuse established open-source tools and Blender add-ons (for example MPFB for one-click character building) wherever possible. Tools are installed by setup scripts from their official sources at pinned versions, and credited.
- **Canonical form:** humanoid skeleton with Unity-humanoid hierarchy (T-pose, metres), 52 ARKit facial blendshapes, 15 viseme blendshapes and a material-slot manifest. Each export converts from it.

## Milestones

### M1: Studio and polished starter avatars
- [x] Studio shell: avatar library, 3D viewport, job log, settings for local tools
- [x] One-command setup and launch; setup checks for Blender and other tools
- [ ] Two starter avatars with polished skin, eyes, teeth and basic hair
- [ ] Bind-pose and skin-weight fixes for shoulders, elbows, hands and thumbs
- [x] Viewport lighting, tone mapping, shadows, camera presets
- [x] Reference renders with fixed motion and cameras for before/after comparison

### M2: Rig and motion
- [ ] Canonical humanoid skeleton and rest pose
- [ ] Load motion files into the Studio and play them, including fingers
- [ ] Validation clips: rest, open hand, fist, pointing, thumb, fast transitions, sitting
- [ ] GLB export from the Studio
- [ ] Automatic checks: Blender re-import and browser load (skeleton, blendshapes, materials)

### M3: Face and lip-sync
- [ ] Load audio files or generate speech in the Studio
- [ ] Phoneme alignment from TTS timings or a forced aligner
- [ ] Multilingual phoneme-to-viseme tables
- [ ] Viseme timeline on the audio clock, with limited jaw/viseme stacking
- [ ] Blinking, gaze and expression blending
- [ ] Combined playback of body motion, speech and face

### M4: Customisation
- [ ] Material slots: skin, hair, eyes, top, bottom, shoes
- [ ] Colour tints and texture-set swapping in the Studio
- [ ] Appearance presets saved as JSON

### M5: Create
- [ ] Character specification: body parameters, outfit, hair, skin and appearance
- [ ] Parameter ranges and presets with a **Create** button; batch creation
- [ ] Headless build, automatic quality gates and export per created avatar
- [ ] At least one new avatar created entirely from the Studio

### M6: Props and interactions
- [ ] Props built for this project (procedural Blender tools or our own modelling) or taken from CC0 sources; no store or brand-catalogue models
- [ ] Prop schema: grasp points, approach position, hand pose, contact targets
- [ ] Inverse-kinematics generation of interactions, baked to clips
- [ ] Prop bundles with interactions, playable with any avatar in the Studio

### Later: engines and formats
Candidates, each decided when reached: Unity (FBX and package), VRM 1.0, Unreal FBX, Mixamo-compatible bone names, USD / USDZ, Godot, BVH for motion clips.

## Releases

- v0.1: M1 to M3
- v0.2: M4 and M5
- v0.3: M6
- Later: engines and formats, then additional features as needed

## Distribution

GitHub Releases first; other channels decided with the engine and format work.
