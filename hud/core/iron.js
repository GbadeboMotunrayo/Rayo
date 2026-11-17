/* ============================================================
   Iron Man layer — five additions on top of the HUD, nothing removed.
   Principles from the Iron Man HUD designers (Jayse Hansen / Cantina Creative):
   the HUD is a character, it has modes, nothing is decorative, elements sit at
   different depths, and the radar shows what is around you.

   1. RADAR      real Wi-Fi networks and Bluetooth devices around the reactor
   2. ALERT MODE the HUD switches mode when something serious needs you
   3. DEPTH      (removed 18 Nov: only the reactor follows the pointer)
   4. MICRO-TEXT the reactor's compass marks become live readouts
   5. COMMS      a JARVIS-style waveform panel while Rayo listens or speaks

   Cost rules (docs/MOTION.md): nothing here loops. The radar redraws only when
   its data changes (every 30 s) with one sweep; alert mode animates only on
   entry; the waveform runs only while
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
  // Two tidy arcs, like the side readouts of a helmet HUD: Wi-Fi on the LEFT (strongest
  // at the top), Bluetooth on the RIGHT (connected first). One distance, even spacing,
  // so labels never pile up. SVG angles run clockwise from 3 o'clock: 180° is left, 0° right.
  const R = 300, STEP = 14, MAXSPAN = 76;
  function arc(n, centre, dir) {           // dir -1: list runs top→bottom on the left (angles decreasing)
    const span = Math.min(MAXSPAN, (n - 1) * STEP);
    return Array.from({ length: n }, (_, k) => (centre + dir * (n === 1 ? 0 : -span / 2 + k * span / (n - 1))) * Math.PI / 180);
  }
  function drawRadar(near) {
    if (!radar || !near) return;
    const sig = JSON.stringify([near.wifi, near.bt]);
    if (sig === nearSig) return;
    nearSig = sig;
    blips.textContent = '';
    const wifi = [...(near.wifi || [])].sort((a, b) => b.signal - a.signal);
    const bt = [...(near.bt || [])].sort((a, b) => (b.connected - a.connected) || a.name.localeCompare(b.name));
    const items = [
      ...arc(wifi.length, 180, -1).map((a, k) => ({ kind: 'wifi', a, w: wifi[k], name: wifi[k].name, right: false })),
      ...arc(bt.length, 0, 1).map((a, k) => ({ kind: 'bt', a, b: bt[k], name: bt[k].name, right: true })),
    ];
    items.forEach((it, i) => {
      const x = Math.cos(it.a) * R, y = Math.sin(it.a) * R;
      const g = el('g', { class: `blip ${it.kind}` + (it.w && it.w.mine ? ' mine' : '') + (it.w && it.w.open ? ' open' : '') + (it.b && it.b.connected ? ' on' : ''), transform: `translate(${x.toFixed(1)} ${y.toFixed(1)})` }, blips);
      g.style.setProperty('--d', `${(i * 60)}ms`);
      el('title', {}, g).textContent = it.kind === 'wifi'
        ? `Wi-Fi · ${it.name} · signal ${it.w.signal}%${it.w.mine ? ' · connected' : ''}${it.w.open ? ' · open (no password)' : ''}`
        : `Bluetooth · ${it.name} · ${it.b.connected ? 'connected' : 'known, not connected'}`;
      if (it.kind === 'wifi') el('path', { d: 'M0 -6 L6 0 L0 6 L-6 0 Z' }, g);
      else el('path', { d: 'M0 -6 L5.5 4.5 L-5.5 4.5 Z' }, g);
      if (it.w && it.w.mine) el('circle', { r: 11, class: 'ring' }, g);
      const t = el('text', { x: it.right ? 14 : -14, y: 4, 'text-anchor': it.right ? 'start' : 'end' }, g);
      t.textContent = it.kind === 'wifi' ? `${it.name.slice(0, 20)}  ${it.w.signal}%` : `${it.name.slice(0, 20)}${it.b.connected ? '  ●' : ''}`;
    });
    // each side's header sits just above its list's first item
    const set = (id, txt, list) => {
      const n = $(id); if (!n) return;
      n.textContent = txt;
      const top = list.length ? Math.min(...list.map((it) => Math.sin(it.a) * R)) : -60;
      n.setAttribute('y', (top - 34).toFixed(0));
    };
    set('radar-kl', `WI-FI · ${wifi.length}`, items.filter((it) => it.kind === 'wifi'));
    set('radar-kr', `BLUETOOTH · ${bt.filter((b) => b.connected).length}/${bt.length} ON`, items.filter((it) => it.kind === 'bt'));
    if (rk) rk.textContent = 'SURROUNDINGS';
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
  // Removed on 18 Nov at MG's request: only the reactor follows the pointer (reactor3d.js).

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
