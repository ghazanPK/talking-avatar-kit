// Reference render capture and the Renders view (side-by-side comparison).
import * as THREE from 'three';
import {api} from './api.js';
import {$, el} from './dom.js';
import {CAMERA_PRESETS} from './viewport.js';

const SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;
const CELL = 256;

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('image decode failed'));
    image.src = url;
  });
}

// Render every pose from every camera preset and save the PNGs, a contact
// sheet (sheet.png) and index.json under build/renders/<slug>/<label>/.
export async function captureReferenceSet({viewport, rig, sheet, avatar, label = 'reference', size = 1024, onProgress = () => {}}) {
  if (!viewport.model || !rig) throw new Error('Load an avatar first');
  if (!SEGMENT.test(label)) throw new Error('Label: use letters, digits, ".", "_" or "-"');
  if (!SEGMENT.test(avatar.slug)) throw new Error(`Avatar slug "${avatar.slug}" cannot be used as a folder name`);
  const cameras = (sheet.cameras || CAMERA_PRESETS.map(p => p.id)).filter(id => CAMERA_PRESETS.some(p => p.id === id));
  const poses = sheet.poses || [];
  const morphs = viewport.morphNames().map(name => [name, viewport.morphValue(name)]);
  viewport.resetMorphs();
  const total = poses.length * cameras.length;
  const images = [], reports = {};
  const contact = document.createElement('canvas');
  const labelWidth = 150, headHeight = 28;
  contact.width = labelWidth + cameras.length * CELL;
  contact.height = headHeight + poses.length * CELL;
  const ctx = contact.getContext('2d');
  ctx.fillStyle = '#15181d';
  ctx.fillRect(0, 0, contact.width, contact.height);
  ctx.fillStyle = '#e3e6eb';
  ctx.font = '600 15px system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  cameras.forEach((id, i) => ctx.fillText(CAMERA_PRESETS.find(p => p.id === id)?.label || id, labelWidth + i * CELL + 10, headHeight / 2));
  let done = 0;
  try {
    for (const [row, pose] of poses.entries()) {
      reports[pose.id] = rig.apply(pose);
      ctx.fillStyle = '#e3e6eb';
      ctx.fillText(pose.label || pose.id, 10, headHeight + row * CELL + CELL / 2);
      for (const [column, cameraId] of cameras.entries()) {
        const {url, camera} = viewport.captureImage(cameraId, size, size);
        const name = `${pose.id}__${cameraId}`;
        await api.saveRender({slug: avatar.slug, label, name, data_url: url});
        images.push({pose: pose.id, camera: cameraId, file: `${name}.png`, view: camera});
        const image = await loadImage(url);
        ctx.drawImage(image, labelWidth + column * CELL, headHeight + row * CELL, CELL, CELL);
        onProgress(++done / total, `${pose.label || pose.id} / ${cameraId}`);
      }
    }
    await api.saveRender({slug: avatar.slug, label, name: 'sheet', data_url: contact.toDataURL('image/png')});
    const index = {
      schema: 1,
      slug: avatar.slug,
      label,
      avatar: {id: avatar.id, name: avatar.name, glb_url: avatar.glb_url, bytes: avatar.bytes,
        sha256: avatar.manifest?.sha256 || avatar.manifest?.file_sha256 || null},
      created: new Date().toISOString(),
      renderer: {three: THREE.REVISION, tone_mapping: viewport.settings.toneMapping, exposure: viewport.settings.exposure,
        environment: viewport.settings.environment, background: viewport.settings.background, width: size, height: size},
      pose_sheet: sheet.id || 'reference',
      poses: poses.map(p => ({id: p.id, label: p.label || p.id, report: reports[p.id]})),
      cameras,
      images,
      sheet: 'sheet.png',
    };
    await api.saveRender({slug: avatar.slug, label, name: 'index', json: index});
    return {count: images.length, folder: `build/renders/${avatar.slug}/${label}/`, index};
  } finally {
    for (const [name, value] of morphs) viewport.setMorph(name, value);
  }
}

export class RendersView {
  constructor() {
    this.a = $('#render-set-a');
    this.b = $('#render-set-b');
    this.grid = $('#render-grid');
    this.sets = [];
    this.a.addEventListener('change', () => this.render());
    this.b.addEventListener('change', () => this.render());
    $('#renders-refresh').addEventListener('click', () => this.load());
  }

  async load(prefer) {
    try {
      this.sets = (await api.renders()).sets;
    } catch (error) {
      this.grid.replaceChildren(el('p', {class: 'hint', text: error.message}));
      return;
    }
    const key = s => `${s.slug}/${s.label}`;
    const previousA = prefer || this.a.value, previousB = this.b.value;
    this.a.replaceChildren(...this.sets.map(s => el('option', {value: key(s), text: key(s)})));
    this.b.replaceChildren(el('option', {value: '', text: '(none)'}), ...this.sets.map(s => el('option', {value: key(s), text: key(s)})));
    if (this.sets.some(s => key(s) === previousA)) this.a.value = previousA;
    else if (this.sets.length) this.a.value = key(this.sets.reduce((x, y) => (y.modified || 0) > (x.modified || 0) ? y : x));
    if (this.sets.some(s => key(s) === previousB)) this.b.value = previousB;
    this.render();
  }

  find(value) { return this.sets.find(s => `${s.slug}/${s.label}` === value); }

  render() {
    const a = this.find(this.a.value), b = this.find(this.b.value);
    if (!a) {
      this.grid.replaceChildren(el('p', {class: 'hint', text: 'No render sets yet. Load an avatar and use Capture reference set in the Viewer.'}));
      return;
    }
    const index = a.index || {};
    const poses = index.poses?.map(p => p.id) || [...new Set(a.files.filter(f => f.includes('__')).map(f => f.split('__')[0]))];
    const cameras = index.cameras || [...new Set(a.files.filter(f => f.includes('__')).map(f => f.split('__')[1].replace(/\.png$/, '')))];
    const label = id => index.poses?.find(p => p.id === id)?.label || id;
    const cell = (set, file) => set.files.includes(file)
      ? el('figure', {}, el('a', {href: set.url + file, target: '_blank', rel: 'noopener'}, el('img', {src: `${set.url}${file}?v=${Math.round(set.modified || 0)}`, alt: `${set.label} ${file}`, loading: 'lazy'})), b ? el('figcaption', {text: set.label}) : null)
      : el('div', {class: 'missing', text: 'missing'});
    const head = el('tr', {}, el('th', {text: ''}), ...cameras.map(c => el('th', {text: CAMERA_PRESETS.find(p => p.id === c)?.label || c})));
    const rows = poses.map(pose => el('tr', {}, el('th', {text: label(pose)}), ...cameras.map(camera => {
      const file = `${pose}__${camera}.png`;
      return el('td', {}, el('div', {class: 'pair'}, cell(a, file), b ? cell(b, file) : null));
    })));
    const meta = index.created ? el('p', {class: 'hint', text: `${a.slug}/${a.label}: ${index.images?.length ?? a.files.length} images, ${index.renderer?.width}x${index.renderer?.height}, three r${index.renderer?.three}, ${index.created}`}) : null;
    this.grid.replaceChildren(...[meta, el('table', {}, head, ...rows)].filter(Boolean));
  }
}
