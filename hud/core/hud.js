/* ============================================================
   Rayo core driver
   - Renders live system stats into the HUD.
   - Data provider: tries GET ./stats.json (the real overlay writes
     this from /proc every second); if absent, generates smooth
     mock data so the HUD looks alive in a plain browser preview.
   ============================================================ */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  // ---- fit the fixed 1920x1200 design into any screen (letterbox) ----------
  function fitScale() {
    const stage = document.querySelector('.stage');
    if (!stage) return;
    const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1200);
    stage.style.transform = `translate(-50%,-50%) scale(${s})`;
  }
  window.addEventListener('resize', fitScale);
  fitScale();

  // ---- fan speedometer (geometry ported from Carpadi SpeedGauge) -----------
  // A 270° arc with a 90° gap at the bottom, tick marks, and a sweeping needle;
  // the live RPM sits in the open gap. Static parts are drawn once; each second
  // we move the fill arc + needle and recolour by how hard the fan is working
  // (calm ice → gold → red) so a glance tells you something's overworking it.
  const G = { START: -135, SWEEP: 270, cx: 100, cy: 100, r: 78, stroke: 12 };
  const SVGNS = 'http://www.w3.org/2000/svg';
  const polar = (cx, cy, r, ang) => {
    const a = (ang - 90) * Math.PI / 180;
    return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
  };
  const arcPath = (cx, cy, r, a0, a1) => {
    const s = polar(cx, cy, r, a0), e = polar(cx, cy, r, a1);
    const large = (a1 - a0) > 180 ? 1 : 0;
    return `M ${s.x.toFixed(2)} ${s.y.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${e.x.toFixed(2)} ${e.y.toFixed(2)}`;
  };
  const svgEl = (name, attrs) => {
    const el = document.createElementNS(SVGNS, name);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  };
  const fanColor = (f) => f >= 0.85 ? 'var(--red)' : f >= 0.6 ? 'var(--gold)' : 'var(--ice)';
  let gauge = null;
  function buildGauge() {
    const svg = $('fan-gauge');
    if (!svg || gauge) return;
    const { START, SWEEP, cx, cy, r, stroke } = G;
    // soft radial aura behind the whole gauge (CSS filters don't render in the
    // WebKitGTK overlay, so the glow is built from geometry: a gradient disc +
    // stacked translucent arcs, not a blur).
    const defs = document.createElementNS(SVGNS, 'defs');
    const rg = document.createElementNS(SVGNS, 'radialGradient');
    rg.setAttribute('id', 'fan-aura');
    [['0%', '.30'], ['55%', '.09'], ['100%', '0']].forEach(([o, op]) => {
      const s = document.createElementNS(SVGNS, 'stop');
      s.setAttribute('offset', o); s.setAttribute('stop-color', 'var(--ice)'); s.setAttribute('stop-opacity', op);
      rg.appendChild(s);
    });
    defs.appendChild(rg); svg.appendChild(defs);
    svg.appendChild(svgEl('circle', { class: 'g-aura', cx, cy, r: 90, fill: 'url(#fan-aura)' }));
    // glow halo behind the fill: two widening translucent arcs = a soft bloom
    const emptyArc = arcPath(cx, cy, r, START, START + 0.001);
    const glow2 = svgEl('path', { class: 'g-glow', d: emptyArc, 'stroke-width': stroke + 16, stroke: 'var(--ice)', 'stroke-linecap': 'round', opacity: .12, fill: 'none' });
    const glow1 = svgEl('path', { class: 'g-glow', d: emptyArc, 'stroke-width': stroke + 7, stroke: 'var(--ice)', 'stroke-linecap': 'round', opacity: .30, fill: 'none' });
    svg.appendChild(glow2); svg.appendChild(glow1);
    svg.appendChild(svgEl('path', { class: 'g-track', 'stroke-width': stroke,
      d: arcPath(cx, cy, r, START, START + SWEEP) }));
    const fill = svgEl('path', { class: 'g-fill', 'stroke-width': stroke,
      d: arcPath(cx, cy, r, START, START + 0.001), stroke: 'var(--ice)' });
    svg.appendChild(fill);
    for (let i = 0; i <= 10; i++) {
      const ang = START + (i / 10) * SWEEP;
      const o = polar(cx, cy, r + 4, ang), inn = polar(cx, cy, r - stroke - 4, ang);
      svg.appendChild(svgEl('line', { class: 'g-tick' + (i % 5 === 0 ? ' maj' : ''),
        x1: o.x.toFixed(2), y1: o.y.toFixed(2), x2: inn.x.toFixed(2), y2: inn.y.toFixed(2),
        'stroke-width': i % 5 === 0 ? 2 : 1 }));
    }
    // needle: a line from the hub to a tip computed directly with polar() — no
    // CSS transform (WebKitGTK mis-pivots transform-origin on SVG and flings it
    // off-screen). At rest it points to the start of the sweep.
    const t0 = polar(cx, cy, r - stroke - 6, START);
    const nglow = svgEl('line', { class: 'g-nglow', x1: cx, y1: cy,
      x2: t0.x.toFixed(2), y2: t0.y.toFixed(2), 'stroke-width': 9, stroke: 'var(--ice)', 'stroke-linecap': 'round', opacity: .25 });
    svg.appendChild(nglow);
    const needle = svgEl('line', { class: 'g-needle', x1: cx, y1: cy,
      x2: t0.x.toFixed(2), y2: t0.y.toFixed(2), 'stroke-width': 3.5, stroke: 'var(--ice)' });
    svg.appendChild(needle);
    svg.appendChild(svgEl('circle', { class: 'g-hub', cx, cy, r: 9 }));
    svg.appendChild(svgEl('circle', { class: 'g-hub-in', cx, cy, r: 4 }));
    const val = svgEl('text', { class: 'g-val', x: cx, y: 150 }); val.textContent = '—';
    const unit = svgEl('text', { class: 'g-unit', x: cx, y: 168 }); unit.textContent = 'RPM';
    const lbl = svgEl('text', { class: 'g-lbl', x: cx, y: 190 }); lbl.textContent = 'CPU FAN';
    svg.append(val, unit, lbl);
    gauge = { fill, needle, nglow, glow1, glow2, val, lbl };
  }
  function updateGauge(rpm, maxRpm, label) {
    if (!gauge) return;
    const mx = maxRpm > 0 ? maxRpm : 8100;
    const frac = clamp(rpm / mx, 0, 1);
    const { START, SWEEP, cx, cy, r, stroke } = G;
    const ang = START + frac * SWEEP;
    const col = fanColor(frac);
    const dNow = arcPath(cx, cy, r, START, Math.max(START + 0.001, ang));
    gauge.fill.setAttribute('d', dNow);
    gauge.fill.setAttribute('stroke', col);
    gauge.glow1.setAttribute('d', dNow); gauge.glow1.setAttribute('stroke', col);
    gauge.glow2.setAttribute('d', dNow); gauge.glow2.setAttribute('stroke', col);
    const tip = polar(cx, cy, r - stroke - 6, ang);
    gauge.needle.setAttribute('x2', tip.x.toFixed(2));
    gauge.needle.setAttribute('y2', tip.y.toFixed(2));
    gauge.needle.setAttribute('stroke', col);
    gauge.nglow.setAttribute('x2', tip.x.toFixed(2));
    gauge.nglow.setAttribute('y2', tip.y.toFixed(2));
    gauge.nglow.setAttribute('stroke', col);
    gauge.val.textContent = Math.round(rpm || 0);
    if (label) gauge.lbl.textContent = String(label).toUpperCase();
  }
  buildGauge();

  // Values are set directly once per second; the progress bars glide via their
  // CSS `transition: width` (see stylesheet). We deliberately do NOT re-paint
  // every frame: doing so kept restarting the CSS transition and made the
  // numbers/bars flicker ("glitch") in the info panels.

  // ---- mock provider: realistic drift when no stats.json present -----------
  const mock = {
    t: 0, cpu: 8, mem: 63, disk: 53, batt: 100, sig: 86,
    down: 0, up: 0, ssid: 'Airtel_W304VA PRO_5DC3_5G',
    freq: 2.6, boot: Date.now() - 1000 * 60 * 60 * 26,
    step() {
      this.t += 1;
      // cpu jitters with occasional spikes
      const spike = Math.random() < 0.06 ? Math.random() * 40 : 0;
      this.cpu = clamp(this.cpu + (Math.random() - 0.5) * 8 + spike - this.cpu * 0.05, 1, 99);
      this.mem = clamp(this.mem + (Math.random() - 0.5) * 2, 40, 80);
      this.sig = clamp(this.sig + (Math.random() - 0.5) * 4, 60, 98);
      this.freq = (1.6 + this.cpu / 100 * 2.6).toFixed(2);
      this.down = Math.max(0, this.down + (Math.random() - 0.5) * 400 + (Math.random() < 0.1 ? 3000 : 0)) * 0.6;
      this.up = Math.max(0, this.up + (Math.random() - 0.5) * 200) * 0.6;
      return {
        // honest placeholder state — NOT claiming charging when we don't know
        battery: Math.round(this.batt), charging: false,
        batt_status: 'Discharging', batt_min: 142,
        cpu: this.cpu, mem: this.mem, disk: this.disk,
        signal: this.sig, ssid: this.ssid, freq: this.freq,
        mem_used: '4.6', mem_total: '6.9', disk_used: '124', disk_total: '233',
        down: this.down, up: this.up, boot: this.boot, mock: true,
        month_bytes: (this.monthB = (this.monthB || 8.4e9) + this.down + this.up),
        // fan tracks cpu load: idle ~2500, busy → toward 8100
        fan: Math.round(2400 + this.cpu / 100 * 5200), fan_max: 8100, fan_label: 'CPU FAN',
        wx_temp: '+27°C', wx_cond: 'Partly cloudy', wx_loc: 'Lagos', wx_feels: '+30°C'
      };
    }
  };

  // Once the bridge is confirmed missing we stop hammering the network and run
  // on mock data. The desktop overlay writes stats.json, flipping this back on.
  let bridge = true;
  async function fetchStats() {
    if (bridge) {
      try {
        const r = await fetch('./stats.json', { cache: 'no-store' });
        if (r.ok) { const d = await r.json(); d.mock = false; return d; }
        bridge = false;                       // 404 → no bridge, go mock
      } catch (e) { bridge = false; }
    }
    return mock.step();
  }

  // ---- formatting ----------------------------------------------------------
  const fmtRate = (bytes) => {
    if (bytes < 1024) return `${bytes.toFixed(0)} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
  };
  // cumulative totals (month usage): scale up to GiB/TiB
  const fmtTotal = (bytes) => {
    if (bytes == null || isNaN(bytes)) return '—';
    const gib = bytes / 1073741824;
    if (gib >= 1024) return `${(gib / 1024).toFixed(2)} TiB`;
    if (gib >= 1) return `${gib.toFixed(2)} GiB`;
    return `${(bytes / 1048576).toFixed(0)} MiB`;
  };
  const fmtDur = (min) => {
    if (min == null) return '';
    if (min <= 0) return '';
    const h = Math.floor(min / 60), m = min % 60;
    return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
  };
  const battLabel = (d) => {
    const status = d.batt_status || (d.charging ? 'Charging' : 'Discharging');
    if (status === 'Full' || d.battery >= 100 && d.charging) return 'full · on AC';
    const t = fmtDur(d.batt_min);
    if (status === 'Charging') return t ? `charging · ${t} to full` : 'charging';
    if (status === 'Discharging') return t ? `${t} left` : 'on battery';
    return d.charging ? 'charging' : 'on battery';
  };
  const fmtUptime = (bootMs) => {
    let s = Math.floor((Date.now() - bootMs) / 1000);
    const d = Math.floor(s / 86400); s -= d * 86400;
    const h = Math.floor(s / 3600); s -= h * 3600;
    const m = Math.floor(s / 60);
    return (d ? `${d}d ` : '') + `${h}h ${m}m`;
  };

  // ---- render --------------------------------------------------------------
  function paintBar(el, v) { el.style.width = clamp(v, 0, 100).toFixed(1) + '%'; }

  function setGauge(gid, nid, v) {
    const g = $(gid); if (g) g.style.setProperty('--p', clamp(v, 0, 100).toFixed(1));
    const n = $(nid); if (n) n.textContent = Math.round(v);
  }

  function render(d) {
    // honest data-source badge (LIVE / STALE / SIM)
    const src = $('data-src');
    if (src) {
      const stale = !d.mock && d.ts && (Date.now() - d.ts > 5000);
      src.textContent = d.mock ? 'SIM' : stale ? 'STALE' : 'LIVE';
      src.classList.toggle('sim', !!(d.mock || stale));
    }

    // power / capacity
    const batt = d.battery;
    if ($('pwr-v')) $('pwr-v').textContent = `${Math.round(batt)}%`;
    if ($('pwr-a')) $('pwr-a').textContent = battLabel(d);
    if ($('pwr')) $('pwr').classList.toggle('charging', !!d.charging && d.batt_status !== 'Full');
    if ($('pwr-b')) paintBar($('pwr-b'), batt);
    if ($('t-month')) $('t-month').textContent = fmtTotal(d.month_bytes);

    // vitals arc gauges
    const cpu = d.cpu, mem = d.mem, disk = d.disk;
    setGauge('sys-g', 'sys-v', cpu); if ($('sys-a')) $('sys-a').textContent = `${d.freq} GHz`;
    setGauge('mem-g', 'mem-v', mem); if ($('mem-a')) $('mem-a').textContent = `${d.mem_used} / ${d.mem_total} GiB`;
    setGauge('disk-g', 'disk-v', disk); if ($('disk-a')) $('disk-a').textContent = `${d.disk_used} / ${d.disk_total} GiB`;

    // weather orb
    const clean = (s) => (s || '').replace('+', '');
    if ($('wx-t')) {
      $('wx-t').textContent = clean(d.wx_temp) || '—';
      $('wx-c').textContent = d.wx_cond || '—';
      const loc = d.wx_loc || '';
      if ($('wx-loc')) $('wx-loc').textContent = /^[\d.,\s-]+$/.test(loc) ? '' : loc.split(',')[0];
      if ($('wx-fl')) $('wx-fl').textContent = d.wx_feels ? 'feels ' + clean(d.wx_feels) : '';
    }

    // network
    if ($('t-ssid')) $('t-ssid').textContent = d.ssid.length > 20 ? d.ssid.slice(0, 19) + '…' : d.ssid;
    if ($('t-down')) $('t-down').textContent = fmtRate(d.down);
    if ($('t-up')) $('t-up').textContent = fmtRate(d.up);
    if ($('t-up2')) $('t-up2').textContent = fmtUptime(d.boot);

    // fan speedometer
    updateGauge(d.fan, d.fan_max, d.fan_label);

    // hub reacts to CPU load by pulsing faster/brighter
    const pulse = (3 - cpu / 100 * 1.6).toFixed(2) + 's';
    const orb = document.querySelector('.orb .core'); if (orb) orb.style.animationDuration = pulse;
    const blades = document.querySelector('.blades'); if (blades) blades.style.animationDuration = pulse;
  }

  function clock() {
    const n = new Date();
    const p = (x) => String(x).padStart(2, '0');
    if ($('t-time')) $('t-time').textContent = `${p(n.getHours())}:${p(n.getMinutes())}`;
    const mon = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
    const day = ['SUNDAY','MONDAY','TUESDAY','WEDNESDAY','THURSDAY','FRIDAY','SATURDAY'];
    if ($('cd-date')) $('cd-date').textContent = `${mon[n.getMonth()]} ${n.getDate()}`;
    if ($('cd-day')) $('cd-day').textContent = day[n.getDay()];
  }

  // ---- loops ---------------------------------------------------------------
  // One update per second. Bars glide via CSS transitions; no per-frame repaint
  // (that caused the info-panel flicker). The clock updates on its own second.
  async function tick() { render(await fetchStats()); }
  clock(); setInterval(clock, 1000);
  tick(); setInterval(tick, 1000);
})();
