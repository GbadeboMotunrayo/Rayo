/* ============================================================
   Iron Man layer — five additions on top of the HUD, nothing removed.
   Principles from the Iron Man HUD designers (Jayse Hansen / Cantina Creative):
   the HUD is a character, it has modes, nothing is decorative, elements sit at
   different depths, and the radar shows what is around you.

   1. RADAR      real Wi-Fi networks and Bluetooth devices around the reactor
   2. ALERT MODE the HUD switches mode when something serious needs you
   3. DEPTH      side clusters drift with the pointer, at different depths
   4. MICRO-TEXT the reactor's compass marks become live readouts
   5. COMMS      a JARVIS-style waveform panel while Rayo listens or speaks

   Cost rules (docs/MOTION.md): nothing here loops. The radar redraws only when
   its data changes (every 30 s) with one sweep; alert mode animates only on
   entry; depth moves only while the pointer moves; the waveform runs only while
   voice is active. Everything that moves uses CSS transforms or SVG, which reach
   the real overlay window (a 2D canvas does not: see MOTION.md §9).
   ============================================================ */
(() => {
  'use strict';
  const root = document.documentElement, $ = (id) => document.getElementById(id);
  const esc = (x) => String(x).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const SVGNS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs = {}, parent) => { const n = document.createElementNS(SVGNS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; };

  // ---------------------------------------------------------------- 1. RADAR
  const radar = $('radar'), blips = $('radar-blips'), sweep = $('radar-sweep'), rk = $('radar-k');
  let nearSig = '';
  // stable angle per name, kept out of the bottom sector where the brief and captions live
  function angleFor(name) {
    let h = 2166136261; for (const c of name) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; }
    const t = (h % 10000) / 10000;                       // 0..1
    // SVG angles run clockwise from 3 o'clock, so the bottom is 90°: use 120°..420°, a 60° gap at the bottom
    return (120 + t * 300) * Math.PI / 180;
  }
  function drawRadar(near) {
    if (!radar || !near) return;
    const sig = JSON.stringify([near.wifi, near.bt]);
    if (sig === nearSig) return;
    nearSig = sig;
    blips.textContent = '';
    const wifi = near.wifi || [], bt = near.bt || [];
    const items = [
      ...wifi.map((w) => ({ kind: 'wifi', name: w.name, r: 338 - Math.max(0, Math.min(100, w.signal)) * 0.9, w })),
      ...bt.map((b) => ({ kind: 'bt', name: b.name, r: b.connected ? 252 : 318, b })),
    ];
    items.forEach((it, i) => {
      const a = angleFor(it.kind + it.name), x = Math.cos(a) * it.r, y = Math.sin(a) * it.r;
      const g = el('g', { class: `blip ${it.kind}` + (it.w && it.w.mine ? ' mine' : '') + (it.w && it.w.open ? ' open' : '') + (it.b && it.b.connected ? ' on' : ''), transform: `translate(${x.toFixed(1)} ${y.toFixed(1)})` }, blips);
      g.style.setProperty('--d', `${(i * 70)}ms`);
      el('title', {}, g).textContent = it.kind === 'wifi'
        ? `Wi-Fi · ${it.name} · signal ${it.w.signal}%${it.w.mine ? ' · connected' : ''}${it.w.open ? ' · open (no password)' : ''}`
        : `Bluetooth · ${it.name} · ${it.b.connected ? 'connected' : 'known, not connected'}`;
      if (it.kind === 'wifi') el('path', { d: 'M0 -6 L6 0 L0 6 L-6 0 Z' }, g);
      else el('path', { d: 'M0 -6 L5.5 4.5 L-5.5 4.5 Z' }, g);
      if (it.w && it.w.mine) el('circle', { r: 11, class: 'ring' }, g);
      const right = x >= 0, t = el('text', { x: right ? 12 : -12, y: 4, 'text-anchor': right ? 'start' : 'end' }, g);
      t.textContent = it.kind === 'wifi' ? `${it.name.slice(0, 18)} ${it.w.signal}%` : it.name.slice(0, 18);
    });
    if (rk) rk.textContent = `SURROUNDINGS · ${wifi.length} WI-FI · ${bt.filter((b) => b.connected).length}/${bt.length} BLUETOOTH`;
    // one sweep per refresh (an event, not a loop)
    if (sweep) { sweep.classList.remove('go'); void sweep.getBoundingClientRect(); sweep.classList.add('go'); }
  }

  // ---------------------------------------------------------------- 2. ALERT MODE
  const ap = $('alertpanel');
  let alertSig = '';
  function alerts(d) {
    const out = [], t = d.threat, o = d.office;
    if (d.power === 'low') out.push({ lvl: 'red', k: 'POWER', v: `${Math.round(d.battery)}% left${d.batt_min ? ` · about ${d.batt_min} min` : ''}. Plug in.` });
    if (d.sys_state === 'HOT') out.push({ lvl: 'red', k: 'THERMAL', v: `CPU at ${d.cpu_temp}°C` });
    if (t && t.bad) out.push({ lvl: 'red', k: 'SECURITY', v: `${t.bad} problem${t.bad > 1 ? 's' : ''} open · ${t.first || ''}` });
    if (o && o.state === 'ok' && o.need > 0) out.push({ lvl: 'gold', k: 'OFFICE', v: `${o.need} need${o.need === 1 ? 's' : ''} you${o.top ? ` · ${o.top.who}: ${o.top.title}` : ''}` });
    return out;
  }
  function alertMode(d) {
    if (!ap || d.mock) return;
    const list = alerts(d), sig = JSON.stringify(list);
    if (sig === alertSig) return;
    const was = alertSig && alertSig !== '[]';
    alertSig = sig;
    if (!list.length) { root.classList.remove('alert-mode', 'alert-red', 'alert-gold'); return; }
    ap.innerHTML = `<div class="ap-k">ALERT MODE</div>` + list.map((a) =>
      `<div class="ap-row ${a.lvl}"><span class="ap-tag">${esc(a.k)}</span><span class="ap-v">${esc(a.v)}</span></div>`).join('');
    root.classList.toggle('alert-red', list.some((a) => a.lvl === 'red'));
    root.classList.toggle('alert-gold', !list.some((a) => a.lvl === 'red'));
    if (!was) {                                           // entering: replay the one-off transition
      root.classList.remove('alert-mode'); void ap.getBoundingClientRect(); root.classList.add('alert-mode');
      window.dispatchEvent(new CustomEvent('rayo:wake'));
    }
  }

  // ---------------------------------------------------------------- 3. DEPTH
  // farther layers move less: top strip 3px, side clusters 9px, wordmark/status 5px
  const LAYERS = [
    ['.topstrip', 3], ['.clock', 9], ['.vitals', 9], ['#pwr', 9], ['.netblk', 7], ['.baseline', 5],
    ['.worb', 9], ['.launch', 9], ['.office', 9], ['.powerbtns', 7], ['.status', 5], ['.cooling', 4],
  ].map(([sel, k]) => [document.querySelector('.stage ' + sel), k]).filter(([n]) => n);
  let px = 0, py = 0, pending = false;
  function applyDepth() {
    pending = false;
    for (const [n, k] of LAYERS) n.style.translate = `${(-px * k).toFixed(1)}px ${(-py * k * 0.6).toFixed(1)}px`;
  }
  addEventListener('pointermove', (e) => {
    px = (e.clientX / innerWidth - 0.5) * 2; py = (e.clientY / innerHeight - 0.5) * 2;
    if (!pending) { pending = true; requestAnimationFrame(applyDepth); }
  }, { passive: true });
  document.documentElement.addEventListener('pointerleave', () => { px = py = 0; requestAnimationFrame(applyDepth); });

  // ---------------------------------------------------------------- 4. MICRO-TEXT
  const fmtK = (b) => (b < 1024 ? `${Math.round(b)}B` : b < 1048576 ? `${(b / 1024).toFixed(1)}K` : `${(b / 1048576).toFixed(1)}M`);
  function microText(d) {
    const set = (sel, txt, title) => { const n = document.querySelector('.reactor .cardinal.' + sel); if (n && n.textContent !== txt) { n.textContent = txt; n.title = title; } };
    if (d.cpu_temp != null) set('n', `${d.cpu_temp}°C`, 'CPU temperature');
    set('e', `↓${fmtK(d.down || 0)}`, 'Download now');
    set('s', `${Math.round(d.battery)}%`, 'Battery');
    const m = Math.floor((Date.now() - d.boot) / 60000);
    set('w', m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}` : `${m}m`, 'Uptime');
  }

  // ---------------------------------------------------------------- 5. COMMS
  const bars = $('comms-bars'), N = 32, levels = new Array(N).fill(0);
  if (bars) for (let i = 0; i < N; i++) bars.appendChild(document.createElement('i'));
  const barEls = bars ? [...bars.children] : [];
  let lastPush = 0;
  addEventListener('rayo:level', (e) => {
    const now = performance.now(); if (now - lastPush < 45) return; lastPush = now;
    levels.shift(); levels.push(Math.max(0, Math.min(1, +e.detail || 0)));
    barEls.forEach((b, i) => { b.style.transform = `scaleY(${(0.08 + levels[i] * 0.92).toFixed(3)})`; });
  });
  const commsK = $('comms-k');
  new MutationObserver(() => {
    if (!commsK) return;
    const c = root.className;
    const word = /\brv-speaking\b/.test(c) ? 'RAYO · TRANSMITTING' : /\brv-thinking\b/.test(c) ? 'RAYO · PROCESSING'
      : /\brv-listening\b/.test(c) ? 'COMMS · RECEIVING' : /\brv-answer\b/.test(c) ? 'RAYO · TRANSMITTING' : 'COMMS · STANDBY';
    if (commsK.textContent !== word) commsK.textContent = word;
    if (!/\brv-(listening|speaking)\b/.test(c)) { levels.fill(0); barEls.forEach((b) => { b.style.transform = 'scaleY(.08)'; }); }
  }).observe(root, { attributes: true, attributeFilter: ['class'] });

  // ---------------------------------------------------------------- data hook (hud.js fires rayo:data every second)
  addEventListener('rayo:data', (e) => {
    const d = e.detail || {};
    if (!d.mock) drawRadar(d.near);
    alertMode(d);
    microText(d);
  });
})();
