/* ============================================================
   Rayo calm mode + the "LAST" line of the idle brief
   - After a quiet minute the reactor rings coast to a stop and only the core
     breathes (html.rayo-calm; the stylesheet pauses the loops). It saves the
     overlay CPU on a desktop nobody is touching, and it is calmer to live with.
   - Anything happening wakes it for another minute: the pointer over the HUD,
     a click or key, voice, the desktop shown again after being covered, a
     status word changing (hud.js fires `rayo:wake`), or an action.
   - LAST: what Rayo last did for you, kept in this browser (localStorage).
   ============================================================ */
(() => {
  'use strict';
  const root = document.documentElement, $ = (id) => document.getElementById(id);
  const QUIET_MS = 60000;
  let timer = null;

  function wake() {
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
    was = now;
    if (voiceChanged || uncovered) wake();
  }).observe(root, { attributes: true, attributeFilter: ['class'] });
  wake();

  // ---- LAST ----------------------------------------------------------------
  const KEY = 'rayo.last';
  const WORDS = { web: 'opened the browser', files: 'opened Files', terminal: 'opened a terminal',
    settings: 'opened Settings', displays: 'opened display settings', dnd: 'toggled Focus',
    lock: 'locked the screen', office: 'opened the Office', voice: 'switched voice',
    logout: 'logged you out', suspend: 'put the laptop to sleep', reboot: 'restarted' };
  const store = {
    get() { try { return JSON.parse(localStorage.getItem(KEY)); } catch { return null; } },
    set(v) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch {} },
  };
  const ago = (t) => {
    const m = Math.round((Date.now() - t) / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m} min ago`;
    const h = Math.round(m / 60);
    return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
  };
  const esc = (x) => String(x).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function paint() {
    const v = store.get(), row = $('b-last');
    if (!row) return;
    if (!v || !v.text || Date.now() - v.at > 7 * 86400000) { row.hidden = true; return; }
    const html = `${esc(v.text)}<small>${ago(v.at)}</small>`;
    if ($('b-last-v').innerHTML !== html) $('b-last-v').innerHTML = html;
    row.hidden = false;
  }
  addEventListener('rayo:action', (e) => {
    const d = e.detail || {};
    const text = d.said ? d.said.replace(/[.!]+$/, '') : WORDS[d.act];
    if (!text) return;
    store.set({ text: text.charAt(0).toUpperCase() + text.slice(1), at: Date.now() });
    paint();
  });
  paint(); setInterval(paint, 30000);

  // ---- the MG.OFFICE card opens the Office (overlay action "office") --------
  const office = $('office');
  if (office) {
    const go = () => window.RayoControl && window.RayoControl.action('office');
    office.addEventListener('click', go);
    office.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
  }
})();
