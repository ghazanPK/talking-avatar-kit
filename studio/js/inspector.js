// Morph-target inspector and pose list.
import {$, el} from './dom.js';

const GROUPS = [
  {id: 'viseme', label: 'Visemes', test: n => /^viseme_/i.test(n)},
  {id: 'brow', label: 'Brows', test: n => /^brow/i.test(n)},
  {id: 'eye', label: 'Eyes', test: n => /^eye/i.test(n)},
  {id: 'cheek', label: 'Cheeks and nose', test: n => /^(cheek|nose)/i.test(n)},
  {id: 'jaw', label: 'Jaw', test: n => /^jaw/i.test(n)},
  {id: 'mouth', label: 'Mouth', test: n => /^mouth/i.test(n)},
  {id: 'tongue', label: 'Tongue', test: n => /^tongue/i.test(n)},
  {id: 'other', label: 'Other', test: () => true},
];

const VISEME_ORDER = ['viseme_sil', 'viseme_PP', 'viseme_FF', 'viseme_TH', 'viseme_DD', 'viseme_kk', 'viseme_CH', 'viseme_SS', 'viseme_nn', 'viseme_RR', 'viseme_aa', 'viseme_E', 'viseme_I', 'viseme_O', 'viseme_U'];

export class MorphInspector {
  constructor(viewport) {
    this.viewport = viewport;
    this.list = $('#morph-list');
    this.filter = $('#morph-filter');
    this.rows = new Map();
    this.filter.addEventListener('input', () => this.applyFilter());
    $('#morph-reset').addEventListener('click', () => this.reset());
  }

  build() {
    this.list.replaceChildren();
    this.rows.clear();
    const names = this.viewport.morphNames();
    if (!names.length) {
      this.list.append(el('p', {class: 'hint', text: this.viewport.model ? 'This avatar has no morph targets.' : 'Load an avatar to inspect its morph targets.'}));
      return;
    }
    const grouped = new Map(GROUPS.map(g => [g.id, []]));
    for (const name of names) grouped.get(GROUPS.find(g => g.test(name)).id).push(name);
    grouped.get('viseme').sort((a, b) => (VISEME_ORDER.indexOf(a) + 1 || 99) - (VISEME_ORDER.indexOf(b) + 1 || 99));
    for (const group of GROUPS) {
      const items = grouped.get(group.id);
      if (!items.length) continue;
      const details = el('details', {class: 'morph-group', open: group.id === 'viseme' || group.id === 'mouth' || group.id === 'eye'},
        el('summary', {}, el('b', {text: group.label}), ` (${items.length})`));
      for (const name of items) {
        const output = el('output', {text: '0.00'});
        const input = el('input', {type: 'range', min: 0, max: 1, step: 0.01, value: this.viewport.morphValue(name), 'aria-label': name});
        const row = el('label', {class: 'morph-row', title: name}, el('span', {text: name}), input, output);
        const update = () => {
          const value = Number(input.value);
          this.viewport.setMorph(name, value);
          output.textContent = value.toFixed(2);
          row.classList.toggle('nonzero', value > 0);
        };
        input.addEventListener('input', update);
        this.rows.set(name, {row, input, output, details});
        details.append(row);
      }
      this.list.append(details);
    }
    this.applyFilter();
  }

  set(name, value) {
    const entry = this.rows.get(name);
    this.viewport.setMorph(name, value);
    if (entry) {
      entry.input.value = value;
      entry.output.textContent = Number(value).toFixed(2);
      entry.row.classList.toggle('nonzero', value > 0);
      entry.details.open = true;
    }
  }

  reset() {
    this.viewport.resetMorphs();
    for (const {input, output, row} of this.rows.values()) {
      input.value = 0; output.textContent = '0.00'; row.classList.remove('nonzero');
    }
  }

  applyFilter() {
    const q = this.filter.value.trim().toLowerCase();
    for (const [name, {row, details}] of this.rows) {
      row.hidden = q && !name.toLowerCase().includes(q);
      if (q) details.open = true;
    }
  }
}

export class PoseList {
  constructor({onSelect}) {
    this.list = $('#pose-list');
    this.report = $('#pose-report');
    this.onSelect = onSelect;
    this.active = 'bind';
  }

  build(sheet) {
    this.list.replaceChildren(...(sheet?.poses || []).map(pose => el('button', {
      type: 'button', dataset: {pose: pose.id}, class: pose.id === this.active ? 'active' : null,
      onclick: () => this.onSelect(pose.id),
    }, pose.label || pose.id)));
  }

  setActive(id, report) {
    this.active = id;
    for (const button of this.list.querySelectorAll('button')) button.classList.toggle('active', button.dataset.pose === id);
    if (!report) { this.report.textContent = ''; return; }
    const parts = [`${report.applied} operations applied`];
    if (report.missing.length) parts.push(`missing bones: ${report.missing.join(', ')}`);
    if (report.skipped.length) parts.push(`skipped: ${report.skipped.join(', ')}`);
    this.report.textContent = parts.join('; ');
  }
}
