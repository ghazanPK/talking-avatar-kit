// Job log panel: lists jobs and streams the selected job's lines.
import {api} from './api.js';
import {$, el, setStatus} from './dom.js';

const ACTIVE = new Set(['queued', 'running']);

function describeLine(line) {
  const j = line.json;
  if (j && 'result' in j) return {cls: 'result', text: `result ${JSON.stringify(j.result)}`};
  if (j && ('stage' in j || 'message' in j)) {
    const pct = typeof j.progress === 'number' ? ` (${Math.round(j.progress * 100)}%)` : '';
    return {cls: 'stage', text: `[${j.stage ?? ''}] ${j.message ?? ''}${pct}`};
  }
  return {cls: line.stream === 'stderr' ? 'stderr' : '', text: line.raw};
}

export class JobPanel {
  constructor({onFinished} = {}) {
    this.root = $('#joblog');
    this.list = $('#job-list');
    this.lines = $('#job-lines');
    this.summary = $('#joblog-summary');
    this.cancel = $('#job-cancel');
    this.onFinished = onFinished || (() => {});
    this.jobs = [];
    this.selected = null;
    this.offset = 0;
    this.timer = 0;
    this.known = new Map();
    $('#joblog-toggle').addEventListener('click', () => this.toggle());
    this.cancel.addEventListener('click', () => this.cancelSelected());
  }

  toggle(open = this.root.classList.contains('collapsed')) {
    this.root.classList.toggle('collapsed', !open);
    $('#joblog-toggle').setAttribute('aria-expanded', String(open));
    window.dispatchEvent(new Event('resize'));
  }

  async start(payload) {
    try {
      const job = await api.startJob(payload);
      setStatus(job.warning || `Started ${job.kind} job ${job.id}`, {error: Boolean(job.warning)});
      this.toggle(true);
      this.select(job.id);
      await this.refresh();
      return job;
    } catch (error) {
      setStatus(`Could not start job: ${error.message}`, {error: true});
      return null;
    }
  }

  async refresh() {
    clearTimeout(this.timer);
    try {
      const {jobs} = await api.jobs();
      this.jobs = jobs;
      for (const job of jobs) {
        const before = this.known.get(job.id);
        if (before && ACTIVE.has(before) && !ACTIVE.has(job.status)) this.onFinished(job);
        this.known.set(job.id, job.status);
      }
      this.renderList();
      if (this.selected) await this.pull();
    } catch (error) {
      this.summary.textContent = error.message;
    }
    const busy = this.jobs.some(j => ACTIVE.has(j.status));
    this.timer = setTimeout(() => this.refresh(), busy ? 800 : 5000);
  }

  renderList() {
    const running = this.jobs.filter(j => ACTIVE.has(j.status)).length;
    this.summary.textContent = this.jobs.length ? `${this.jobs.length} job(s)${running ? `, ${running} active` : ''}` : 'No jobs yet';
    this.list.replaceChildren(...this.jobs.map(job => {
      const label = job.params?.slug ? `${job.kind} ${job.params.slug}` : job.params?.all ? `${job.kind} --all` : job.kind;
      const pct = typeof job.progress === 'number' ? job.progress : (job.status === 'succeeded' ? 1 : 0);
      return el('li', {}, el('button', {type: 'button', class: job.id === this.selected ? 'active' : null, onclick: () => this.select(job.id)},
        el('span', {}, el('b', {text: label}), ' ', el('span', {class: `st-${job.status}`, text: job.status})),
        el('span', {class: 'hint', text: job.message || job.stage || job.error || ''}),
        el('div', {class: 'bar'}, el('div', {style: {width: `${Math.round(pct * 100)}%`}}))));
    }));
    const selected = this.jobs.find(j => j.id === this.selected);
    this.cancel.hidden = !selected || !ACTIVE.has(selected.status);
  }

  select(id) {
    this.selected = id;
    this.offset = 0;
    this.lines.replaceChildren();
    delete this.lines.dataset.done;
    this.renderList();
    this.pull();
  }

  async pull() {
    if (!this.selected) return;
    const id = this.selected;
    try {
      const detail = await api.job(id, this.offset);
      if (id !== this.selected) return;
      if (this.offset === 0) this.lines.append(el('span', {class: 'hint', text: `$ ${detail.command.join(' ')}\n`}));
      const stick = this.lines.scrollTop + this.lines.clientHeight >= this.lines.scrollHeight - 8;
      for (const line of detail.lines) {
        const {cls, text} = describeLine(line);
        this.lines.append(el('span', {class: cls || null, text: `${text}\n`}));
      }
      this.offset = detail.next_offset;
      if (!ACTIVE.has(detail.status) && !this.lines.dataset.done) {
        this.lines.dataset.done = id;
        this.lines.append(el('span', {class: `st-${detail.status}`, text: `-- ${detail.status}${detail.returncode !== null ? ` (exit ${detail.returncode})` : ''}${detail.error ? `: ${detail.error}` : ''}\n`}));
      }
      if (stick) this.lines.scrollTop = this.lines.scrollHeight;
    } catch (error) {
      this.lines.append(el('span', {class: 'stderr', text: `${error.message}\n`}));
    }
  }

  async cancelSelected() {
    if (!this.selected) return;
    try { await api.cancelJob(this.selected); } catch (error) { setStatus(error.message, {error: true}); }
    this.refresh();
  }
}
