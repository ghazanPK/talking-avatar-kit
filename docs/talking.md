# Talking avatars

The kit makes its avatars speak: text goes to a local Kokoro text-to-speech model, which returns audio together with the duration of every phoneme; the phonemes become a viseme track, and a small three.js rig plays the audio and drives the avatar's mouth, eyes, head and breathing from the audio clock.

Everything runs locally. Speech is optional: the Studio and the avatars work without it.

## Quick start

```sh
python -m tak speech setup   # once: installs Kokoro into .tak/speech-venv (about 1.5 GB with CPU PyTorch)
python -m tak demo           # serves the Studio and opens the talking demo at /talk/
```

The demo page is part of the Studio server (`python -m tak studio` serves it too, under **Talk** in the top bar). Pick an avatar, type text, choose a voice, speed and mood, and press **Speak** (or Ctrl+Enter). Camera presets: face, upper body, full body. Without the speech setup the page shows the setup command instead of speaking.

The first sentence downloads the Kokoro model (`hexgrad/Kokoro-82M`, about 330 MB) and the selected voice (about 0.5 MB each) from the Hugging Face Hub into `.tak/models/Kokoro-82M/`. Synthesised clips are cached in `.tak/cache/speech/`. Both folders are git-ignored; model weights are never committed.

## Speech setup

`python -m tak speech setup`:

1. creates `.tak/speech-venv` with a Python 3.10 to 3.12 (Kokoro does not support newer versions yet): the current interpreter if it fits, otherwise `python3.12`, `python3.11` or `python3.10` from `PATH` (on Windows also `py -3.12` ...), or `--python PATH`;
2. installs PyTorch from the official CPU wheel index on Linux and Windows (`--torch-index URL` for another build, for example CUDA), then `kokoro` and `soundfile` from PyPI; Kokoro brings its G2P library `misaki` with the English pipeline and espeak-ng (through `espeakng-loader`) for the other languages;
3. installs the spaCy model `en_core_web_sm` used by the English G2P;
4. downloads the model and the default voices (`--voices af_heart,bf_emma`; `--no-download` skips this);
5. synthesises a test sentence and writes `.tak/speech-install.json` (versions, files and sha256).

Options: `--check` only reports what is installed or missing; `--lang ja,zh` adds the Japanese or Mandarin G2P (`misaki[ja]`, `misaki[zh]`).

Other commands:

| Command | Purpose |
|---|---|
| `python -m tak speech status` | Speech status as JSON (what `/api/speech/status` returns) |
| `python -m tak speech voices` | Kokoro voices as JSON |
| `python -m tak speech say "Text" --voice bf_emma --out hello.wav` | Synthesise to WAV plus `hello.json` (the timeline) |

Environment variables: `TAK_SPEECH_PYTHON` (use this interpreter instead of the venv), `TAK_SPEECH_VENV` (venv folder), `TAK_KOKORO_DIR` (model folder, for example an existing local copy with `config.json`, `kokoro-v1_0.pth` and `voices/`), `TAK_SPEECH_DEVICE` (`cpu` by default, `cuda` with a CUDA build of PyTorch).

### Languages

Kokoro v1.0 voices cover American and British English, Spanish, French, Hindi, Italian, Brazilian Portuguese, Japanese and Mandarin Chinese. English uses misaki's dictionary-based G2P with word tokens; Spanish, French, Hindi, Italian and Portuguese use espeak-ng; Japanese and Mandarin need `--lang ja` or `--lang zh`. The first letter of a voice id selects the language (`a` US English, `b` UK English, `e` Spanish, `f` French, `h` Hindi, `i` Italian, `p` Portuguese, `j` Japanese, `z` Mandarin).

**Korean is not covered by Kokoro**: there is no Korean voice or G2P.

## Architecture

```
browser (/talk/)                     python -m tak demo (standard library)          .tak/speech-venv
 TalkingRig  <- audio + timeline  <-  POST /api/speech/say  -> SpeechService  ->  tak.speech.worker (Kokoro, PyTorch)
             AudioContext clock       GET  /api/speech/audio/<id>.wav            JSON lines over stdin/stdout
```

- `tak/speech/service.py` validates requests, caches clips and keeps one Kokoro worker process alive. The server itself imports nothing outside the standard library; the worker runs with the speech venv's Python.
- `tak/speech/worker.py` runs Kokoro and reports, per synthesised chunk, the phoneme string the model read (one model token per character), the predicted duration of each token in frames (600 samples = 25 ms at 24 kHz) and misaki's word tokens.
- `tak/speech/visemes.py` turns that report into the timeline (standard library, unit tested).
- `studio/js/talking/rig.js` is the reusable three.js rig; `studio/js/talk.js` and `studio/talk/` are the demo page.

## HTTP API

| Endpoint | Purpose |
|---|---|
| `GET /api/speech/status` | `available`, `reason`, `setup_command`, installed versions, G2P per language, languages, whether the weights are downloaded |
| `GET /api/speech/voices` | `{"voices": [{"id", "lang", "language", "language_name", "gender", "label", "downloaded"}], "default"}` |
| `POST /api/speech/say` | `{"text", "voice", "speed"}` (text up to 2000 characters, speed 0.5 to 2) returns `{"id", "cached", "audio_url", "synthesis_seconds", "timeline"}` |
| `GET /api/speech/audio/<id>.wav` | The clip: 24 kHz mono 16-bit WAV |

## Timeline

```json
{
  "version": 1, "duration": 2.475, "sample_rate": 24000,
  "text": "Peter bought a box of fresh apples.", "voice": "af_heart", "speed": 1.0, "language": "en-US",
  "visemes_set": "oculus15", "lead": 0.03,
  "words":    [{"text": "Peter", "start": 0.15, "end": 0.475, "phonemes": "pˈiɾəɹ"}, ...],
  "phonemes": [{"p": "p", "start": 0.15, "end": 0.2, "viseme": "PP"}, ...],
  "visemes":  [{"viseme": "PP", "start": 0.15, "end": 0.2, "weight": 1.0}, ...],
  "keys":     {"viseme_PP": [[0.08, 0], [0.12, 1], [0.17, 1], [0.21, 0], ...], "viseme_aa": [...], ...}
}
```

Times are seconds from the start of the audio.

- **Phoneme to viseme**: IPA and misaki symbols map to the 15 Oculus visemes (`PP` p b m, `FF` f v, `TH` θ ð, `DD` t d ɾ, `kk` k g ŋ, `CH` ʃ ʒ ʧ ʤ, `SS` s z, `nn` n l, `RR` ɹ r ɚ, `aa` a ɑ æ ʌ, `E` e ɛ ə, `I` i ɪ j, `O` o ɔ, `U` u ʊ w). Misaki's diphthong letters (`A` eɪ, `I` aɪ, `O` oʊ, `Q` əʊ, `W` aʊ, `Y` ɔɪ) become two shapes (60 % / 40 % of the duration). Stress marks add their duration to the next phoneme, length and tone marks to the previous one, `h` and the glottal stop take the shape of the next sound, punctuation is silence, and gaps between words shorter than 120 ms are shared by the neighbouring sounds instead of closing the mouth.
- **Weights**: each viseme has a peak weight (lip closures `PP` and lip-teeth `FF` 1.0, open vowels 0.8, other consonants 0.5 to 0.75), reduced for reduced vowels and very short sounds.
- **Keys** (coarticulation): every segment becomes a trapezoid that starts `lead` (30 ms) before the sound plus a 60 ms attack and releases over 80 ms after it, so neighbouring shapes overlap. `PP` and `FF` reach full weight 30 ms before the consonant (40 ms attack) and hold it until 20 ms before its audible release (at least 50 ms), then open over 40 ms, so the lips really close and part with the burst. Curves of the same viseme are combined with `max`; sample them with linear interpolation (`sample()` in `tak/speech/visemes.py`, `sampleKeys()` in the rig).

Use `keys` to drive any engine (the Unity and FBX exports keep the same `viseme_*` names), or `visemes` / `phonemes` / `words` for your own animation.

### Timing

Kokoro predicts the duration of every phoneme, so the timing comes from the synthesis model itself; there is no separate aligner. The sum of the predicted durations equals the audio length exactly (600 samples per frame). The audio runs three frames (75 ms) ahead of the cumulative durations, the same correction Kokoro applies to its own word timestamps, so the timeline starts the first phoneme three frames before the end of the begin token (`TAK_SPEECH_SHIFT_FRAMES` overrides it).

Checked against the waveform on "Peter bought a box of fresh apples. My mother made maple bread, but Bob prefers apple pie." (12 bilabial stops per clip): with the correction the audible release bursts of `p`/`b`/`m` fall within a median of -18 to +12 ms of the predicted phoneme ends (voices `af_heart` at speed 0.8 and 1.0, `bf_emma` at 1.0, `am_michael` at 1.3; without it they come 72 ms early). The visemes reach half weight 36 to 180 ms (mean about 75 ms) before each word is heard, mostly lip closures that form during the silent closure. In the browser, the rig's applied `viseme_PP` follows the timeline within 10 ms of the audio clock.

## Talking rig

```js
import {TalkingRig, MOODS} from './js/talking/rig.js';

const rig = new TalkingRig({audioContext, camera});
rig.attach(model);                        // a loaded (and posed) avatar scene
const clip = await (await fetch('/api/speech/say', {method: 'POST',
  headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text, voice: 'bf_emma'})})).json();
const buffer = await audioContext.decodeAudioData(await (await fetch(clip.audio_url)).arrayBuffer());
rig.setMood('happy', 0.6);
await rig.speak(buffer, clip.timeline);   // resolves when the clip ends or rig.stop() is called
// every frame:
rig.update(dt); renderer.render(scene, camera);
```

- **Audio clock**: the mouth is sampled at the time being heard: `AudioContext.getOutputTimestamp()` (which includes the output latency) or `currentTime - outputLatency`. Dropped frames never desynchronise the mouth. `rig.options.offset` (seconds) shifts the mouth for unusual audio paths (Bluetooth headsets).
- **Mixing**: lip closures win (other visemes are scaled down while `PP` or `FF` is strongly active, and the lips part quickly when a closure releases), the total viseme weight is limited to 1, and open sounds add some `jawOpen` (the MakeHuman viseme targets barely move the jaw) up to a cap (`options.jawCap`, 0.42) that counts the opening the visemes already make, so jaw and visemes never stack into an over-open mouth. A short attack/release filter (18 ms / 45 ms) removes frame-to-frame jitter.
- **All meshes**: every morph name is written on every mesh that has it (on the kit's avatars `viseme_*` and `jawOpen` live on Body, Teeth and Tongue; blinks on Body, Eyebrows and Eyelashes; gaze on Body, Eyes, Eyebrows and Eyelashes).
- **Eyes**: blinks every 2.5 to 6 s (sometimes double, less often with wide eyes), gaze toward the camera through the `eyeLook*` shapes, small fixational saccades and the occasional glance away.
- **Idle**: breathing on `spine_02`/`spine_03` and the clavicles, slow head and neck motion (livelier while speaking) with small nods on longer words. Bones are animated relative to the pose captured at `attach()` (call `rig.captureRest()` after changing the base pose).
- **Moods**: `neutral`, `happy`, `sad`, `angry`, `surprised` as ARKit presets with an intensity from 0 to 1, eased in over about 0.25 s. While speaking, the mood's mouth shapes are reduced so the visemes stay readable; brows, eyes, cheeks and the smile remain.
- **Without audio**: `rig.pose(timeline, t)` shows the face at time `t` of a timeline (for captures or engines that play the audio themselves).

The demo page exposes `window.talk` for automation (`ready`, `selectAvatar(slug)`, `setCamera(id)`, `say(text, {voice, speed})`, `speak(text)`, `setMood(name, intensity)`, `freeze(true)`, `renderAt(clip, t)`, `step(dt, n)`, `snapshot()`), and keeps `#avatar=<slug>&camera=<preset>&voice=<id>&mood=<name>` in the URL.

## Tests

```sh
python -m pytest tests/test_speech.py
```

The conversion and server tests use a fake TTS engine and need neither network nor PyTorch; the real Kokoro test runs only after `python -m tak speech setup`.

## Limitations

- Kokoro's phoneme durations describe the synthesised audio, not a recording; other TTS engines need their own timing source.
- Visemes are the 15 Oculus classes: tongue positions (for example `l` against `n`) and lip rounding within a class are not distinguished.
- Japanese and Mandarin timelines have one word per synthesised chunk (their G2P reports no word tokens); the phonemes are timed individually.
- Korean is not covered by Kokoro.
