/* ============================================================
   Rayo calm mode + the "LAST" line of the idle brief
   - After a quiet minute the reactor rings coast to a stop and only the core
     breathes (html.rayo-calm; the stylesheet pauses the loops). It saves the
     overlay CPU on a desktop nobody is touching, and it is calmer to live with.
   - Anything happening wakes it for another minute: the pointer over the HUD,
     a click or key, voice, the desktop shown again after being covered, a
     status word changing (hud.js fires `rayo:wake`), or an action.
   - LAST: what Rayo just did, shown for 5 seconds; nothing is stored.
   ============================================================ */
(() => {
  'use strict';
  const root = document.documentElement, $ = (id) => document.getElementById(id);
  const QUIET_MS = 60000;
  let timer = null;

  // RAYO's hologram re-projects (one light sweep) when the HUD wakes or listens
  let scanTimer = null;
  function scan() {
    root.classList.remove('holo-scan'); void root.offsetWidth;   // restart the pass
    root.classList.add('holo-scan');
    clearTimeout(scanTimer); scanTimer = setTimeout(() => root.classList.remove('holo-scan'), 3100);
  }
  function wake() {
    if (root.classList.contains('rayo-calm')) scan();
    root.classList.remove('rayo-calm');
    clearTimeout(timer);
    timer = setTimeout(() => {
      // never settle mid-conversation or with the menu or Bench open
      const busy = /\brv-(listening|thinking|speaking|answer)\b/.test(root.className)
        || document.querySelector('.hubmenu.open, .powerbar.open, .bench.open, .countdown.open');
      busy ? wake() : root.classList.add('rayo-calm');
    }, QUIET_MS);
  }
  let lastMove = 0;
  addEventListener('pointermove', () => { const n = Date.now(); if (n - lastMove > 1000) { lastMove = n; wake(); } }, { passive: true });
  ['pointerdown', 'keydown', 'rayo:wake', 'rayo:action'].forEach((e) => addEventListener(e, wake));
  // voice states and the overlay's idle/uncovered switch both arrive as classes on <html>
  let was = root.className;
  new MutationObserver(() => {
    const now = root.className;
    const voiceChanged = (now.match(/rv-[a-z]+/g) || []).join() !== (was.match(/rv-[a-z]+/g) || []).join();
    const uncovered = /\brayo-idle\b/.test(was) && !/\brayo-idle\b/.test(now);
    if (/\brv-listening\b/.test(now) && !/\brv-listening\b/.test(was)) scan();
    was = now;
    if (voiceChanged || uncovered) wake();
  }).observe(root, { attributes: true, attributeFilter: ['class'] });
  wake(); scan();

  // ---- LAST ----------------------------------------------------------------
  // A short confirmation of what Rayo just did, shown for 5 seconds and then
  // gone. Nothing is stored: what you opened is nobody else's business.
  const SHOW_MS = 5000;
  try { localStorage.removeItem('rayo.last'); } catch {}      // older builds kept it
  const WORDS = { web: 'opened the browser', files: 'opened Files', terminal: 'opened a terminal',
    settings: 'opened Settings', displays: 'opened display settings', dnd: 'toggled Focus',
    lock: 'locked the screen', office: 'opening the Office', voice: 'switched voice',
    logout: 'logging you out', suspend: 'going to sleep', reboot: 'restarting' };
  let hideTimer = null;
  addEventListener('rayo:action', (e) => {
    const d = e.detail || {}, row = $('b-last');
    const text = d.said ? d.said.replace(/[.!]+$/, '') : WORDS[d.act];
    if (!row || !text) return;
    $('b-last-v').textContent = text.charAt(0).toUpperCase() + text.slice(1);
    row.hidden = false;
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { row.hidden = true; }, SHOW_MS);
  });

  // ---- the MG.OFFICE card opens the Office (overlay action "office") --------
  const office = $('office');
  if (office) {
    const go = () => window.RayoControl && window.RayoControl.action('office');
    office.addEventListener('click', go);
    office.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
  }
})();
