// Settings form and tool check.
import {api} from './api.js';
import {$, el, setStatus} from './dom.js';

function valueCell(value) {
  if (value === true) return el('span', {class: 'badge ok', text: 'yes'});
  if (value === false) return el('span', {class: 'badge bad', text: 'no'});
  if (value === null || value === undefined || value === '') return el('span', {class: 'hint', text: '-'});
  if (Array.isArray(value)) {
    if (value.every(v => v === null || typeof v !== 'object')) return value.join(', ') || '-';
    return el('div', {}, ...value.map(v => table(v)));
  }
  if (typeof value === 'object') return table(value);
  return String(value);
}

function table(object) {
  if (object === null || typeof object !== 'object') return valueCell(object);
  return el('table', {}, ...Object.entries(object).map(([key, value]) => el('tr', {}, el('th', {text: key}), el('td', {}, valueCell(value)))));
}

export class SettingsView {
  constructor({onSaved, jobs}) {
    this.form = $('#settings-form');
    this.onSaved = onSaved || (() => {});
    this.jobs = jobs;
    this.form.addEventListener('submit', event => { event.preventDefault(); this.save(); });
    $('#check-run').addEventListener('click', () => this.check());
    $('#setup-run').addEventListener('click', () => this.jobs.start({kind: 'setup'}));
  }

  async load() {
    try {
      const data = await api.settings();
      this.fill(data);
      return data.settings;
    } catch (error) {
      setStatus(`Settings: ${error.message}`, {error: true});
      return null;
    }
  }

  fill(data) {
    $('#settings-path').textContent = data.path;
    for (const [key, value] of Object.entries(data.settings)) {
      const input = this.form.elements[key];
      if (input) input.value = Array.isArray(value) ? value.join('\n') : value ?? '';
    }
  }

  async save() {
    const values = {};
    for (const key of ['blender_path', 'mpfb_profile_dir', 'packs_dir']) values[key] = this.form.elements[key].value;
    values.extra_avatar_dirs = this.form.elements.extra_avatar_dirs.value.split('\n').map(s => s.trim()).filter(Boolean);
    try {
      const data = await api.saveSettings(values);
      this.fill(data);
      $('#settings-saved').textContent = `Saved ${new Date().toLocaleTimeString()}`;
      this.onSaved(data.settings);
    } catch (error) {
      $('#settings-saved').textContent = error.message;
    }
  }

  async check() {
    const out = $('#check-result');
    out.replaceChildren(el('p', {class: 'hint', text: 'Checking tools (this runs blender --version)...'}));
    $('#check-run').disabled = true;
    try {
      const report = await api.check();
      const parts = [];
      const blender = report.studio?.blender || {};
      parts.push(el('h3', {text: 'Studio discovery'}), table({
        platform: report.studio?.platform,
        python: `${report.studio?.python?.version ?? ''} (${report.studio?.python?.executable ?? ''})`,
        'blender found': Boolean(blender.found),
        'blender path': blender.path,
        'found through': blender.source,
        'blender version': blender.version,
        'windows program from WSL': blender.windows_exe_from_wsl,
      }));
      if (blender.candidates?.length) {
        parts.push(el('h3', {text: 'Blender candidates'}), el('table', {}, ...blender.candidates.map(c =>
          el('tr', {}, el('th', {text: c.source}), el('td', {}, c.exists ? el('span', {class: 'badge ok', text: 'found'}) : el('span', {class: 'badge', text: 'missing'}), ' ', c.path)))));
      }
      parts.push(el('h3', {text: 'Avatar pipeline (python -m tak check)'}));
      if (report.message) parts.push(el('p', {class: 'hint', text: report.message}));
      if (report.check) parts.push(table(report.check));
      if (report.stderr) parts.push(el('pre', {class: 'job-lines', text: report.stderr}));
      out.replaceChildren(...parts);
    } catch (error) {
      out.replaceChildren(el('p', {class: 'hint', text: error.message}));
    } finally {
      $('#check-run').disabled = false;
    }
  }
}
