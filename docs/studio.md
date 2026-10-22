# Studio

The Studio is a local web app for inspecting avatars, running the avatar pipeline and capturing reference renders. It is served by a small Python server (standard library only) and runs in any current desktop browser with WebGL 2.

## Launch

From the repository root, with Python 3.10 or newer:

```
python -m tak studio
```

The server listens on `127.0.0.1` only and prints its URL (default `http://127.0.0.1:8750/`). Options:

- `--port N` uses another port (`0` picks a free one).
- `--no-open` does not open a browser.

Under WSL the browser is opened on the Windows side when possible. Stop the server with Ctrl+C.

Other commands of the same entry point:

| Command | Purpose |
|---|---|
| `python -m tak setup` | Install MPFB and the CC0 asset packs used by headless builds |
| `python -m tak build <slug>` / `--all` | Build avatars from `avatars/<slug>/spec.json` |
| `python -m tak check` | Report Python, Blender, MPFB and pack availability as JSON |
| `python -m tak demo` | The same server, opening the talking demo at `/talk/` (see [talking.md](talking.md)) |
| `python -m tak speech setup` | Install the optional Kokoro speech into `.tak/speech-venv` |

## Layout

- **Avatar library** (left): every `avatars/<slug>/` folder with a `manifest.json`, a `<slug>.glb` or a `spec.json`, plus the folders listed under *Extra avatar folders* in the settings (loose `.glb` files or `<slug>/` folders). A GLB without a manifest still loads. **Build** runs `python -m tak build <slug>` for avatars that have a `spec.json`; **Build all** builds every avatar.
- **Viewport** (centre): physically based rendering with AgX tone mapping (ACES Filmic, Khronos Neutral and linear are selectable), exposure, image-based lighting from three.js `RoomEnvironment`, a key light with soft shadows on the floor and a rim light. Drag to orbit, right-drag to pan, scroll to zoom.
  - Camera presets: full body, upper body, face, left hand, right hand (keys `1` to `5`). Presets are computed from the avatar's size, so avatars of any height are framed the same way.
  - Options: tone mapping, exposure, background, skeleton overlay (key `s`), floor grid.
- **Inspector** (right):
  - *Morphs*: one slider per morph target, grouped into visemes, brows, eyes, cheeks and nose, jaw, mouth and tongue, with a filter box and a reset button.
  - *Pose*: the reference pose sheet (see below).
  - *Capture*: renders the reference set.
- **Jobs** (bottom bar): pipeline jobs run one at a time. The log shows each output line; JSON progress lines (`{"stage", "message", "progress"}`) are shown as stages and drive the progress bar, and the final `{"result": ...}` line is highlighted. Running jobs can be cancelled.
- **Renders**: browse captured sets as a pose by camera grid, and compare two sets side by side (for example `before` and `after`).
- **Settings**: tool locations and a tool check.

## Settings

Settings are stored outside the repository:

- Linux and macOS: `$XDG_CONFIG_HOME/talking-avatar-kit/settings.json` (default `~/.config/...`)
- Windows: `%APPDATA%\talking-avatar-kit\settings.json`
- `TAK_CONFIG_DIR` overrides the folder.

| Key | Meaning |
|---|---|
| `blender_path` | Blender executable. Empty: the `BLENDER` environment variable, `PATH`, then the standard install folders (`ProgramFiles`, `ProgramFiles(x86)`, `LOCALAPPDATA` on Windows; `/Applications` on macOS). |
| `mpfb_profile_dir` | Blender user folder with MPFB and the packs. Empty: `.tak/blender-user` in the repository. |
| `packs_dir` | Folder with already downloaded asset pack zips, passed to `tak setup --packs-dir`. |
| `extra_avatar_dirs` | Additional folders shown in the avatar library. Relative paths are relative to the repository. |

Under WSL a Windows Blender (`blender.exe`) works: Windows paths such as `D:/Tools/Blender/blender.exe` are accepted, and file arguments are converted with `wslpath -w` when the pipeline starts a Windows program. Jobs started from the Studio receive the configured Blender through the `BLENDER` environment variable.

**Run check** shows the Studio's own Blender discovery (every candidate and where it came from, plus `blender --version`) and the output of `python -m tak check`. **Run setup** starts `python -m tak setup` as a job.

## Reference renders

The pose sheet `studio/poses/reference.json` defines eight poses: bind pose, relaxed A-pose, arms raised, elbows bent 90 degrees, open hands, fists, pointing and thumb opposition. Poses are lists of operations applied on top of the bind pose (`aim`, `palm`, `flat`, `curl`, `spread`, `reach`, `rotate`). Directions are given in the avatar frame (+x the avatar's left, +y up, +z the avatar's forward), not in bone-local axes, and `"mirror": true` repeats an operation for the right side.

Bone names follow the rig description `studio/rigs/mpfb-game-engine.json` (the MPFB game-engine skeleton). It maps each bone to its canonical humanoid name, so the same pose sheet resolves on a skeleton that uses the canonical names. Missing bones are listed under the pose list.

**Capture reference set** renders every pose from every camera preset at a fixed size (512, 1024 or 2048 pixels square) with an offscreen renderer at pixel ratio 1. It saves to `build/renders/<slug>/<label>/`:

- `<pose>__<camera>.png` for each image,
- `sheet.png`, a contact sheet of all images,
- `index.json` with the avatar, renderer settings, poses, cameras and image list.

Full-body, upper-body and face cameras are fixed per avatar (from bind-pose measurements); hand cameras follow the hand in each pose. Morph targets are reset to zero during capture. With the same avatar, browser and settings, repeated captures are identical. Use labels such as `before` and `after` and compare them in the Renders view. `build/` is not committed.

## Scripting

The page exposes `window.studio` for automation, for example in Playwright:

```js
await window.studio.ready;
await window.studio.selectAvatar('avatars/rowan');
window.studio.applyPose('fists');
window.studio.setCamera('hand_l');
await window.studio.captureReferenceSet({label: 'after', size: 1024});
```

The URL hash keeps the view state: `#view=viewer&avatar=avatars/rowan&camera=face&pose=fists&tab=pose`.

## HTTP API

All endpoints are on the local server and exchange JSON. State-changing requests must send `Content-Type: application/json`; requests whose `Host` header is not `127.0.0.1` or `localhost` are refused.

| Endpoint | Purpose |
|---|---|
| `GET /api/avatars` | Avatar library entries |
| `GET /api/check` | Studio discovery and `python -m tak check` output |
| `GET`, `PUT /api/settings` | Read or update settings |
| `POST /api/jobs` | Start `{"kind": "build", "slug": ...}`, `{"kind": "build", "all": true}`, `{"kind": "setup"}` or `{"kind": "check"}` |
| `GET /api/jobs` | Job summaries |
| `GET /api/jobs/<id>?offset=N` | Job status and log lines from line `N` |
| `POST /api/jobs/<id>/cancel` | Cancel a queued or running job |
| `GET /api/renders` | Saved render sets |
| `POST /api/renders` | Save `{"slug", "label", "name", "data_url"}` (PNG) or `{"slug", "label", "name", "json"}` under `build/renders/` |

Speech endpoints (`/api/speech/status`, `/api/speech/voices`, `POST /api/speech/say`, `/api/speech/audio/<id>.wav`) are described in [talking.md](talking.md).

Files: `/avatars/...` (repository avatars), `/extra/<n>/...` (extra avatar folder `n`), `/renders/...` (saved renders); everything else comes from `studio/` (the talking demo is `studio/talk/`, served at `/talk/`).

## Tests

```
python -m pytest tests
```

The Studio tests need neither network access nor Blender.
