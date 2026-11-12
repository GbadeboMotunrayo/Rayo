/* ============================================================
   R7 — the reactor in real 3D (three.js r160, vendored in hud/vendor/three)
   Replaces the CSS rings, ruler, blades and core with one small WebGL canvas
   the size of the reactor (not the whole screen). Everything else stays CSS.

   Cost rules (docs/MOTION.md §8):
   - Ambient spin renders on the shared 10 fps beat, like the CSS loops did.
   - While you interact (pointer moving, a press, voice changing state) it
     renders at 30 fps for about a second, so tilts and springs stay smooth.
   - Calm mode, a covered desktop, a hidden page: the loop stops entirely.
   - No WebGL, or reduced motion: the CSS reactor stays (html.r3d not added),
     or one still frame is drawn.
   Colours come from the theme tokens and follow a theme change.
   ============================================================ */
import * as THREE from '../vendor/three/three.module.min.js';

(() => {
  const root = document.documentElement;
  const reactor = document.querySelector('.reactor');
  if (!reactor || new URLSearchParams(location.search).get('r3d') === '0') return;

  const canvas = document.createElement('canvas');
  canvas.className = 'r3d-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power' });
  } catch (e) {
    console.log('[rayo] 3D reactor unavailable, keeping the CSS one:', e.message);
    return;
  }
  reactor.prepend(canvas);
  root.classList.add('r3d');
  { const gl = renderer.getContext(), dbg = gl.getExtension('WEBGL_debug_renderer_info');
    console.log('[rayo] 3D reactor on:', dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : 'webgl'); }
  renderer.setClearColor(0x000000, 0);

  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const SIZE = 560;                                   // the reactor's design box
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 10, 4000);
  camera.position.z = (SIZE / 2) / Math.tan(THREE.MathUtils.degToRad(15));   // 560 world units fill the view

  // ---- theme colours ---------------------------------------------------------
  const tok = (n, d) => { const v = getComputedStyle(root).getPropertyValue(n).trim(); return new THREE.Color(v || d); };
  let C = {};
  function readColours() {
    C = { ice: tok('--ice', '#78d2ee'), bright: tok('--ice-bright', '#a6ecff'), deep: tok('--ice-deep', '#1f6f86'),
          hi: tok('--ice-hi', '#e9f9ff'), abyss: tok('--ice-abyss', '#0c3b49') };
  }
  readColours();

  // ---- rings: a faint full band + a bright arc whose head leads the spin -----
  const arcMat = (head) => new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { cB: { value: C.bright.clone() }, cM: { value: C.ice.clone() }, head: { value: head } },
    vertexShader: 'varying float u; void main(){ u = uv.x; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }',
    fragmentShader: `uniform vec3 cB; uniform vec3 cM; uniform float head; varying float u;
      void main(){ float d = abs(u - head); vec3 c = mix(cB, cM, smoothstep(0., .33, d));
        float a = 1. - smoothstep(.3, 1., d); gl_FragColor = vec4(c * a, a); }`,
  });
  // radius, period (s), direction (1 = counter-clockwise on screen), start angle
  const RINGS = [[267.5, 14, 1, 0], [225.5, 12, -1, 3.1], [187.5, 10, -1, 4.2], [153.5, 8, 1, 2.1], [120.5, 6, -1, 5.2]];
  const AXIS = new THREE.Vector3(1, -0.3, 0).normalize();
  const rings = [], faintMats = [];
  RINGS.forEach(([r, period, dir, a0], i) => {
    const tilt = new THREE.Group();                    // tips back on the shared axis while thinking
    const spin = new THREE.Group();                    // spins in its own plane
    const fm = new THREE.MeshBasicMaterial({ color: C.ice, transparent: true, opacity: .16, depthWrite: false });
    faintMats.push(fm);
    spin.add(new THREE.Mesh(new THREE.TorusGeometry(r, 1.6, 6, 160), fm));
    const arc = new THREE.Mesh(new THREE.TorusGeometry(r, 2.4, 6, 90, THREE.MathUtils.degToRad(165)), arcMat(dir > 0 ? 1 : 0));
    spin.add(arc);
    spin.rotation.z = a0;
    tilt.add(spin); scene.add(tilt);
    rings.push({ tilt, spin, arc, speed: dir * Math.PI * 2 / period, ang: 0, i });
  });

  // ruler: 72 tick marks (every 5°), turning slowly the other way
  const ruler = new THREE.Group();
  const tickMat = new THREE.MeshBasicMaterial({ color: C.bright, transparent: true, opacity: .55, depthWrite: false });
  const ticks = new THREE.InstancedMesh(new THREE.BoxGeometry(1.4, 9, 1), tickMat, 72);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), s1 = new THREE.Vector3(1, 1, 1);
  for (let k = 0; k < 72; k++) {
    const a = k / 72 * Math.PI * 2;
    q.setFromAxisAngle(new THREE.Vector3(0, 0, 1), a - Math.PI / 2);
    ticks.setMatrixAt(k, m4.compose(v.set(Math.cos(a) * 202.5, Math.sin(a) * 202.5, 0), q, s1));
  }
  ruler.add(ticks);
  const rulerTilt = new THREE.Group(); rulerTilt.add(ruler); scene.add(rulerTilt);

  // blades: 12 short bars round the core that glow bright and dim
  const bladeMat = new THREE.MeshBasicMaterial({ color: C.ice, transparent: true, opacity: .85, depthWrite: false });
  const blades = new THREE.InstancedMesh(new THREE.BoxGeometry(4.5, 18, 3), bladeMat, 12);
  for (let k = 0; k < 12; k++) {
    const a = k / 12 * Math.PI * 2;
    q.setFromAxisAngle(new THREE.Vector3(0, 0, 1), a - Math.PI / 2);
    blades.setMatrixAt(k, m4.compose(v.set(Math.cos(a) * 89, Math.sin(a) * 89, 0), q, s1));
  }
  const bladeTilt = new THREE.Group(); bladeTilt.add(blades); scene.add(bladeTilt);

  // the core: a lit sphere with a soft halo behind it
  const coreMat = new THREE.MeshStandardMaterial({ color: C.bright, emissive: C.ice, emissiveIntensity: .55, roughness: .3, metalness: 0 });
  const core = new THREE.Mesh(new THREE.SphereGeometry(75, 48, 32), coreMat);
  scene.add(core);
  const haloTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 128;
    const g = c.getContext('2d'), grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grd.addColorStop(0, 'rgba(255,255,255,.9)'); grd.addColorStop(.35, 'rgba(255,255,255,.28)'); grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  })();
  const haloMat = new THREE.SpriteMaterial({ map: haloTex, color: C.ice, transparent: true, opacity: .5, depthWrite: false, blending: THREE.AdditiveBlending });
  const halo = new THREE.Sprite(haloMat); halo.scale.set(300, 300, 1); halo.position.z = -40; scene.add(halo);
  scene.add(new THREE.AmbientLight(0xffffff, .55));
  const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(-260, 320, 520); scene.add(key);
  const rim = new THREE.DirectionalLight(C.bright, .8); rim.position.set(300, -200, -300); scene.add(rim);

  function recolour() {
    readColours();
    rings.forEach((r) => { r.arc.material.uniforms.cB.value.copy(C.bright); r.arc.material.uniforms.cM.value.copy(C.ice); });
    faintMats.forEach((m) => m.color.copy(C.ice));
    tickMat.color.copy(C.bright); bladeMat.color.copy(C.ice); haloMat.color.copy(C.ice);
    coreMat.color.copy(C.bright); coreMat.emissive.copy(C.ice); rim.color.copy(C.bright);
    draw();
  }

  // ---- size: match the canvas's on-screen pixels (never the whole window) ----
  function resize() {
    const b = canvas.getBoundingClientRect();
    const px = Math.max(64, Math.round(Math.max(b.width, b.height) * Math.min(devicePixelRatio || 1, 1.5)));
    renderer.setPixelRatio(1);
    renderer.setSize(px, px, false);
    draw();
  }

  // ---- input: pointer tilt, press, voice tilt ---------------------------------
  let lastInput = 0, tx = 0, ty = 0, tilt = { x: 0, y: 0 }, think = 0, press = 1, pressT = 1;
  addEventListener('pointermove', (e) => {
    const b = reactor.getBoundingClientRect();
    const nx = (e.clientX - (b.left + b.width / 2)) / innerWidth, ny = (e.clientY - (b.top + b.height / 2)) / innerHeight;
    tx = THREE.MathUtils.clamp(ny, -1, 1) * 0.5; ty = THREE.MathUtils.clamp(nx, -1, 1) * 0.6;
    poke();
  }, { passive: true });
  const hub = document.getElementById('hub-hit');
  if (hub) {
    hub.addEventListener('pointerdown', () => { pressT = 0.93; poke(); });
    addEventListener('pointerup', () => { pressT = 1; poke(); });
  }

  // ---- frame loop ---------------------------------------------------------------
  let raf = 0, last = 0, clockT = 0;
  const stopped = () => document.hidden || root.classList.contains('rayo-calm') || root.classList.contains('rayo-idle');
  function poke() { lastInput = performance.now(); start(); }
  function start() { if (!raf && !reduced && !stopped()) { last = performance.now(); raf = requestAnimationFrame(frame); } }
  function frame(now) {
    raf = 0;
    if (stopped()) { draw(); return; }                                 // freeze where it is
    const busy = now - lastInput < 1200 || Math.abs(think - thinkTarget()) > .002 || Math.abs(press - pressT) > .002;
    const step = busy ? 33 : 100;                                       // 30 fps while you act, else the 10 fps beat
    if (now - last >= step - 2) {
      const dt = Math.min((now - last) / 1000, .25); last = now;
      advance(dt); draw();
    }
    raf = requestAnimationFrame(frame);
  }
  const thinkTarget = () => (/\brv-(thinking|answer)\b/.test(root.className) ? THREE.MathUtils.degToRad(64) : 0);
  function advance(dt) {
    clockT += dt;
    const k = 1 - Math.exp(-dt * 7);                                    // critically-damped-ish follow
    tilt.x += (tx - tilt.x) * k; tilt.y += (ty - tilt.y) * k;
    think += (thinkTarget() - think) * (1 - Math.exp(-dt * 6));
    press += (pressT - press) * (1 - Math.exp(-dt * 18));
    rings.forEach((r) => { r.ang += r.speed * dt; r.spin.rotation.z = r.ang; });
    ruler.rotation.z += 2 * Math.PI / 40 * dt;
    bladeMat.opacity = .55 + .45 * (0.5 + 0.5 * Math.sin(clockT * Math.PI * 2 / 3));
    core.scale.setScalar(press * (1 + .02 * Math.sin(clockT * Math.PI * 2 / 3)));
  }
  const base = new THREE.Quaternion(), qa = new THREE.Quaternion();
  function draw() {
    // whole reactor leans towards the pointer; rings also tip back while thinking, outer → inner
    base.setFromEuler(new THREE.Euler(-0.12 + tilt.x, 0.1 + tilt.y, 0));
    rings.forEach((r) => { qa.setFromAxisAngle(AXIS, think * (1 - r.i * 0.04)); r.tilt.quaternion.copy(base).multiply(qa); });
    qa.setFromAxisAngle(AXIS, think * .82); rulerTilt.quaternion.copy(base).multiply(qa); bladeTilt.quaternion.copy(base).multiply(qa);
    core.quaternion.copy(base);
    renderer.render(scene, camera);
  }

  // restart when calm / idle ends or voice changes; recolour on a theme change
  new MutationObserver((list) => {
    for (const m of list) if (m.attributeName === 'data-theme' || m.attributeName === 'style') { recolour(); break; }
    if (/\brv-/.test(root.className)) lastInput = performance.now();
    start();
  }).observe(root, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] });
  document.addEventListener('visibilitychange', start);
  new ResizeObserver(resize).observe(canvas);
  addEventListener('resize', () => setTimeout(resize, 50));        // the stage scales by transform, not size
  resize();
  start();
})();
