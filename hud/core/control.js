/* ============================================================
   Rayo · interactive hub control
   Turns the reactor's centre hub into a control surface:
     • single click  → radial menu (12 actions bloom to the ring;
                        hover magnifies each, dock-style)
     • double click  → quick power bar (shutdown/restart/sleep/lock/focus)
     • triple click  → shutdown, with a 4s cancellable countdown
   Actions are sent to the desktop overlay (which runs the real command)
   via window.webkit.messageHandlers.rayo. In a plain browser preview there
   is no bridge, so actions just log to the console.
   ============================================================ */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);

  // ---- bridge to the overlay (or console in preview) -----------------------
  function sendAction(action) {
    try {
      if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.rayo) {
        window.webkit.messageHandlers.rayo.postMessage(JSON.stringify({ action }));
        return;
      }
    } catch (e) { /* fall through to preview log */ }
    // plain browser: VOICE plays a labelled demo so the look can be previewed
    if (action === 'voice' && window.RayoVoice) {
      window.RayoVoice.demoRunning ? window.RayoVoice.stopDemo() : window.RayoVoice.demo();
      return;
    }
    console.log('[rayo action]', action);
  }

  // ---- radial menu items (12, placed every 30° starting at the top) --------
  const ITEMS = [
    { label: 'FILES',    act: 'files' },
    { label: 'TERMINAL', act: 'terminal' },
    { label: 'WEB',      act: 'web' },
    { label: 'SETTINGS', act: 'settings' },
    { label: 'DISPLAYS', act: 'displays' },
    { label: 'FOCUS',    act: 'dnd' },
    { label: 'LOCK',     act: 'lock' },
    { label: 'LOG OUT',  act: 'logout' },
    { label: 'SLEEP',    act: 'suspend' },
    { label: 'RESTART',  act: 'reboot' },
    { label: 'SHUTDOWN', act: 'poweroff', danger: true },
    { label: 'VOICE',    act: 'voice' },
    { label: 'THEME',    act: 'theme' },
  ];
  const RADIUS = 250;                       // px from hub centre (design space)
  const menu = $('hubmenu');
  const bar = $('powerbar');
  if (!menu || !bar) return;

  ITEMS.forEach((it, i) => {
    const ang = (i / ITEMS.length) * 360 - 90;   // -90 → first item at 12 o'clock
    const a = ang * Math.PI / 180;
    const el = document.createElement('button');
    el.className = 'hm-item' + (it.danger ? ' danger' : '');
    el.dataset.act = it.act;
    el.style.setProperty('--x', (Math.cos(a) * RADIUS).toFixed(1) + 'px');
    el.style.setProperty('--y', (Math.sin(a) * RADIUS).toFixed(1) + 'px');
    el.style.setProperty('--i', i);         // stagger on the way in only (CSS)
    el.textContent = it.label;
    el.addEventListener('click', (e) => { e.stopPropagation(); doAction(it.act); });
    menu.appendChild(el);
  });

  // ---- rubber-band pull: an item leans towards the pointer, but less the
  // further you go — iOS's offset = (1 − 1/(c·x/d + 1))·d (docs/MOTION.md §3).
  // It follows 1:1 while you move (.mag), and springs home when you leave.
  const BAND_C = 0.55, BAND_D = 10;
  const band = (x) => Math.sign(x) * (1 - 1 / (BAND_C * Math.abs(x) / BAND_D + 1)) * BAND_D;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  menu.addEventListener('pointermove', (e) => {
    const el = e.target.closest('.hm-item');
    if (!el || reduced.matches || !menu.classList.contains('open')) return;
    // measure from the item's resting centre (take its current pull back out),
    // or the pull would chase itself
    const r = el.getBoundingClientRect(), mx = el._mx || 0, my = el._my || 0;
    el._mx = band(e.clientX - (r.left + r.width / 2 - mx));
    el._my = band(e.clientY - (r.top + r.height / 2 - my));
    el.classList.add('mag');
    el.style.translate = `${el._mx.toFixed(2)}px ${el._my.toFixed(2)}px`;
  });
  const release = (el) => { el.classList.remove('mag'); el.style.translate = ''; el._mx = el._my = 0; };
  menu.addEventListener('pointerout', (e) => {
    const el = e.target.closest('.hm-item');
    if (el && !el.contains(e.relatedTarget)) release(el);
  });

  // ---- open/close helpers --------------------------------------------------
  const openMenu   = () => { menu.classList.add('open');  menu.setAttribute('aria-hidden', 'false'); };
  const closeMenu  = () => {
    menu.classList.remove('open'); menu.setAttribute('aria-hidden', 'true');
    menu.querySelectorAll('.hm-item.mag').forEach(release);   // no leftover pull next time
  };
  const openPower  = () => { bar.classList.add('open');  bar.setAttribute('aria-hidden', 'false'); };
  const closePower = () => { bar.classList.remove('open'); bar.setAttribute('aria-hidden', 'true'); };
  const closeAll   = () => { closeMenu(); closePower(); };

  // ---- Bench mode (holographic schematic, double-tap the hub) --------------
  const bench = $('bench');
  const openBench  = () => { if (bench) { bench.classList.add('open'); bench.setAttribute('aria-hidden', 'false'); } };
  const closeBench = () => { if (bench) { bench.classList.remove('open'); bench.setAttribute('aria-hidden', 'true'); } };
  const toggleBench = () => { if (bench) bench.classList.contains('open') ? closeBench() : openBench(); };
  // exposed so voice commands ("bench mode" / "exit bench") can drive it
  window.RayoControl = { openBench, closeBench, toggleBench, action: (a) => doAction(a) };

  function doAction(act) {
    // THEME cycles the look in-page and keeps the menu open so you can keep
    // tapping to preview each theme.
    if (act === 'theme') { if (window.RayoTheme) window.RayoTheme.cycle(); return; }
    closeAll();
    if (act === 'close') return;
    if (act === 'poweroff') { startCountdown(); return; }
    window.dispatchEvent(new CustomEvent('rayo:action', { detail: { act } }));   // calm.js: wake + "LAST"
    sendAction(act);
  }

  // ---- shutdown countdown (cancellable) ------------------------------------
  let cdTimer = null;
  function startCountdown() {
    let n = 4;
    const box = $('countdown'), num = $('cd-num');
    num.textContent = n;
    box.classList.add('open');
    clearInterval(cdTimer);
    cdTimer = setInterval(() => {
      n -= 1;
      num.textContent = n;
      if (n <= 0) { clearInterval(cdTimer); box.classList.remove('open'); sendAction('poweroff'); }
    }, 1000);
  }
  function cancelCountdown() {
    clearInterval(cdTimer);
    $('countdown').classList.remove('open');
  }
  $('cd-cancel').addEventListener('click', (e) => { e.stopPropagation(); cancelCountdown(); });

  // ---- click-count on the hub: 1 = radial menu, 2 = Bench mode, 3 = shutdown.
  // The first click acts at once (docs/MOTION.md §1) instead of waiting 300ms to
  // rule out a double-click; a 2nd click takes the menu back down at once. Bench
  // itself still waits out the window: it covers the hub, so opening it early
  // would swallow the 3rd click of a triple-click shutdown.
  const hit = $('hub-hit');
  let clicks = 0, tap = null;
  hit.addEventListener('click', (e) => {
    e.stopPropagation();
    clicks += 1;
    clearTimeout(tap);
    if (clicks === 1)      { closePower(); menu.classList.contains('open') ? closeMenu() : openMenu(); }
    else if (clicks === 2) { closeAll(); }
    else                   { closeAll(); startCountdown(); clicks = 0; return; }
    tap = setTimeout(() => { if (clicks === 2) toggleBench(); clicks = 0; }, 300);
  });

  // power-bar buttons
  bar.querySelectorAll('button').forEach((b) => {
    b.addEventListener('click', (e) => { e.stopPropagation(); doAction(b.dataset.act); });
  });

  // Command Deck: launchers + power buttons run their whitelisted action
  document.querySelectorAll('.launch .it, .powerbtns button').forEach((el) => {
    el.addEventListener('click', (e) => { e.stopPropagation(); doAction(el.dataset.act); });
  });

  // ---- glass light: the specular highlight follows the pointer across the
  // hovered glass surface (R4). Set on that element only, so nothing else restyles.
  document.addEventListener('pointermove', (e) => {
    const el = e.target.closest && e.target.closest('.hm-item, .powerbar, .powerbtns button');
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty('--lx', ((e.clientX - r.left) / r.width * 100).toFixed(1) + '%');
    el.style.setProperty('--ly', ((e.clientY - r.top) / r.height * 100).toFixed(1) + '%');
  });

  // ---- launchers: one glass highlight glides to the item under the pointer (R5)
  const launch = document.querySelector('.launch');
  if (launch) {
    const hl = document.createElement('div');
    hl.className = 'hl';
    launch.insertBefore(hl, launch.firstChild);
    launch.addEventListener('pointerover', (e) => {
      const it = e.target.closest('.it');
      if (!it) return;
      if (!launch.classList.contains('hov')) {           // first arrival: appear in place, don't slide in from the top
        hl.style.transition = 'none';
        hl.style.setProperty('--hy', it.offsetTop + 'px');
        void hl.offsetWidth;
        hl.style.transition = '';
      }
      hl.style.setProperty('--hy', it.offsetTop + 'px');
      launch.classList.add('hov');
    });
    launch.addEventListener('pointerleave', () => launch.classList.remove('hov'));
  }

  // Bench: exit button + clicking the backdrop closes it
  const benchExit = $('bench-exit');
  if (benchExit) benchExit.addEventListener('click', (e) => { e.stopPropagation(); closeBench(); });
  if (bench) bench.addEventListener('click', (e) => {
    if (e.target === bench || e.target.classList.contains('bgrid')) closeBench();
  });

  // clicking empty space (or pressing Esc) dismisses everything
  document.addEventListener('click', closeAll);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeAll(); cancelCountdown(); closeBench(); }
  });
})();
