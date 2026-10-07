// Studio entry point: wires the library, viewport, inspector, capture,
// renders, settings and job panels together.
//
// URL hash parameters (also used for scripted screenshots):
//   #view=viewer|renders|settings&avatar=<id>&camera=<preset>&pose=<pose id>&tab=morphs|pose|capture
// window.studio exposes the same actions for automation.
import {api} from './api.js';
import {$, $$, el, formatBytes, setStatus} from './dom.js';
import {Viewport, CAMERA_PRESETS, TONE_MAPPINGS, BACKGROUNDS} from './viewport.js';
import {PoseRig, loadJSON} from './rig.js';
import {MorphInspector, PoseList} from './inspector.js';
import {JobPanel} from './jobs.js';
import {SettingsView} from './settings.js';
import {captureReferenceSet, RendersView} from './capture.js';

const state = {avatars: [], current: null, rig: null, rigDesc: null, sheet: null, pose: 'bind', view: 'viewer', tab: 'morphs', pipeline: false};
const hash = () => Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
function writeHash() {
  const params = new URLSearchParams({view: state.view});
  if (state.current) params.set('avatar', state.current.id);
  if (viewport?.preset) params.set('camera', viewport.preset);
  if (state.pose && state.pose !== 'bind') params.set('pose', state.pose);
  if (state.tab !== 'morphs') params.set('tab', state.tab);
  history.replaceState(null, '', `#${params}`);
}

// ------------------------------------------------------------------ viewport
let viewport;
try {
  viewport = new Viewport($('#viewport'), {onChange: event => {
    if (event.type === 'camera') {
      for (const b of $$('#camera-bar button')) b.classList.toggle('active', b.dataset.preset === event.preset);
      writeHash();
    }
  }});
} catch (error) {
  showMessage(`WebGL is not available in this browser: ${error.message}`);
  throw error;
}
const morphs = new MorphInspector(viewport);
const poses = new PoseList({onSelect: id => applyPose(id)});
const jobs = new JobPanel({onFinished: job => { setStatus(`Job ${job.kind} ${job.status}`); if (job.kind === 'build') loadAvatars(); }});
const renders = new RendersView();
const settingsView = new SettingsView({jobs, onSaved: () => loadAvatars()});

function showMessage(text) {
  const node = $('#viewport-message');
  node.hidden = !text;
  node.textContent = text || '';
}

// Camera bar and view options
$('#camera-bar').append(...CAMERA_PRESETS.map(p => el('button', {
  type: 'button', dataset: {preset: p.id}, title: `${p.label} (key ${p.key})`, onclick: () => viewport.setPreset(p.id),
}, p.label)));
$('#tone-mapping').append(...Object.entries(TONE_MAPPINGS).map(([id, t]) => el('option', {value: id, text: t.label})));
$('#background').append(...Object.entries(BACKGROUNDS).map(([id, b]) => el('option', {value: id, text: b.label})));
const optionInputs = {toneMapping: '#tone-mapping', exposure: '#exposure', background: '#background', skeleton: '#skeleton', grid: '#grid'};
function syncOptions() {
  for (const [key, selector] of Object.entries(optionInputs)) {
    const input = $(selector);
    if (input.type === 'checkbox') input.checked = viewport.settings[key];
    else input.value = viewport.settings[key];
  }
}
for (const [key, selector] of Object.entries(optionInputs)) {
  $(selector).addEventListener('input', event => {
    const input = event.target;
    viewport.applySettings({[key]: input.type === 'checkbox' ? input.checked : input.type === 'range' ? Number(input.value) : input.value});
  });
}
syncOptions();

window.addEventListener('keydown', event => {
  if (event.target.closest('input, textarea, select') || event.ctrlKey || event.metaKey || event.altKey) return;
  const preset = CAMERA_PRESETS.find(p => p.key === event.key);
  if (preset && state.view === 'viewer') viewport.setPreset(preset.id);
  if (event.key === 's' && state.view === 'viewer') { viewport.applySettings({skeleton: !viewport.settings.skeleton}); syncOptions(); }
});

// ------------------------------------------------------------------ views and tabs
function setView(view) {
  state.view = ['viewer', 'renders', 'settings'].includes(view) ? view : 'viewer';
  for (const b of $$('.views button')) b.classList.toggle('active', b.dataset.view === state.view);
  for (const s of $$('main .view')) s.classList.toggle('active', s.id === `view-${state.view}`);
  if (state.view === 'renders') renders.load();
  if (state.view === 'viewer') viewport.resize();
  writeHash();
}
for (const b of $$('.views button')) b.addEventListener('click', () => setView(b.dataset.view));

function setTab(tab) {
  state.tab = ['morphs', 'pose', 'capture'].includes(tab) ? tab : 'morphs';
  for (const b of $$('.tabs button')) b.classList.toggle('active', b.dataset.tab === state.tab);
  for (const t of $$('.inspector .tab')) t.classList.toggle('active', t.dataset.tab === state.tab);
  writeHash();
}
for (const b of $$('.tabs button')) b.addEventListener('click', () => setTab(b.dataset.tab));

// ------------------------------------------------------------------ library
function avatarCard(avatar) {
  const m = avatar.manifest || {};
  const bones = m.bone_count ?? m.bones?.length ?? m.rig?.bone_count;
  const morphCount = m.morph_target_count ?? m.morph_targets?.length ?? m.face?.morph_target_count;
  const thumb = el('span', {class: 'avatar-thumb', text: avatar.preview_url ? '' : avatar.name.slice(0, 1).toUpperCase()});
  if (avatar.preview_url) thumb.style.backgroundImage = `url("${avatar.preview_url}")`;
  const badges = [];
  if (avatar.source !== 'avatars') badges.push(el('span', {class: 'badge', title: avatar.location, text: 'extra'}));
  if (avatar.manifest_error) badges.push(el('span', {class: 'badge bad', title: avatar.manifest_error, text: 'bad manifest'}));
  else if (!avatar.manifest) badges.push(el('span', {class: 'badge warn', text: 'no manifest'}));
  if (!avatar.glb_url) badges.push(el('span', {class: 'badge warn', text: 'not built'}));
  const sub = [avatar.slug, formatBytes(avatar.bytes), bones ? `${bones} bones` : '', morphCount ? `${morphCount} morphs` : ''].filter(Boolean).join(' / ');
  const card = el('button', {type: 'button', class: `avatar-card${state.current?.id === avatar.id ? ' active' : ''}`, dataset: {id: avatar.id},
    disabled: !avatar.glb_url, onclick: () => selectAvatar(avatar.id)},
  thumb, el('span', {class: 'avatar-meta'}, el('div', {class: 'avatar-name', text: avatar.name}), el('div', {class: 'avatar-sub', text: sub}), el('div', {}, badges)));
  const actions = avatar.source === 'avatars' && avatar.has_spec
    ? el('div', {class: 'avatar-actions'}, el('button', {type: 'button', title: `python -m tak build ${avatar.slug}`, onclick: () => jobs.start({kind: 'build', slug: avatar.slug})}, 'Build'))
    : null;
  return el('li', {}, card, actions);
}

async function loadAvatars() {
  try {
    const {avatars} = await api.avatars();
    state.avatars = avatars;
  } catch (error) {
    setStatus(error.message, {error: true});
    state.avatars = [];
  }
  const list = $('#avatar-list');
  if (!state.avatars.length) {
    list.replaceChildren(el('li', {class: 'empty'},
      'No avatars found. Build one with ', el('code', {text: 'python -m tak build <slug>'}),
      ', place a GLB at ', el('code', {text: 'avatars/<slug>/<slug>.glb'}),
      ', or add a folder under Settings > Extra avatar folders.'));
  } else {
    list.replaceChildren(...state.avatars.map(avatarCard));
  }
  $('#build-all').disabled = !state.avatars.some(a => a.has_spec);
  return state.avatars;
}

async function selectAvatar(id) {
  const avatar = state.avatars.find(a => a.id === id);
  if (!avatar?.glb_url) { setStatus(`Avatar ${id} not found`, {error: true}); return false; }
  state.current = avatar;
  for (const card of $$('.avatar-card')) card.classList.toggle('active', card.dataset.id === id);
  showMessage(`Loading ${avatar.name}...`);
  setStatus(`Loading ${avatar.name}`, {sticky: true});
  writeHash();
  try {
    const result = await viewport.load(avatar.glb_url, {name: avatar.slug});
    if (!result) return false;
    state.rig = new PoseRig(viewport.model, state.rigDesc, viewport.avatarRoot);
    const s = result.stats;
    $('#avatar-info').replaceChildren(el('strong', {text: avatar.name}), ` ${s.height.toFixed(2)} m / ${s.bones} bones / ${s.morphTargets} morph targets / ${s.meshes} meshes / ${Math.round(s.triangles).toLocaleString()} triangles / ${s.materials} materials / ${s.loadMs} ms`,
      state.rig.matches() ? '' : el('span', {class: 'badge warn', text: 'unknown rig: poses may be partial'}));
    morphs.build();
    applyPose(state.pose, {quiet: true});
    showMessage('');
    setStatus(`${avatar.name} loaded`);
    return true;
  } catch (error) {
    showMessage(`Could not load ${avatar.glb_url}: ${error.message}`);
    setStatus(`Load failed: ${error.message}`, {error: true});
    return false;
  }
}

function applyPose(id, {quiet = false} = {}) {
  const pose = state.sheet?.poses?.find(p => p.id === id) || state.sheet?.poses?.[0];
  if (!pose) return null;
  state.pose = pose.id;
  const report = state.rig ? state.rig.apply(pose) : null;
  poses.setActive(pose.id, report);
  if (state.rig) viewport.setPreset(viewport.preset);
  if (!quiet) setStatus(`Pose: ${pose.label || pose.id}`);
  writeHash();
  return report;
}

$('#refresh-avatars').addEventListener('click', () => loadAvatars());
$('#build-all').addEventListener('click', () => jobs.start({kind: 'build', all: true}));

// ------------------------------------------------------------------ capture
async function captureSet({label = $('#capture-label').value.trim(), size = Number($('#capture-size').value)} = {}) {
  if (!state.current || !state.rig) throw new Error('Load an avatar first');
  const button = $('#capture-run'), bar = $('#capture-progress'), result = $('#capture-result');
  button.disabled = true; bar.hidden = false; result.textContent = '';
  const keepPose = state.pose;
  try {
    const out = await captureReferenceSet({viewport, rig: state.rig, sheet: state.sheet, avatar: state.current, label, size,
      onProgress: (fraction, text) => { bar.firstElementChild.style.width = `${Math.round(fraction * 100)}%`; result.textContent = text; }});
    result.replaceChildren(`Saved ${out.count} images and a contact sheet to `, el('code', {text: out.folder}), '. ',
      el('a', {href: '#', onclick: event => { event.preventDefault(); setView('renders'); renders.load(`${state.current.slug}/${label}`); }}, 'Open in Renders'));
    setStatus(`Captured ${out.count} reference images`);
    return out;
  } catch (error) {
    result.textContent = `Capture failed: ${error.message}`;
    setStatus(`Capture failed: ${error.message}`, {error: true});
    throw error;
  } finally {
    button.disabled = false;
    applyPose(keepPose, {quiet: true});
  }
}
$('#capture-run').addEventListener('click', () => captureSet().catch(() => {}));

// ------------------------------------------------------------------ start
async function start() {
  [state.rigDesc, state.sheet] = await Promise.all([loadJSON('rigs/mpfb-game-engine.json'), loadJSON('poses/reference.json')]);
  poses.build(state.sheet);
  morphs.build();
  try {
    const info = await api.info();
    state.pipeline = info.pipeline_available;
    if (!info.pipeline_available) $('#build-all').title = 'The avatar pipeline (tak.pipeline) is not installed in this checkout';
  } catch (error) {
    setStatus(error.message, {error: true});
  }
  await Promise.all([loadAvatars(), settingsView.load()]);
  jobs.refresh();
  const params = hash();
  if (params.camera && CAMERA_PRESETS.some(p => p.id === params.camera)) viewport.preset = params.camera;
  if (params.pose) state.pose = params.pose;
  setTab(params.tab);
  setView(params.view);
  const initial = state.avatars.find(a => a.id === params.avatar) || state.avatars.find(a => a.glb_url);
  if (initial) await selectAvatar(initial.id);
  else showMessage('No avatar loaded. Build or add an avatar; see the library on the left.');
}

const ready = start().catch(error => { setStatus(error.message, {error: true}); showMessage(error.message); throw error; });

window.studio = {
  ready,
  state,
  viewport,
  loadAvatars,
  selectAvatar,
  setCamera: id => viewport.setPreset(id),
  applyPose,
  setView,
  setTab,
  setMorph: (name, value) => morphs.set(name, value),
  resetMorphs: () => morphs.reset(),
  setViewOptions: options => { viewport.applySettings(options); syncOptions(); },
  captureReferenceSet: captureSet,
  checkTools: () => settingsView.check(),
  jobs,
};
