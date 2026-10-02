/* ============================================================
   Rayo · voice visuals — the reactor is the voice interface.
   The desktop overlay streams the listener's events here:
     starting · armed · listening · level <0..1> · heard <text> ·
     ask <question> · thinking [cloud <groq|anthropic>] · say <partial answer> · speaking · alert <message> · answer <text> · result <msg> · idle · error <msg> · off
   window.RayoVoice.on(kind, payload) is the single entry point.
   In a plain browser (no overlay) RayoVoice.demo() plays a clearly
   labelled scripted run so the look can be previewed.
   ============================================================ */
(() => {
  'use strict';
  const root = document.documentElement;
  const $ = (id) => document.getElementById(id);
  const STATES = ['rv-on', 'rv-armed', 'rv-listening', 'rv-thinking', 'rv-speaking', 'rv-error'];
  let capTimer = null, lastHeard = '', demo = false;

  const setState = (...cls) => { STATES.forEach((c) => root.classList.remove(c)); cls.forEach((c) => root.classList.add(c)); };
  const label = (t) => { const el = $('vstate'); if (el) el.textContent = demo ? t.replace('VOICE', 'VOICE DEMO') : t; };
  function level(v) {
    const L = Math.max(0, Math.min(1, +v || 0));
    root.style.setProperty('--vs', (1 + L * 0.14).toFixed(3));   // spectrum ring flares
    root.style.setProperty('--vo', (1 + L * 0.07).toFixed(3));   // core breathes
  }
  function caption(said, res, err, hold = 3200, asking = false, talking = false) {
    const c = $('vcap'); if (!c) return;
    c.classList.toggle('talk', talking); if (!talking) c.classList.remove('alert');
    c.querySelector('.said').textContent = !said ? '' : asking ? said : `“${said}”`;
    c.classList.toggle('ask', asking);
    c.querySelector('.res').textContent = res || '';
    c.classList.toggle('err', !!err);
    c.classList.add('show');
    clearTimeout(capTimer);
    if (hold) capTimer = setTimeout(() => c.classList.remove('show'), hold);
  }
  const isErr = (m) => /not available|didn't catch|no matching|unavailable|couldn't find|^no (document|browser|command|folder|app)/i.test(m || '');

  const on = {
    starting() { setState('rv-on'); label('VOICE WAKING'); },
    armed()    { setState('rv-on', 'rv-armed'); label('VOICE ARMED'); level(0);
                 caption('', 'say “rayo”', false, 3500); },
    listening(){ setState('rv-on', 'rv-armed', 'rv-listening'); label('VOICE · LISTENING');
                 lastHeard = ''; caption('', 'listening…', false, 0); },
    level(v)   { level(v); },
    heard(t)   { lastHeard = t || ''; },
    thinking(src) { const [kind, who] = (src || '').split(' ');                 // payload 'cloud groq' = the question is leaving the laptop
                 const cloud = kind === 'cloud', name = (who || 'cloud').toUpperCase();
                 setState('rv-on', 'rv-armed', 'rv-thinking'); label(cloud ? 'VOICE · ASKING ' + name : 'VOICE · THINKING'); level(0);
                 caption(lastHeard, cloud ? 'asking ' + name.toLowerCase() + '…' : 'thinking…', false, 0); },
    say(t)     { caption(lastHeard, t, false, 0, false, true); },               // answer streaming in
    answer(t)  { caption(lastHeard, t, false, Math.max(5000, (t || '').split(' ').length * 420), false, true); },
    ask(q)     { setState('rv-on', 'rv-armed', 'rv-listening'); label('VOICE · ASKING');   // Rayo needs a detail
                 caption(q, 'listening…', false, 0, true); },
    result(m)  { const long = (m || '').length > 46;                 // long replies wrap instead of running off-screen
                 caption(lastHeard, m, isErr(m), long ? Math.max(4500, m.split(' ').length * 420) : 3200, false, long); },
    idle()     { setState('rv-on', 'rv-armed'); label('VOICE ARMED'); level(0); },
    error(m)   { setState('rv-on', 'rv-error'); label('VOICE ERROR'); caption('', m, true, 7000); },
    off()      { STATES.forEach((c) => root.classList.remove(c)); level(0); demo = false; },
    do(cmd)    {                        // HUD-side voice commands
      if (cmd === 'theme' && window.RayoTheme) window.RayoTheme.cycle();
      else if (cmd === 'bench' && window.RayoControl) window.RayoControl.openBench();
      else if (cmd === 'bench_off' && window.RayoControl) window.RayoControl.closeBench();
    },
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
    at(6100, 'level', 0); at(6200, 'heard', 'launch browser');
    at(6300, 'ask', 'which browser? brave, chromium or firefox');
    [.3, .7, .5, .2].forEach((v, i) => at(8600 + i * 250, 'level', v));
    at(9700, 'level', 0); at(9800, 'heard', 'firefox'); at(9850, 'result', 'opening firefox (demo)');
    at(10300, 'idle');
    // then a question for the brain (the local LLM)
    at(12500, 'listening'); [.4, .8, .6, .3].forEach((v, i) => at(12800 + i * 250, 'level', v));
    at(13900, 'level', 0); at(14000, 'heard', 'why is the sky blue'); at(14050, 'thinking');
    const reply = 'Sunlight scatters off the air, and blue light scatters the most, so the whole sky glows blue.';
    reply.split(' ').forEach((w, i, a) => at(15000 + i * 110, 'say', a.slice(0, i + 1).join(' ')));
    at(15000 + reply.split(' ').length * 110, 'answer', reply);
    at(17800, 'idle'); at(25000, 'off');
  }

  window.RayoVoice = {
    on(kind, payload) { const h = on[kind]; if (h) h(payload); },
    demo: runDemo,
    get demoRunning() { return demo; },
    stopDemo() { demoTimers.forEach(clearTimeout); demoTimers = []; on.off(); },
  };
  if (new URLSearchParams(location.search).get('voicedemo') === '1') runDemo();
})();
