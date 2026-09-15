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

  // ---- smooth value interpolation (eased toward target) --------------------
  const state = {};
  function ease(key, target, k = 0.12) {
    if (state[key] === undefined) state[key] = target;
    state[key] += (target - state[key]) * k;
    return state[key];
  }

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
        down: this.down, up: this.up, boot: this.boot, mock: true
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

  function render(d) {
    // left cluster
    const batt = ease('batt', d.battery);
    $('pwr-v').innerHTML = `${Math.round(batt)}<span class="u">%</span>`;
    $('pwr-a').textContent = battLabel(d);
    // battery card glows gold while charging
    $('pwr').classList.toggle('charging', !!d.charging && d.batt_status !== 'Full');
    paintBar($('pwr-b'), batt);

    const cpu = ease('cpu', d.cpu);
    $('sys-v').innerHTML = `${Math.round(cpu)}<span class="u">%</span>`;
    $('sys-a').textContent = `${d.freq} GHz`;
    paintBar($('sys-b'), cpu);

    const sig = ease('sig', d.signal);
    $('net-v').innerHTML = `${Math.round(sig)}<span class="u">%</span>`;
    $('net-a').textContent = d.ssid.length > 18 ? d.ssid.slice(0, 17) + '…' : d.ssid;
    paintBar($('net-b'), sig);

    // right telemetry
    $('t-cpu').textContent = Math.round(cpu);
    $('t-freq').textContent = `${d.freq} GHz`;
    paintBar($('t-cpu-b'), cpu);
    const mem = ease('mem', d.mem);
    $('t-mem').textContent = Math.round(mem);
    $('t-memx').textContent = `${d.mem_used} / ${d.mem_total} GiB`;
    paintBar($('t-mem-b'), mem);
    const disk = ease('disk', d.disk, 0.3);
    $('t-disk').textContent = Math.round(disk);
    $('t-diskx').textContent = `${d.disk_used} / ${d.disk_total} GiB`;
    paintBar($('t-disk-b'), disk);
    $('t-ssid').textContent = d.ssid.length > 22 ? d.ssid.slice(0, 21) + '…' : d.ssid;
    $('t-down').textContent = fmtRate(ease('down', d.down, 0.25));
    $('t-up').textContent = fmtRate(ease('up', d.up, 0.25));
    $('t-up2').textContent = fmtUptime(d.boot);

    // honest data-source badge:
    //   LIVE  — real bridge, fresh (<5s old)
    //   STALE — real file but the bridge stopped writing (data is old!)
    //   SIM   — no bridge file at all, showing mock
    const src = $('data-src');
    if (src) {
      const stale = !d.mock && d.ts && (Date.now() - d.ts > 5000);
      src.textContent = d.mock ? 'SIM · NO BRIDGE' : stale ? 'STALE · BRIDGE DOWN' : 'LIVE';
      src.classList.toggle('sim', !!(d.mock || stale));
    }

    // hub reacts to CPU load by GLOWING faster/brighter (never rotating):
    // heavier load → quicker bright↔dim pulse on the core and blades.
    const pulse = (3 - cpu / 100 * 1.6).toFixed(2) + 's';   // 3s idle → ~1.4s busy
    const orb = document.querySelector('.orb .core');
    if (orb) orb.style.animationDuration = pulse;
    const blades = document.querySelector('.blades');
    if (blades) blades.style.animationDuration = pulse;
  }

  function clock() {
    const n = new Date();
    const p = (x) => String(x).padStart(2, '0');
    $('t-time').textContent = `${p(n.getHours())}:${p(n.getMinutes())}:${p(n.getSeconds())}`;
  }

  // ---- loops ---------------------------------------------------------------
  let lastData = mock.step();
  async function tick() { lastData = await fetchStats(); render(lastData); }
  clock(); setInterval(clock, 1000);
  tick(); setInterval(tick, 1000);
  // fast loop: re-render the SAME data so eased values glide smoothly (no refetch)
  setInterval(() => render(lastData), 90);
})();
