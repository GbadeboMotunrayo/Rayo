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
    el.style.setProperty('--x', (Math.cos(a) * RADIUS).toFixed(1) + 'px');
    el.style.setProperty('--y', (Math.sin(a) * RADIUS).toFixed(1) + 'px');
    el.style.transitionDelay = (i * 14) + 'ms';
    el.textContent = it.label;
    el.addEventListener('click', (e) => { e.stopPropagation(); doAction(it.act); });
    menu.appendChild(el);
  });

  // ---- open/close helpers --------------------------------------------------
  const openMenu   = () => { menu.classList.add('open');  menu.setAttribute('aria-hidden', 'false'); };
  const closeMenu  = () => { menu.classList.remove('open'); menu.setAttribute('aria-hidden', 'true'); };
  const openPower  = () => { bar.classList.add('open');  bar.setAttribute('aria-hidden', 'false'); };
  const closePower = () => { bar.classList.remove('open'); bar.setAttribute('aria-hidden', 'true'); };
  const closeAll   = () => { closeMenu(); closePower(); };

  function doAction(act) {
    // THEME cycles the look in-page and keeps the menu open so you can keep
    // tapping to preview each theme.
    if (act === 'theme') { if (window.RayoTheme) window.RayoTheme.cycle(); return; }
    closeAll();
    if (act === 'close') return;
    if (act === 'poweroff') { startCountdown(); return; }
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

  // ---- click-count on the hub: 1 = menu, 2 = power, 3 = shutdown -----------
  const hit = $('hub-hit');
  let clicks = 0, tap = null;
  hit.addEventListener('click', (e) => {
    e.stopPropagation();
    clicks += 1;
    clearTimeout(tap);
    tap = setTimeout(() => {
      if (clicks === 1)      { closePower(); menu.classList.contains('open') ? closeMenu() : openMenu(); }
      else if (clicks === 2) { closeMenu();  bar.classList.contains('open') ? closePower() : openPower(); }
      else                   { closeAll();   startCountdown(); }
      clicks = 0;
    }, 300);
  });

  // power-bar buttons
  bar.querySelectorAll('button').forEach((b) => {
    b.addEventListener('click', (e) => { e.stopPropagation(); doAction(b.dataset.act); });
  });

  // clicking empty space (or pressing Esc) dismisses everything
  document.addEventListener('click', closeAll);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeAll(); cancelCountdown(); }
  });
})();
