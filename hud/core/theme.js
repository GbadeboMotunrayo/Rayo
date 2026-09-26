/* ============================================================
   Rayo · theme loader
   A theme is just hud/themes/<name>/theme.json — a set of CSS-variable
   values plus wordmark/subtitle/callsign text. This fetches one and applies
   it live (no reload): every colour in the HUD resolves from these tokens.
   Order: ?theme=NAME  →  last choice (localStorage)  →  'rayo'.
   Exposes window.RayoTheme.{apply, cycle, list, current} — control.js's
   THEME menu item calls cycle().
   ============================================================ */
(() => {
  'use strict';
  const THEMES = ['rayo', 'cyberpunk', 'cyborg', 'tron'];
  const KEY = 'rayo.theme';
  const root = document.documentElement;
  let current = 'rayo';

  // Optional personal overrides (hud/user.json, gitignored) applied ON TOP of
  // every theme — lets you set your own wordmark/subtitle/callsign/tokens
  // without editing the shipped themes. Fetched once and cached.
  let userCfg;                       // undefined = not fetched yet
  async function getUser() {
    if (userCfg !== undefined) return userCfg;
    try { const r = await fetch('user.json', { cache: 'no-store' }); userCfg = r.ok ? await r.json() : null; }
    catch (e) { userCfg = null; }
    return userCfg;
  }

  function pickInitial() {
    const q = new URLSearchParams(location.search).get('theme');
    if (q && THEMES.includes(q)) return q;
    try { const s = localStorage.getItem(KEY); if (s && THEMES.includes(s)) return s; } catch (e) {}
    return 'rayo';
  }

  async function apply(name) {
    if (!THEMES.includes(name)) name = 'rayo';
    try {
      const r = await fetch(`themes/${name}/theme.json`, { cache: 'no-store' });
      if (!r.ok) throw new Error('theme ' + name + ' not found');
      const t = await r.json();
      const tok = t.tokens || {};
      for (const k in tok) root.style.setProperty(k, tok[k]);
      const set = (sel, val) => { const el = document.querySelector(sel); if (el && val != null) el.textContent = val; };
      set('.baseline .brand', t.wordmark);
      set('.baseline .sub', t.subtitle);
      set('.status .r', t.callsign);
      // personal overrides win
      const u = await getUser();
      if (u) {
        if (u.tokens) for (const k in u.tokens) root.style.setProperty(k, u.tokens[k]);
        if (u.wordmark) set('.baseline .brand', u.wordmark);
        if (u.subtitle) set('.baseline .sub', u.subtitle);
        if (u.callsign) set('.status .r', u.callsign);
      }
      root.setAttribute('data-theme', name);
      current = name;
      try { localStorage.setItem(KEY, name); } catch (e) {}
    } catch (e) {
      console.log('[rayo theme]', e.message || e);   // keep whatever is applied
    }
  }

  function cycle(dir = 1) {
    const i = THEMES.indexOf(current);
    const next = THEMES[(i + dir + THEMES.length) % THEMES.length];
    apply(next);
    return next;
  }

  window.RayoTheme = { apply, cycle, list: THEMES, get current() { return current; } };
  apply(pickInitial());
})();
