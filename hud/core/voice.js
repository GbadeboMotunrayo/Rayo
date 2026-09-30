/* ============================================================
   Rayo · voice visuals — the reactor is the voice interface.
   The desktop overlay streams the listener's events here:
     starting · armed · listening · level <0..1> · heard <text> ·
     result <msg> · idle · error <msg> · off
   window.RayoVoice.on(kind, payload) is the single entry point.
   In a plain browser (no overlay) RayoVoice.demo() plays a clearly
   labelled scripted run so the look can be previewed.
   ============================================================ */
(() => {
  'use strict';
  const root = document.documentElement;
  const $ = (id) => document.getElementById(id);
  const STATES = ['rv-on', 'rv-armed', 'rv-listening', 'rv-error'];
  let capTimer = null, lastHeard = '', demo = false;

  const setState = (...cls) => { STATES.forEach((c) => root.classList.remove(c)); cls.forEach((c) => root.classList.add(c)); };
  const label = (t) => { const el = $('vstate'); if (el) el.textContent = demo ? t.replace('VOICE', 'VOICE DEMO') : t; };
  function level(v) {
    const L = Math.max(0, Math.min(1, +v || 0));
    root.style.setProperty('--vs', (1 + L * 0.14).toFixed(3));   // spectrum ring flares
    root.style.setProperty('--vo', (1 + L * 0.07).toFixed(3));   // core breathes
  }
  function caption(said, res, err, hold = 3200) {
    const c = $('vcap'); if (!c) return;
    c.querySelector('.said').textContent = said ? `“${said}”` : '';
    c.querySelector('.res').textContent = res || '';
    c.classList.toggle('err', !!err);
    c.classList.add('show');
    clearTimeout(capTimer);
    if (hold) capTimer = setTimeout(() => c.classList.remove('show'), hold);
  }
  const isErr = (m) => /not available|didn't catch|no matching|unavailable/i.test(m || '');

  const on = {
    starting() { setState('rv-on'); label('VOICE WAKING'); },
    armed()    { setState('rv-on', 'rv-armed'); label('VOICE ARMED'); level(0);
                 caption('', 'say “rayo”', false, 3500); },
    listening(){ setState('rv-on', 'rv-armed', 'rv-listening'); label('VOICE · LISTENING');
                 lastHeard = ''; caption('', 'listening…', false, 0); },
    level(v)   { level(v); },
    heard(t)   { lastHeard = t || ''; },
    result(m)  { caption(lastHeard, m, isErr(m)); },
    idle()     { setState('rv-on', 'rv-armed'); label('VOICE ARMED'); level(0); },
    error(m)   { setState('rv-on', 'rv-error'); label('VOICE ERROR'); caption('', m, true, 7000); },
    off()      { STATES.forEach((c) => root.classList.remove(c)); level(0); demo = false; },
  };

  // scripted preview (browser only — no microphone, nothing runs)
  let demoTimers = [];
  function runDemo() {
    demoTimers.forEach(clearTimeout); demoTimers = [];
    demo = true;
    const at = (ms, k, p) => demoTimers.push(setTimeout(() => on[k](p), ms));
    at(0, 'starting'); at(900, 'armed'); at(3200, 'listening');
    const speech = [.18, .52, .78, .64, .86, .41, .73, .58, .22, .09];
    speech.forEach((v, i) => at(3500 + i * 250, 'level', v));
    at(6100, 'level', 0); at(6200, 'heard', 'open browser'); at(6250, 'result', 'opening browser (demo)');
    at(6700, 'idle'); at(10500, 'off');
  }

  window.RayoVoice = {
    on(kind, payload) { const h = on[kind]; if (h) h(payload); },
    demo: runDemo,
    get demoRunning() { return demo; },
    stopDemo() { demoTimers.forEach(clearTimeout); demoTimers = []; on.off(); },
  };
  if (new URLSearchParams(location.search).get('voicedemo') === '1') runDemo();
})();
