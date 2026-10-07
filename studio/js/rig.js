// Pose sheets on a loaded avatar.
//
// Poses are written with the bone names of one rig description
// (studio/rigs/<id>.json). A bone is looked up by its own name first and
// then through the rig's canonical (Unity humanoid) name, so a pose sheet
// keeps working when the skeleton is renamed to the canonical form.
//
// Every operation works in world space in the avatar frame (+x the avatar's
// left, +y up, +z the avatar's forward), not in the bones' local axes, so the
// same sheet applies to skeletons with different bind orientations.
import * as THREE from 'three';

const DEG = Math.PI / 180;
const UP = new THREE.Vector3(0, 1, 0);
const vec = a => new THREE.Vector3(Number(a[0]) || 0, Number(a[1]) || 0, Number(a[2]) || 0);
const worldPos = o => o.getWorldPosition(new THREE.Vector3());
const worldQuat = o => o.getWorldQuaternion(new THREE.Quaternion());

export async function loadJSON(url) {
  const response = await fetch(url, {cache: 'no-store'});
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

// Expand "mirror": true into a left and a right operation.
export function expandMirror(ops, desc) {
  const left = desc?.mirror?.left ?? '_l', right = desc?.mirror?.right ?? '_r';
  const swap = name => typeof name === 'string' && name.endsWith(left) ? name.slice(0, -left.length) + right : name;
  const polar = v => Array.isArray(v) ? [-v[0], v[1], v[2]] : v;
  const axial = v => Array.isArray(v) ? [v[0], -v[1], -v[2]] : v;
  const out = [];
  for (const op of ops || []) {
    const {mirror, ...base} = op;
    out.push(base);
    if (!mirror) continue;
    const m = structuredClone(base);
    for (const key of ['bone', 'hand']) if (m[key]) m[key] = swap(m[key]);
    if (Array.isArray(m.chain)) m.chain = m.chain.map(swap);
    if (m.target?.bone) m.target.bone = swap(m.target.bone);
    if (m.dir) m.dir = polar(m.dir);
    if (m.normal) m.normal = polar(m.normal);
    if (m.axis) m.axis = axial(m.axis);
    out.push(m);
  }
  return out;
}

export class PoseRig {
  constructor(model, desc, frame = model) {
    this.model = model;
    this.desc = desc || {canonical: {}, hands: {}};
    this.frame = frame;
    this.byName = new Map();
    this.bind = new Map();
    model.traverse(o => {
      if (!o.isBone) return;
      if (!this.byName.has(o.name)) this.byName.set(o.name, o);
      this.bind.set(o, o.quaternion.clone());
    });
  }

  get boneCount() { return this.bind.size; }

  bone(name) {
    if (!name) return null;
    if (this.byName.has(name)) return this.byName.get(name);
    const sanitized = THREE.PropertyBinding.sanitizeNodeName(name);
    if (this.byName.has(sanitized)) return this.byName.get(sanitized);
    const canonical = this.desc.canonical?.[name];
    if (canonical && this.byName.has(canonical)) return this.byName.get(canonical);
    return null;
  }

  // True when the model looks like the rig this description was written for.
  matches() {
    const names = Object.keys(this.desc.canonical || {});
    return names.length > 0 && names.filter(n => this.bone(n)).length >= names.length * 0.8;
  }

  reset() {
    for (const [bone, q] of this.bind) bone.quaternion.copy(q);
    this.model.updateMatrixWorld(true);
  }

  toWorld(v) {
    return vec(v).applyQuaternion(worldQuat(this.frame)).normalize();
  }

  // Direction a bone points in, in world space.
  boneDir(bone) {
    const kids = bone.children.filter(o => o.isBone);
    if (kids.length === 1) {
      const d = worldPos(kids[0]).sub(worldPos(bone));
      if (d.lengthSq() > 1e-12) return d.normalize();
    }
    return UP.clone().applyQuaternion(worldQuat(bone)).normalize();
  }

  segmentLength(bone) {
    const kids = bone.children.filter(o => o.isBone);
    if (kids.length === 1) return worldPos(kids[0]).distanceTo(worldPos(bone));
    if (bone.parent?.isBone) return worldPos(bone).distanceTo(worldPos(bone.parent));
    return 0.03;
  }

  tip(bone) {
    return worldPos(bone).addScaledVector(this.boneDir(bone), this.segmentLength(bone) * 0.85);
  }

  applyWorldDelta(bone, delta) {
    const parent = bone.parent ? worldQuat(bone.parent) : new THREE.Quaternion();
    bone.quaternion.premultiply(parent.clone().invert().multiply(delta).multiply(parent));
    bone.updateMatrixWorld(true);
  }

  rotateWorld(bone, axis, angle) {
    if (!angle || axis.lengthSq() < 1e-12) return;
    this.applyWorldDelta(bone, new THREE.Quaternion().setFromAxisAngle(axis.clone().normalize(), angle));
  }

  aim(bone, dir) {
    const current = this.boneDir(bone);
    if (dir.lengthSq() < 1e-12) return;
    this.applyWorldDelta(bone, new THREE.Quaternion().setFromUnitVectors(current, dir.clone().normalize()));
  }

  hand(name) {
    const info = this.desc.hands?.[name];
    const bone = this.bone(name);
    if (!info || !bone) return null;
    const fingers = {};
    for (const [finger, chain] of Object.entries(info.fingers || {})) {
      const bones = chain.map(n => this.bone(n));
      if (bones.every(Boolean)) fingers[finger] = bones;
    }
    return {bone, side: info.side, fingers};
  }

  // Normal pointing out of the palm (the side the fingers curl toward).
  palmNormal(hand) {
    const {bone, side, fingers} = hand;
    const middle = fingers.middle?.[0], index = fingers.index?.[0], pinky = fingers.pinky?.[0];
    if (!middle || !index || !pinky) return null;
    const along = worldPos(middle).sub(worldPos(bone));
    const across = worldPos(index).sub(worldPos(pinky));
    const n = new THREE.Vector3().crossVectors(along, across).multiplyScalar(side === 'left' ? 1 : -1);
    return n.lengthSq() > 1e-12 ? n.normalize() : null;
  }

  handScale(hand) {
    const middle = hand.fingers.middle?.[0];
    return middle ? worldPos(middle).distanceTo(worldPos(hand.bone)) / 0.115 : 1;
  }

  // Twist forearm and wrist so the palm normal turns toward ``target``.
  turnPalm(hand, target) {
    const fore = hand.bone.parent?.isBone ? hand.bone.parent : null;
    if (!fore) return false;
    const twist = (bone, share) => {
      const normal = this.palmNormal(hand);
      if (!normal) return;
      const axis = worldPos(hand.bone).sub(worldPos(fore));
      if (axis.lengthSq() < 1e-12) return;
      axis.normalize();
      const p = normal.clone().addScaledVector(axis, -normal.dot(axis));
      const q = target.clone().addScaledVector(axis, -target.dot(axis));
      if (p.lengthSq() < 1e-10 || q.lengthSq() < 1e-10) return;
      const angle = Math.atan2(axis.dot(new THREE.Vector3().crossVectors(p, q)), p.dot(q)) * share;
      this.rotateWorld(bone, axis, angle);
    };
    twist(fore, 0.6);
    twist(hand.bone, 1);
    return true;
  }

  reach(chain, target, iterations = 24, maxStep = 25 * DEG) {
    const end = chain[chain.length - 1];
    for (let iter = 0; iter < iterations; iter++) {
      for (let i = chain.length - 1; i >= 0; i--) {
        const bone = chain[i], origin = worldPos(bone);
        const from = this.tip(end).sub(origin), to = target.clone().sub(origin);
        if (from.lengthSq() < 1e-12 || to.lengthSq() < 1e-12) continue;
        const q = new THREE.Quaternion().setFromUnitVectors(from.normalize(), to.normalize());
        const angle = 2 * Math.acos(Math.min(1, Math.abs(q.w)));
        if (angle > maxStep) q.slerp(new THREE.Quaternion(), 1 - maxStep / angle);
        this.applyWorldDelta(bone, q);
      }
      if (this.tip(end).distanceTo(target) < 0.0015) break;
    }
  }

  // Apply a pose ({ops: [...]}) on top of the bind pose. Returns a report.
  apply(pose) {
    this.reset();
    const missing = new Set(), skipped = [];
    let applied = 0;
    const need = name => { const b = this.bone(name); if (!b) missing.add(name); return b; };
    const needHand = name => { const h = this.hand(name); if (!h) missing.add(name); return h; };
    for (const op of expandMirror(pose?.ops, this.desc)) {
      try {
        switch (op.op) {
          case 'aim': { const b = need(op.bone); if (b) { this.aim(b, this.toWorld(op.dir)); applied++; } break; }
          case 'rotate': { const b = need(op.bone); if (b) { this.rotateWorld(b, this.toWorld(op.axis), (op.angle || 0) * DEG); applied++; } break; }
          case 'palm': { const h = needHand(op.hand); if (h && this.turnPalm(h, this.toWorld(op.normal))) applied++; break; }
          case 'flat': {
            const h = needHand(op.hand); if (!h) break;
            const n = this.palmNormal(h); if (!n) break;
            for (const finger of op.fingers || []) {
              const chain = h.fingers[finger]; if (!chain) { missing.add(`${op.hand}:${finger}`); continue; }
              const d = this.boneDir(chain[0]);
              this.aim(chain[0], d.addScaledVector(n, -d.dot(n)));
              for (let k = 1; k < chain.length; k++) this.aim(chain[k], this.boneDir(chain[k - 1]));
            }
            applied++; break;
          }
          case 'curl': {
            const h = needHand(op.hand); if (!h) break;
            const n = this.palmNormal(h); if (!n) break;
            for (const finger of op.fingers || []) {
              const chain = h.fingers[finger]; if (!chain) { missing.add(`${op.hand}:${finger}`); continue; }
              const axis = new THREE.Vector3().crossVectors(this.boneDir(chain[0]), n);
              if (axis.lengthSq() < 1e-10) continue;
              axis.normalize();
              chain.forEach((bone, k) => this.rotateWorld(bone, axis, (op.angles?.[k] || 0) * DEG));
            }
            applied++; break;
          }
          case 'spread': {
            const h = needHand(op.hand); if (!h) break;
            const n = this.palmNormal(h), middle = h.fingers.middle?.[0]; if (!n || !middle) break;
            const mid = worldPos(middle);
            for (const [finger, angle] of Object.entries(op.angles || {})) {
              const chain = h.fingers[finger]; if (!chain || finger === 'middle') continue;
              const d = this.boneDir(chain[0]);
              const lateral = worldPos(chain[0]).sub(mid);
              lateral.addScaledVector(d, -lateral.dot(d)).addScaledVector(n, -lateral.dot(n));
              if (lateral.lengthSq() < 1e-10) continue;
              this.rotateWorld(chain[0], new THREE.Vector3().crossVectors(d, lateral), angle * DEG);
            }
            applied++; break;
          }
          case 'reach': {
            const chain = (op.chain || []).map(need);
            const tb = need(op.target?.bone);
            if (chain.some(b => !b) || !tb) break;
            const h = op.hand ? this.hand(op.hand) : null;
            const point = op.target.tip ? this.tip(tb) : worldPos(tb);
            if (h && op.target.palm) {
              const n = this.palmNormal(h);
              if (n) point.addScaledVector(n, op.target.palm * this.handScale(h));
            }
            this.reach(chain, point);
            applied++; break;
          }
          default: skipped.push(op.op);
        }
      } catch (error) {
        skipped.push(`${op.op}: ${error.message}`);
      }
      this.model.updateMatrixWorld(true);
    }
    return {pose: pose?.id, applied, missing: [...missing], skipped};
  }
}
