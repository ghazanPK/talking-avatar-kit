// 3D viewport: physically based rendering, tone mapping, image-based
// lighting from RoomEnvironment, soft shadows, camera presets, skeleton view,
// morph targets and deterministic offscreen captures.
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';

export const TONE_MAPPINGS = {
  agx: {label: 'AgX', value: THREE.AgXToneMapping},
  aces: {label: 'ACES Filmic', value: THREE.ACESFilmicToneMapping},
  neutral: {label: 'Khronos Neutral', value: THREE.NeutralToneMapping},
  none: {label: 'None (linear)', value: THREE.NoToneMapping},
};

export const BACKGROUNDS = {
  slate: {label: 'Slate', color: 0x2b3038, floor: 0x3a4049},
  grey: {label: 'Mid grey', color: 0x6b6e73, floor: 0x7d8086},
  light: {label: 'Light', color: 0xc9ccd1, floor: 0xd8dade},
};

export const CAMERA_PRESETS = [
  {id: 'full', label: 'Full body', key: '1'},
  {id: 'upper', label: 'Upper body', key: '2'},
  {id: 'face', label: 'Face', key: '3'},
  {id: 'hand_l', label: 'Left hand', key: '4'},
  {id: 'hand_r', label: 'Right hand', key: '5'},
];

const worldPos = o => o.getWorldPosition(new THREE.Vector3());

export class Viewport {
  constructor(container, {onChange} = {}) {
    this.container = container;
    this.onChange = onChange || (() => {});
    this.settings = {toneMapping: 'agx', exposure: 1.0, environment: 0.7, keyLight: 2.4, background: 'slate', grid: false, skeleton: false, shadows: true};

    const renderer = this.renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.configureRenderer(renderer);
    Object.assign(renderer.domElement.style, {display: 'block', width: '100%', height: '100%'});
    renderer.domElement.setAttribute('aria-label', '3D viewport');
    container.append(renderer.domElement);

    const scene = this.scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    this.envTexture = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();
    scene.environment = this.envTexture;

    this.camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);
    this.camera.position.set(0, 1, 4);
    this.controls = new OrbitControls(this.camera, renderer.domElement);
    this.controls.enableDamping = false;
    this.controls.target.set(0, 0.9, 0);
    this.controls.addEventListener('change', () => this.requestRender());

    const key = this.keyLight = new THREE.DirectionalLight(0xffffff, this.settings.keyLight);
    key.position.set(1.6, 3.6, 2.6);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.bias = -0.0002;
    key.shadow.normalBias = 0.02;
    key.shadow.radius = 5;
    scene.add(key, key.target);
    const rim = this.rimLight = new THREE.DirectionalLight(0xdde8ff, 1.1);
    rim.position.set(-2.0, 2.8, -2.6);
    scene.add(rim);

    this.floor = new THREE.Mesh(new THREE.CircleGeometry(40, 96), new THREE.MeshStandardMaterial({roughness: 0.92, metalness: 0}));
    this.floor.rotation.x = -Math.PI / 2;
    this.floor.receiveShadow = true;
    scene.add(this.floor);
    this.grid = new THREE.GridHelper(4, 16, 0x7f8a99, 0x56606d);
    this.grid.position.y = 0.001;
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.5;
    scene.add(this.grid);

    this.avatarRoot = new THREE.Group();
    this.avatarRoot.name = 'avatar-root';
    scene.add(this.avatarRoot);

    this.model = null;
    this.skeletonHelper = null;
    this.morphs = new Map();
    this.metrics = null;
    this.preset = 'full';
    this.loader = new GLTFLoader();
    this.loadToken = 0;
    this.applySettings({});

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
  }

  configureRenderer(renderer) {
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = TONE_MAPPINGS[this.settings.toneMapping].value;
    renderer.toneMappingExposure = this.settings.exposure;
    renderer.shadowMap.enabled = this.settings.shadows;
    renderer.shadowMap.type = THREE.PCFShadowMap;
  }

  applySettings(changes) {
    Object.assign(this.settings, changes);
    const s = this.settings;
    if (!TONE_MAPPINGS[s.toneMapping]) s.toneMapping = 'agx';
    if (!BACKGROUNDS[s.background]) s.background = 'slate';
    this.configureRenderer(this.renderer);
    this.scene.environmentIntensity = s.environment;
    this.keyLight.intensity = s.keyLight;
    const bg = BACKGROUNDS[s.background];
    this.scene.background = new THREE.Color(bg.color);
    // Fog in the background colour dissolves the floor edge into the backdrop;
    // it starts well behind any camera preset's subject.
    this.scene.fog = new THREE.Fog(bg.color, 9, 26);
    this.updateFog();
    this.floor.material.color.set(bg.floor);
    this.grid.visible = s.grid;
    if (this.skeletonHelper) this.skeletonHelper.visible = s.skeleton;
    this.scene.traverse(o => { if (o.material) o.material.needsUpdate = true; });
    this.requestRender();
  }

  resize() {
    const w = Math.max(1, this.container.clientWidth), h = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.requestRender();
  }

  requestRender() {
    if (this.pending) return;
    this.pending = requestAnimationFrame(() => { this.pending = 0; this.render(); });
  }

  render() {
    this.renderer.render(this.scene, this.camera);
  }

  // ---------------------------------------------------------------- loading
  async load(url, {name = ''} = {}) {
    const token = ++this.loadToken;
    const started = performance.now();
    const gltf = await this.loader.loadAsync(url);
    if (token !== this.loadToken) { dispose(gltf.scene); return null; }
    this.unload();
    const model = gltf.scene;
    model.name = name || 'avatar';
    const stats = {meshes: 0, triangles: 0, bones: 0, materials: new Set(), morphTargets: 0};
    model.traverse(o => {
      if (o.isBone) stats.bones++;
      if (!o.isMesh) return;
      stats.meshes++;
      o.castShadow = true;
      o.receiveShadow = true;
      o.frustumCulled = false;
      const index = o.geometry.index;
      stats.triangles += (index ? index.count : o.geometry.attributes.position.count) / 3;
      for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
        stats.materials.add(m);
        if (m.map) m.map.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
      }
      if (o.morphTargetDictionary && o.morphTargetInfluences) {
        for (const [morph, i] of Object.entries(o.morphTargetDictionary)) {
          if (!this.morphs.has(morph)) this.morphs.set(morph, []);
          this.morphs.get(morph).push({mesh: o, index: i});
        }
      }
    });
    stats.morphTargets = this.morphs.size;
    stats.materials = stats.materials.size;
    this.avatarRoot.add(model);
    model.updateMatrixWorld(true);
    this.model = model;
    this.skeletonHelper = new THREE.SkeletonHelper(model);
    this.skeletonHelper.visible = this.settings.skeleton;
    this.skeletonHelper.material.depthTest = false;
    this.skeletonHelper.material.linewidth = 2;
    if (this.skeletonHelper.setColors) this.skeletonHelper.setColors(new THREE.Color(0x7cf0a0), new THREE.Color(0x3fc3ff));
    this.scene.add(this.skeletonHelper);
    this.metrics = this.measure();
    // Keep the authored placement, but stand the avatar on the floor.
    if (Math.abs(this.metrics.box.min.y) > 0.03) {
      model.position.y -= this.metrics.box.min.y;
      model.updateMatrixWorld(true);
      this.metrics = this.measure();
    }
    this.fitShadow();
    stats.loadMs = Math.round(performance.now() - started);
    stats.height = this.metrics.height;
    this.stats = stats;
    this.setPreset(this.preset);
    this.onChange({type: 'loaded', stats});
    return {model, stats, animations: gltf.animations};
  }

  unload() {
    if (this.skeletonHelper) { this.scene.remove(this.skeletonHelper); this.skeletonHelper.dispose?.(); this.skeletonHelper = null; }
    if (this.model) { this.avatarRoot.remove(this.model); dispose(this.model); this.model = null; }
    this.morphs.clear();
    this.metrics = null;
    this.requestRender();
  }

  boneByName(...names) {
    if (!this.model) return null;
    for (const name of names) {
      const bone = this.model.getObjectByName(name);
      if (bone?.isBone) return bone;
    }
    return null;
  }

  // Bind-pose measurements used for the fixed cameras.
  measure() {
    const box = new THREE.Box3();
    this.model.updateMatrixWorld(true);
    this.model.traverse(o => {
      if (!o.isMesh) return;
      if (o.isSkinnedMesh) {
        o.computeBoundingBox();
        box.union(o.boundingBox.clone().applyMatrix4(o.matrixWorld));
      } else {
        box.expandByObject(o);
      }
    });
    const height = Math.max(0.3, box.max.y - Math.min(0, box.min.y));
    const head = this.boneByName('head', 'Head');
    const hips = this.boneByName('pelvis', 'Hips', 'hips');
    const neck = this.boneByName('neck_01', 'Neck', 'neck');
    const center = box.getCenter(new THREE.Vector3());
    return {
      box, height, center,
      head: head ? worldPos(head) : new THREE.Vector3(center.x, box.max.y - height * 0.07, center.z),
      neck: neck ? worldPos(neck) : null,
      hips: hips ? worldPos(hips) : new THREE.Vector3(center.x, height * 0.53, center.z),
      scale: height / 1.75,
    };
  }

  fitShadow() {
    const m = this.metrics, s = Math.max(1, m.height);
    const cam = this.keyLight.shadow.camera;
    cam.left = -1.3 * s; cam.right = 1.3 * s; cam.top = 1.6 * s; cam.bottom = -1.3 * s;
    cam.near = 0.1; cam.far = 12 * s;
    this.keyLight.position.set(m.center.x + 1.6 * s, 3.6 * s, m.center.z + 2.6 * s);
    this.keyLight.target.position.set(m.center.x, m.height * 0.45, m.center.z);
    this.keyLight.target.updateMatrixWorld();
    cam.updateProjectionMatrix();
  }

  // ---------------------------------------------------------------- cameras
  // Full body, upper body and face are fixed per avatar (bind-pose metrics);
  // hand close-ups follow the hand in the current pose.
  cameraFor(id, aspect = 1) {
    const m = this.metrics;
    if (!m) return {position: new THREE.Vector3(0, 1, 4), target: new THREE.Vector3(0, 0.9, 0), fov: 30};
    const fov = 30, s = m.scale;
    // Distance at which a box of halfHeight x halfWidth around target fills the view.
    const fit = (target, halfHeight, dir, halfWidth = halfHeight) => {
      const t = Math.tan(fov * Math.PI / 360);
      const distance = Math.max(halfHeight / t, halfWidth / (t * Math.max(0.1, aspect)));
      return {target, position: target.clone().addScaledVector(dir.normalize(), distance), fov};
    };
    const front = new THREE.Vector3(0, 0, 1);
    switch (id) {
      case 'upper': {
        const top = m.box.max.y + 0.04 * s, bottom = m.hips.y - 0.06 * s;
        return fit(new THREE.Vector3(m.center.x, (top + bottom) / 2, m.center.z), (top - bottom) * 0.62, new THREE.Vector3(0, 0.08, 1));
      }
      case 'face': {
        // The head bone sits at the skull base; frame chin to crown.
        const target = m.head.clone().add(new THREE.Vector3(0, 0.075 * s, 0.03 * s));
        return fit(target, 0.2 * s, new THREE.Vector3(0, 0.02, 1));
      }
      case 'hand_l':
      case 'hand_r': {
        const side = id === 'hand_l' ? 'l' : 'r';
        const hand = this.boneByName(`hand_${side}`, side === 'l' ? 'LeftHand' : 'RightHand');
        const middle = this.boneByName(`middle_01_${side}`, side === 'l' ? 'LeftMiddleProximal' : 'RightMiddleProximal');
        let target = m.center.clone();
        if (hand) target = worldPos(hand);
        if (hand && middle) target.lerp(worldPos(middle), 0.75);
        const sign = side === 'l' ? 1 : -1;
        return fit(target, 0.15 * s, new THREE.Vector3(0.35 * sign, 0.18, 1));
      }
      case 'full':
      default: {
        const top = m.box.max.y + 0.3 * m.height, bottom = Math.min(0, m.box.min.y) - 0.03 * m.height;
        const halfWidth = Math.max(m.box.max.x - m.center.x, m.center.x - m.box.min.x, 0.45 * m.height) * 1.1;
        return fit(new THREE.Vector3(m.center.x, (top + bottom) / 2, m.center.z), (top - bottom) / 2 * 1.04, front, halfWidth);
      }
    }
  }

  updateFog(subjectDistance = this.fogDistance ?? 6) {
    this.fogDistance = subjectDistance;
    if (!this.scene.fog) return;
    this.scene.fog.near = Math.max(9, subjectDistance + 4);
    this.scene.fog.far = this.scene.fog.near + 17;
  }

  setPreset(id) {
    this.preset = id;
    const c = this.cameraFor(id, this.camera.aspect);
    this.updateFog(c.position.distanceTo(c.target));
    this.camera.fov = c.fov;
    this.camera.position.copy(c.position);
    this.controls.target.copy(c.target);
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.requestRender();
    this.onChange({type: 'camera', preset: id});
  }

  // ---------------------------------------------------------------- morphs
  morphNames() { return [...this.morphs.keys()]; }

  morphValue(name) {
    const t = this.morphs.get(name)?.[0];
    return t ? t.mesh.morphTargetInfluences[t.index] : 0;
  }

  setMorph(name, value) {
    for (const {mesh, index} of this.morphs.get(name) || []) mesh.morphTargetInfluences[index] = value;
    this.requestRender();
  }

  resetMorphs() {
    for (const targets of this.morphs.values()) for (const {mesh, index} of targets) mesh.morphTargetInfluences[index] = 0;
    this.requestRender();
  }

  // ---------------------------------------------------------------- capture
  captureRenderer(width, height) {
    if (!this.capture) {
      const canvas = document.createElement('canvas');
      this.capture = new THREE.WebGLRenderer({canvas, antialias: true, preserveDrawingBuffer: true});
      this.capture.setPixelRatio(1);
      // GPU textures belong to one WebGL context: the capture renderer needs
      // its own prefiltered environment map.
      const pmrem = new THREE.PMREMGenerator(this.capture);
      this.captureEnv = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      pmrem.dispose();
    }
    this.configureRenderer(this.capture);
    this.capture.setSize(width, height, false);
    return this.capture;
  }

  // Render the scene from a camera preset at a fixed size; returns a PNG data URL.
  captureImage(presetId, width = 1024, height = 1024) {
    const renderer = this.captureRenderer(width, height);
    const c = this.cameraFor(presetId, width / height);
    const fogDistance = this.fogDistance;
    this.updateFog(c.position.distanceTo(c.target));
    const camera = new THREE.PerspectiveCamera(c.fov, width / height, 0.01, 100);
    camera.position.copy(c.position);
    camera.lookAt(c.target);
    camera.updateMatrixWorld();
    const helpers = [this.grid, this.skeletonHelper].filter(Boolean).map(o => [o, o.visible]);
    for (const [o] of helpers) o.visible = false;
    renderer.shadowMap.needsUpdate = true;
    this.scene.environment = this.captureEnv;
    try {
      renderer.render(this.scene, camera);
    } finally {
      this.scene.environment = this.envTexture;
    }
    const url = renderer.domElement.toDataURL('image/png');
    for (const [o, visible] of helpers) o.visible = visible;
    this.updateFog(fogDistance);
    return {url, camera: {preset: presetId, position: c.position.toArray().map(round), target: c.target.toArray().map(round), fov: c.fov, width, height}};
  }
}

const round = v => Math.round(v * 10000) / 10000;

export function dispose(object) {
  object.traverse(o => {
    o.geometry?.dispose();
    for (const m of o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : []) {
      for (const value of Object.values(m)) if (value?.isTexture) value.dispose();
      m.dispose();
    }
  });
}
