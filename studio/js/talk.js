// Talking demo page (/talk/): pick an avatar, type text, choose a Kokoro
// voice, speed and mood, and the avatar speaks it with lip-sync, blinks, gaze
// and idle motion. Speech comes from the local server (POST /api/speech/say).
//
// URL hash: #avatar=<slug>&camera=face|upper|full&voice=<id>&mood=<name>
// window.talk exposes the same actions for automation (see docs/talking.md).
import {$, el, setStatus} from './dom.js';
import {Viewport} from './viewport.js';
import {PoseRig, loadJSON} from './rig.js';
import {TalkingRig, MOODS} from './talking/rig.js';

const CAMERAS = [{id: 'face', label: 'Face'}, {id: 'upper', label: 'Upper body'}, {id: 'full', label: 'Full body'}];
// Arms resting at the sides (operations as in poses/reference.json).
const STANDING_POSE = {id: 'standing', ops: [
  {op: 'aim', bone: 'upperarm_l', dir: [0.2, -0.975, 0.06], mirror: true},
  {op: 'aim', bone: 'lowerarm_l', dir: [0.1, -0.96, 0.24], mirror: true},
  {op: 'palm', hand: 'hand_l', normal: [-0.95, 0, -0.25], mirror: true},
  {op: 'curl', hand: 'hand_l', fingers: ['index', 'middle', 'ring', 'pinky'], angles: [14, 20, 10], mirror: true},
]};

async function request(method, path, body) {
  const options = {method, cache: 'no-store', headers: {}};
  if (body !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
  const response = await fetch(path, options);
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = {error: text}; }
  if (!response.ok) throw new Error(data?.error || `HTTP ${response.status}`);
  return data;
}

const hash = Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
const state = {avatars: [], current: null, speech: null, voices: [], rigDesc: null, clip: null, camera: hash.camera || 'face'};
let audioContext = null;
const viewport = new Viewport($('#viewport'));
viewport.applySettings({shadows: true});
const rig = new TalkingRig({camera: viewport.camera});

function message(text) { const n = $('#viewport-message'); n.hidden = !text; n.textContent = text || ''; }
function writeHash() {
  const p = new URLSearchParams();
  if (state.current) p.set('avatar', state.current.slug);
  p.set('camera', state.camera);
  p.set('voice', $('#voice').value);
  if ($('#mood').value !== 'neutral') p.set('mood', $('#mood').value);
  history.replaceState(null, '', `#${p}`);
}

// ------------------------------------------------------------------ camera
$('#camera-bar').append(...CAMERAS.map(c => el('button', {type: 'button', dataset: {preset: c.id}, onclick: () => setCamera(c.id)}, c.label)));
function setCamera(id) {
  state.camera = CAMERAS.some(c => c.id === id) ? id : 'face';
  viewport.setPreset(state.camera);
  if (state.camera === 'face' && viewport.metrics) {
    // Centre on the eyes and mouth rather than chin to crown.
    const lift = -0.07 * viewport.metrics.scale;
    viewport.camera.position.y += lift;
    viewport.controls.target.y += lift;
    viewport.camera.position.lerp(viewport.controls.target, 0.12);
    viewport.controls.update();
  }
  for (const b of $('#camera-bar').children) b.classList.toggle('active', b.dataset.preset === state.camera);
  writeHash();
}

// ------------------------------------------------------------------ avatars
async function selectAvatar(slug) {
  const avatar = state.avatars.find(a => a.slug === slug) || state.avatars[0];
  if (!avatar) { message('No avatars found in avatars/.'); return false; }
  stop();
  state.current = avatar;
  $('#avatar').value = avatar.slug;
  message(`Loading ${avatar.name}...`);
  const result = await viewport.load(avatar.glb_url, {name: avatar.slug});
  if (!result) return false;
  const pose = new PoseRig(viewport.model, state.rigDesc, viewport.avatarRoot);
  if (pose.matches()) pose.apply(STANDING_POSE);
  const report = rig.attach(viewport.model);
  setCamera(state.camera);
  $('#avatar-info').textContent = `${avatar.name}: ${report.visemes}/15 visemes, ${report.arkit} ARKit shapes; visemes on ${report.meshes.viseme_aa.join(', ') || 'no mesh'}`;
  message(report.visemes ? '' : 'This avatar has no viseme_* morph targets: no lip-sync.');
  writeHash();
  return true;
}

// ------------------------------------------------------------------ speech
async function loadSpeech() {
  try {
    state.speech = await request('GET', '/api/speech/status');
  } catch (error) {
    state.speech = {available: false, reason: error.message};
  }
  const {voices, default: fallback} = await request('GET', '/api/speech/voices').catch(() => ({voices: [], default: 'af_heart'}));
  state.voices = voices;
  const groups = new Map();
  for (const v of voices) {
    if (!groups.has(v.language_name)) groups.set(v.language_name, el('optgroup', {label: v.language_name}));
    groups.get(v.language_name).append(el('option', {value: v.id, text: `${v.label.split(' (')[0]} (${v.gender})`}));
  }
  $('#voice').replaceChildren(...groups.values());
  $('#voice').value = voices.some(v => v.id === hash.voice) ? hash.voice : fallback;
  const ok = state.speech.available;
  $('#speech-missing').hidden = ok;
  $('#speech-reason').textContent = ok ? '' : (state.speech.reason || '');
  $('#speak').disabled = !ok;
  if (ok && !state.speech.weights_downloaded) $('#speech-info').textContent = 'The first sentence downloads the Kokoro model (about 330 MB) into .tak/models/.';
}

async function say(text, {voice = $('#voice').value, speed = Number($('#speed').value)} = {}) {
  setStatus('Synthesising...', {sticky: true});
  const clip = await request('POST', '/api/speech/say', {text, voice, speed});
  audioContext ||= new AudioContext();
  rig.ctx = audioContext;
  const bytes = await (await fetch(clip.audio_url, {cache: 'no-store'})).arrayBuffer();
  clip.buffer = await audioContext.decodeAudioData(bytes);
  state.clip = clip;
  const tl = clip.timeline;
  $('#speech-info').textContent = `${tl.duration.toFixed(2)} s, ${tl.words.length} words, ${tl.phonemes.length} phonemes${clip.cached ? ' (cached)' : clip.synthesis_seconds ? `, synthesised in ${clip.synthesis_seconds.toFixed(1)} s` : ''}`;
  $('#words').replaceChildren(...tl.words.map((w, i) => el('span', {dataset: {i}, title: `${w.start.toFixed(2)}-${w.end.toFixed(2)} s  /${w.phonemes}/`}, w.text)));
  setStatus('');
  return clip;
}

async function speak(text = $('#text').value, options = {}) {
  const button = $('#speak');
  button.disabled = true;
  try {
    const clip = await say(text, options);
    if (audioContext.state === 'suspended') await audioContext.resume();
    setStatus('Speaking', {sticky: true});
    const done = rig.speak(clip.buffer, clip.timeline);
    const result = await done;
    setStatus(result.reason === 'ended' ? '' : 'Stopped');
    return result;
  } catch (error) {
    setStatus(error.message, {error: true});
    throw error;
  } finally {
    button.disabled = !state.speech?.available;
  }
}

function stop() { rig.stop(); for (const s of $('#words').children) s.classList.remove('on'); }

// ------------------------------------------------------------------ controls
$('#mood').append(...MOODS.map(m => el('option', {value: m, text: m[0].toUpperCase() + m.slice(1)})));
const applyMood = () => { rig.setMood($('#mood').value, Number($('#mood-intensity').value)); $('#mood-value').textContent = Number($('#mood-intensity').value).toFixed(2); writeHash(); };
$('#mood').addEventListener('input', applyMood);
$('#mood-intensity').addEventListener('input', applyMood);
$('#speed').addEventListener('input', () => { $('#speed-value').textContent = Number($('#speed').value).toFixed(2); });
$('#voice').addEventListener('input', writeHash);
$('#avatar').addEventListener('input', () => selectAvatar($('#avatar').value).catch(e => setStatus(e.message, {error: true})));
$('#speak').addEventListener('click', () => speak().catch(() => {}));
$('#stop').addEventListener('click', stop);
$('#text').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) speak().catch(() => {}); });
for (const [id, key] of [['opt-blink', 'blink'], ['opt-gaze', 'gaze'], ['opt-idle', 'idle']]) $(`#${id}`).addEventListener('input', e => { rig.options[key] = e.target.checked; });
$('#offset').addEventListener('input', e => { rig.options.offset = Number(e.target.value) / 1000; $('#offset-value').textContent = e.target.value; });

// ------------------------------------------------------------------ loop
let last = performance.now(), frozen = false;
function frame(now) {
  const dt = (now - last) / 1000;
  last = now;
  if (!frozen) {
    rig.update(dt);
    const t = rig.speaking ? rig.audioTime() : null;
    if (t !== null && state.clip) for (const s of $('#words').children) {
      const w = state.clip.timeline.words[s.dataset.i];
      s.classList.toggle('on', t >= w.start && t < w.end);
    }
    viewport.render();
  }
  requestAnimationFrame(frame);
}

async function start() {
  state.rigDesc = await loadJSON('/rigs/mpfb-game-engine.json');
  const [{avatars}] = await Promise.all([request('GET', '/api/avatars'), loadSpeech()]);
  state.avatars = avatars.filter(a => a.glb_url && a.source === 'avatars');
  $('#avatar').replaceChildren(...state.avatars.map(a => el('option', {value: a.slug, text: a.name})));
  if (hash.mood && MOODS.includes(hash.mood)) { $('#mood').value = hash.mood; }
  applyMood();
  await selectAvatar(hash.avatar);
  requestAnimationFrame(frame);
}

const ready = start().catch(error => { setStatus(error.message, {error: true}); message(error.message); throw error; });

// Automation (Playwright captures, tests). freeze(true) stops the loop so
// renderAt() frames are deterministic.
window.talk = {
  ready, state, rig, viewport,
  selectAvatar, setCamera, say, speak, stop,
  setMood: (name, intensity = 0.7) => { $('#mood').value = name; $('#mood-intensity').value = intensity; applyMood(); },
  freeze: value => { frozen = value; },
  // Pose the face at speech time t of a clip (no audio) and render.
  renderAt(clip, t, {dt = 1 / 60, settle = 0} = {}) {
    rig.pose(clip.timeline, t - settle);
    for (let i = 0; i <= Math.round(settle / dt); i++) { rig.manualTime = t - settle + i * dt; rig.update(dt); }
    viewport.render();
    return {...rig.last.target};
  },
  // Advance the idle clock (blinks, gaze, breathing) by dt and render.
  step(dt = 1 / 60, n = 1) { for (let i = 0; i < n; i++) rig.update(dt); viewport.render(); return {...rig.last.target}; },
  snapshot: () => viewport.renderer.domElement.toDataURL('image/png'),
};
