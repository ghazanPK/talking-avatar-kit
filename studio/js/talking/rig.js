// Talking rig: lip-sync, blinks, gaze, idle motion and moods for avatars
// with the 15 Oculus viseme_* morph targets and the 52 ARKit blendshapes
// (MPFB game_engine skeleton for the idle motion; other skeletons simply get
// no body motion).
//
//   const rig = new TalkingRig({audioContext, camera});
//   rig.attach(model);                       // after the GLB is loaded and posed
//   await rig.speak(audioBuffer, timeline);  // timeline from POST /api/speech/say
//   rig.stop(); rig.setMood('happy', 0.6);
//   rig.update(dt);                           // every frame, before rendering
//
// The viseme track is driven by the audio clock (AudioContext), not by frame
// time, so the mouth follows what is heard even when frames are dropped.
// Each morph name is written on every mesh that has it (Body, Teeth, Tongue,
// Eyelashes, Eyebrows, Eyes ...), so teeth and tongue move with the lips.
import * as THREE from 'three';

export const VISEMES = ['sil', 'PP', 'FF', 'TH', 'DD', 'kk', 'CH', 'SS', 'nn', 'RR', 'aa', 'E', 'I', 'O', 'U'];

// The MPFB/MakeHuman viseme targets move the lips but open the jaw only a
// little, so open sounds add some jawOpen. OPENNESS is how far each viseme
// already opens the mouth in jawOpen units; the jaw added on top is capped so
// stacked shapes never exceed jawCap (no jaw drop on top of an open viseme).
const OPENNESS = {aa: 0.15, O: 0.12, E: 0.1, I: 0.06, U: 0.05, RR: 0.04, CH: 0.04, kk: 0.05, DD: 0.04, nn: 0.04, SS: 0.03, TH: 0.05, FF: 0.02, PP: 0};
const JAW_EXTRA = {aa: 0.3, O: 0.22, E: 0.16, I: 0.1, U: 0.08, kk: 0.09, DD: 0.07, nn: 0.07, RR: 0.08, CH: 0.06, TH: 0.08, SS: 0.03};
const CLOSURES = ['PP', 'FF']; // shapes that need lip contact win over open shapes

// Mood presets (ARKit names; *Left/*Right pairs written as one entry with
// the 'LR' suffix). Values are for intensity 1.
const MOOD_PRESETS = {
  neutral: {},
  // The MakeHuman face units are subtle, so the presets use most of their range.
  happy: {mouthSmileLR: 0.9, cheekSquintLR: 0.55, eyeSquintLR: 0.3, mouthDimpleLR: 0.3, browOuterUpLR: 0.12, mouthUpperUpLR: 0.1},
  sad: {browInnerUp: 1, browDownLR: 0.2, mouthFrownLR: 0.75, mouthShrugLower: 0.35, eyeSquintLR: 0.15, eyeLookDownLR: 0.15, mouthPressLR: 0.15},
  angry: {browDownLR: 1, eyeSquintLR: 0.45, mouthPressLR: 0.45, noseSneerLR: 0.5, mouthRollLower: 0.15, mouthFrownLR: 0.25, jawForward: 0.08},
  surprised: {browInnerUp: 0.95, browOuterUpLR: 0.9, eyeWideLR: 0.75, jawOpen: 0.12, mouthFunnel: 0.1},
};
export const MOODS = Object.keys(MOOD_PRESETS);
// Mouth channels of a mood are reduced while speaking: the visemes own the lips.
const MOUTH_CHANNEL = /^(jaw|mouth(Funnel|Pucker|Press|Roll|Shrug|Close|LowerDown|UpperUp|Stretch))/;

function expand(preset, intensity) {
  const out = {};
  for (const [name, value] of Object.entries(preset)) {
    if (name.endsWith('LR')) { const base = name.slice(0, -2); out[`${base}Left`] = value * intensity; out[`${base}Right`] = value * intensity; }
    else out[name] = value * intensity;
  }
  return out;
}
export function moodChannels(name = 'neutral', intensity = 1) {
  return expand(MOOD_PRESETS[name] || {}, Math.max(0, Math.min(1, intensity)));
}

const smoothstep = x => { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); };
export function blinkCurve(t) {
  if (!(t >= 0)) return 0;
  if (t < 0.07) return smoothstep(t / 0.07);
  if (t < 0.1) return 1;
  return t < 0.24 ? 1 - smoothstep((t - 0.1) / 0.14) : 0;
}

// Piecewise-linear sample of timeline.keys at time t (same as tak/speech/visemes.py sample()).
export function sampleKeys(keys, t) {
  const out = {};
  for (const [name, pts] of Object.entries(keys || {})) {
    if (!pts.length || t <= pts[0][0] || t >= pts[pts.length - 1][0]) continue;
    let lo = 0, hi = pts.length - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (pts[mid][0] <= t) lo = mid; else hi = mid; }
    const [t0, w0] = pts[lo], [t1, w1] = pts[hi];
    const w = w0 + (w1 - w0) * (t - t0) / Math.max(1e-9, t1 - t0);
    if (w > 1e-4) out[name] = w;
  }
  return out;
}

// Closure priority, total-weight normalisation and the jaw stacking cap.
export function mixVisemes(raw, {jawCap = 0.42} = {}) {
  const w = {};
  for (const v of VISEMES) { const x = raw[`viseme_${v}`] || 0; if (x > 0) w[v] = Math.min(1, x); }
  // Squared, so a closure that is only starting or ending leaves the vowel visible.
  const closure = Math.max(w.PP || 0, w.FF || 0);
  if (closure > 0) for (const v of Object.keys(w)) if (!CLOSURES.includes(v)) w[v] *= 1 - 0.85 * closure * closure;
  const total = Object.values(w).reduce((a, b) => a + b, 0);
  if (total > 1) for (const v of Object.keys(w)) w[v] /= total;
  let open = 0, jaw = 0;
  for (const [v, x] of Object.entries(w)) { open += x * (OPENNESS[v] || 0); jaw += x * (JAW_EXTRA[v] || 0); }
  jaw = Math.max(0, Math.min(jaw, jawCap - open));
  const out = {};
  for (const [v, x] of Object.entries(w)) out[`viseme_${v}`] = x;
  if (jaw > 1e-4) out.jawOpen = jaw;
  return out;
}

// Random number generator with a seed, so captures are repeatable.
function rng(seed = 1) {
  let s = seed >>> 0 || 1;
  return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
}

const BONES = {spine: ['spine_02', 'spine_03'], neck: 'neck_01', head: 'head', clavicles: ['clavicle_l', 'clavicle_r']};

export class TalkingRig {
  constructor({audioContext = null, camera = null, seed = 7, gain = 1} = {}) {
    this.ctx = audioContext;
    this.camera = camera;
    this.random = rng(seed);
    this.gain = gain;
    this.model = null;
    this.morphs = new Map();      // name -> [{mesh, index}]
    this.values = new Map();      // name -> smoothed value written last frame
    this.bones = {};
    this.rest = new Map();        // bone -> rest quaternion (captured at attach)
    this.mood = {name: 'neutral', intensity: 0};
    this.moodCurrent = {};
    this.options = {lipSync: true, blink: true, gaze: true, idle: true, saccades: true, attack: 0.018, release: 0.045,
      jawCap: 0.42, offset: 0, visemeGain: 1};
    this.clip = null;             // {source, start, timeline, resolve}
    this.manualTime = null;       // fixed speech time for deterministic captures
    this.time = 0;
    this.blink = {next: 1.2, start: -1, double: false};
    this.saccade = {next: 0.5, x: 0, y: 0, tx: 0, ty: 0};
    this.headImpulse = 0;
    this.wordIndex = 0;
    this.last = {};
  }

  // ------------------------------------------------------------------ setup
  attach(model) {
    this.detach();
    this.model = model;
    model.traverse(o => {
      if (!o.isMesh || !o.morphTargetDictionary || !o.morphTargetInfluences) return;
      for (const [name, index] of Object.entries(o.morphTargetDictionary)) {
        if (!this.morphs.has(name)) this.morphs.set(name, []);
        this.morphs.get(name).push({mesh: o, index});
      }
    });
    const bone = name => { const b = model.getObjectByName(name); return b?.isBone ? b : null; };
    this.bones = {
      spine: BONES.spine.map(bone).filter(Boolean),
      neck: bone(BONES.neck), head: bone(BONES.head),
      clavicles: BONES.clavicles.map(bone).filter(Boolean),
    };
    this.captureRest();
    return this.report();
  }

  // Call again after changing the base pose.
  captureRest() {
    this.rest.clear();
    for (const b of [...this.bones.spine, this.bones.neck, this.bones.head, ...this.bones.clavicles]) if (b) this.rest.set(b, b.quaternion.clone());
  }

  report() {
    const meshes = name => (this.morphs.get(name) || []).map(t => t.mesh.name);
    return {
      visemes: VISEMES.filter(v => this.morphs.has(`viseme_${v}`)).length,
      arkit: [...this.morphs.keys()].filter(n => !n.startsWith('viseme_')).length,
      meshes: {viseme_aa: meshes('viseme_aa'), jawOpen: meshes('jawOpen'), eyeBlinkLeft: meshes('eyeBlinkLeft')},
      bones: {spine: this.bones.spine.length, neck: !!this.bones.neck, head: !!this.bones.head},
    };
  }

  detach() {
    this.stop();
    if (this.model) {
      for (const targets of this.morphs.values()) for (const {mesh, index} of targets) mesh.morphTargetInfluences[index] = 0;
      for (const [b, q] of this.rest) b.quaternion.copy(q);
    }
    this.model = null;
    this.morphs.clear();
    this.values.clear();
    this.rest.clear();
  }

  // ------------------------------------------------------------------ speech
  get speaking() { return Boolean(this.clip); }

  // Time in the current clip as heard: the AudioContext output timestamp
  // when available (includes output latency), else currentTime minus latency.
  audioTime() {
    if (this.manualTime !== null) return this.manualTime;
    if (!this.clip || !this.ctx) return null;
    let now = this.ctx.currentTime - (this.ctx.outputLatency || this.ctx.baseLatency || 0);
    const ts = this.ctx.getOutputTimestamp?.();
    if (ts && ts.contextTime > 0 && ts.performanceTime > 0) now = ts.contextTime + (performance.now() - ts.performanceTime) / 1000;
    // Output timestamps arrive in blocks and can step back by a few ms; never
    // move the mouth backwards within a clip.
    const t = now - this.clip.start + this.options.offset;
    const last = this.clip.lastTime ?? -Infinity;
    this.clip.lastTime = t < last && last - t < 0.05 ? last : t;
    return this.clip.lastTime;
  }

  speak(audioBuffer, timeline, {delay = 0.06} = {}) {
    this.stop();
    if (!this.ctx) throw new Error('TalkingRig needs an AudioContext to play audio');
    const source = this.ctx.createBufferSource();
    source.buffer = audioBuffer;
    const gain = this.ctx.createGain();
    gain.gain.value = this.gain;
    source.connect(gain).connect(this.ctx.destination);
    const start = this.ctx.currentTime + delay;
    return new Promise(resolve => {
      const clip = {source, start, timeline, resolve, duration: audioBuffer.duration};
      this.clip = clip;
      this.wordIndex = 0;
      source.onended = () => { if (this.clip === clip) this.finish('ended'); };
      source.start(start);
    });
  }

  // Play a timeline without audio at a given time (captures, tests, engines
  // that play the audio themselves): rig.pose(timeline, t).
  pose(timeline, t) {
    if (!this.clip || this.clip.timeline !== timeline) {
      this.stop();
      this.clip = {source: null, start: 0, timeline, resolve: () => {}, duration: timeline.duration};
    }
    this.manualTime = t;
  }

  stop() { if (this.clip) this.finish('stopped'); this.manualTime = null; }

  finish(reason) {
    const clip = this.clip;
    this.clip = null;
    if (clip?.source) { clip.source.onended = null; try { clip.source.stop(); } catch { /* not started */ } }
    clip?.resolve({reason});
  }

  setMood(name, intensity = 0.7) {
    this.mood = {name: MOOD_PRESETS[name] ? name : 'neutral', intensity: Math.max(0, Math.min(1, Number(intensity) || 0))};
  }

  // ------------------------------------------------------------------ frame
  update(dt) {
    if (!this.model) return;
    dt = Math.max(0, Math.min(0.1, dt || 0));
    this.time += dt;
    const o = this.options, target = {};
    const add = (name, v) => { if (v > 0) target[name] = Math.max(target[name] || 0, v); };

    // Mood, eased in and out.
    const goal = moodChannels(this.mood.name, this.mood.intensity);
    const k = 1 - Math.exp(-dt / 0.25);
    for (const name of new Set([...Object.keys(goal), ...Object.keys(this.moodCurrent)])) {
      const v = (this.moodCurrent[name] || 0) + ((goal[name] || 0) - (this.moodCurrent[name] || 0)) * k;
      if (v > 1e-4) this.moodCurrent[name] = v; else delete this.moodCurrent[name];
    }

    // Visemes from the audio clock.
    let mouth = {}, t = null;
    if (this.clip) {
      t = this.audioTime();
      const tl = this.clip.timeline;
      if (o.lipSync && tl && t !== null) mouth = mixVisemes(sampleKeys(tl.keys, t), {jawCap: o.jawCap});
      if (tl?.words && t !== null) {
        while (this.wordIndex < tl.words.length && tl.words[this.wordIndex].start <= t) {
          const w = tl.words[this.wordIndex++];
          if (w.end - w.start > 0.22) this.headImpulse = Math.min(1, this.headImpulse + 0.6);
        }
      }
    }
    const speakingNow = Object.keys(mouth).length > 0 || (this.clip && t !== null && t >= 0 && t < this.clip.duration);
    for (const [name, v] of Object.entries(this.moodCurrent)) add(name, speakingNow && MOUTH_CHANNEL.test(name) ? v * 0.35 : v);
    for (const [name, v] of Object.entries(mouth)) target[name] = Math.min(1, (target[name] || 0) * (name === 'jawOpen' ? 0.5 : 1) + v * o.visemeGain);

    // Blinks: 2.5-6 s apart, sometimes double; wide eyes blink less.
    if (o.blink) {
      const b = this.blink;
      if (this.time >= b.next) {
        b.start = this.time;
        const wide = (this.moodCurrent.eyeWideLeft || 0) > 0.3;
        b.next = this.time + (this.random() < 0.15 ? 0.3 : (2.5 + this.random() * 3.5) * (wide ? 1.6 : 1));
      }
      const blink = blinkCurve(this.time - b.start);
      if (blink > 0) for (const side of ['Left', 'Right']) {
        target[`eyeBlink${side}`] = Math.max(target[`eyeBlink${side}`] || 0, blink);
        if (target[`eyeWide${side}`]) target[`eyeWide${side}`] *= 1 - blink;
      }
    }

    // Gaze toward the camera plus small saccades.
    if (o.gaze) this.gaze(target, dt);

    // Write every channel we control; smoothing with attack/release.
    const att = 1 - Math.exp(-dt / o.attack), rel = 1 - Math.exp(-dt / o.release);
    const names = new Set([...this.values.keys(), ...Object.keys(target)]);
    for (const name of names) {
      if (!this.morphs.has(name)) continue;
      const prev = this.values.get(name) || 0, goalValue = target[name] || 0;
      // Lip-sync channels follow the (already smooth, anticipatory) curves
      // closely; blinks and gaze are applied directly.
      const fast = name.startsWith('eyeBlink') || name.startsWith('eyeLook');
      // Lips part quickly at the release of a closure.
      const release = name === 'viseme_PP' || name === 'viseme_FF' ? att : rel;
      const value = fast || dt === 0 ? goalValue : prev + (goalValue - prev) * (goalValue > prev ? att : release);
      if (value < 1e-4 && !target[name]) { this.values.delete(name); this.write(name, 0); continue; }
      this.values.set(name, value);
      this.write(name, value);
    }
    this.last = {time: t, target};

    if (o.idle) this.idle(dt, speakingNow);
  }

  write(name, value) {
    for (const {mesh, index} of this.morphs.get(name) || []) mesh.morphTargetInfluences[index] = value;
  }

  gaze(target, dt) {
    const s = this.saccade;
    if (this.options.saccades && this.time >= s.next) {
      // Small fixational saccades (a few degrees), occasionally a glance away.
      const away = this.random() < 0.08;
      s.tx = (this.random() - 0.5) * (away ? 0.5 : 0.12);
      s.ty = (this.random() - 0.5) * (away ? 0.3 : 0.08);
      s.next = this.time + (away ? 0.6 : 0.5 + this.random() * 2.2);
    }
    const k = 1 - Math.exp(-dt / 0.035); // saccades are fast
    s.x += (s.tx - s.x) * k; s.y += (s.ty - s.y) * k;
    let yaw = s.x, pitch = s.y;
    const head = this.bones.head;
    if (this.camera && head) {
      // Direction to the camera in the avatar frame (+x left, +y up, +z forward).
      const dir = this.camera.getWorldPosition(new THREE.Vector3()).sub(head.getWorldPosition(new THREE.Vector3()));
      const root = new THREE.Quaternion();
      this.model.getWorldQuaternion(root);
      dir.applyQuaternion(root.invert()).normalize();
      yaw += Math.atan2(dir.x, dir.z);
      pitch += Math.atan2(dir.y, Math.hypot(dir.x, dir.z)) - 0.05;
    }
    // About 30 degrees of eye rotation per unit morph weight.
    const range = 0.52;
    const h = Math.max(-1, Math.min(1, yaw / range)), v = Math.max(-1, Math.min(1, pitch / range));
    // Positive yaw = looking toward the avatar's left (+x).
    if (h > 0) { target.eyeLookOutLeft = h; target.eyeLookInRight = h; }
    else if (h < 0) { target.eyeLookInLeft = -h; target.eyeLookOutRight = -h; }
    if (v > 0) { target.eyeLookUpLeft = v; target.eyeLookUpRight = v; }
    else if (v < 0) { target.eyeLookDownLeft = Math.max(target.eyeLookDownLeft || 0, -v); target.eyeLookDownRight = Math.max(target.eyeLookDownRight || 0, -v); }
  }

  idle(dt, speaking) {
    const t = this.time;
    this.headImpulse *= Math.exp(-dt / 0.35);
    const set = (bone, x, y, z) => {
      const rest = this.rest.get(bone);
      if (!rest) return;
      bone.quaternion.copy(rest).multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(x, y, z)));
    };
    // Breathing: about 15 breaths per minute, chest pitch and a slight shoulder lift.
    const breath = Math.sin(t * Math.PI * 2 / 4.2);
    this.bones.spine.forEach((b, i) => set(b, -0.012 * breath * (i + 1) / this.bones.spine.length, 0, 0));
    this.bones.clavicles.forEach(b => set(b, 0, 0, 0.006 * Math.max(0, breath) * (b.name.endsWith('_l') ? 1 : -1)));
    // Head: slow wander, livelier while speaking, with small nods on longer words.
    const amp = speaking ? 1.6 : 1;
    const nx = 0.018 * amp * (Math.sin(t * 0.61) * 0.6 + Math.sin(t * 1.37 + 1.2) * 0.4) + 0.035 * this.headImpulse;
    const ny = 0.03 * amp * (Math.sin(t * 0.43 + 0.5) * 0.7 + Math.sin(t * 1.11) * 0.3);
    const nz = 0.012 * amp * Math.sin(t * 0.53 + 2.0);
    if (this.bones.neck) set(this.bones.neck, nx * 0.4, ny * 0.4, nz * 0.4);
    if (this.bones.head) set(this.bones.head, nx * 0.6, ny * 0.6, nz * 0.6);
  }
}
