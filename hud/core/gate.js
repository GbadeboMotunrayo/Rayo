/* Startup gate: play the startup only once the PC has settled (see GATE in the styles).
   Settled = the page has finished loading, then 0.6 s in which a 100 ms timer never runs
   more than 60 ms late (the page isn't starved of CPU). It doesn't look at total CPU:
   Rayo's own loading (3D reactor, page) pushed that over any limit and made the gate wait
   its full fallback on an idle PC. Frame rate isn't used either: Rayo's window draws few
   frames by design. Never waits more than 6 s; the check stops once it fires.
   Each start is reported to the overlay log: "[rayo] startup played at 2.6s (calm)". */
(() => {
  const root = document.documentElement, T0 = performance.now();
  const CALM_MS = 600, LATE_MS = 60, MAX_MS = 6000;
  let go = false, loaded = document.readyState === 'complete', calmSince = 0, last = T0;
  const fire = (why) => {
    if (go) return;
    go = true;
    root.classList.replace('boot-hold', 'boot-go');
    root.dataset.bootWhy = why;
    const at = ((performance.now() - T0) / 1000).toFixed(1);
    try {
      const h = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.rayo;
      if (h) h.postMessage(JSON.stringify({ action: 'boot', why, at }));
    } catch (_) { /* a plain browser preview has no bridge */ }
  };
  addEventListener('load', () => { loaded = true; calmSince = performance.now(); });
  function tick() {
    if (go) return;
    const now = performance.now(), late = now - last - 100; last = now;
    if (late > LATE_MS || !loaded) calmSince = now;
    if (loaded && now - calmSince >= CALM_MS) return fire('calm');
    setTimeout(tick, 100);
  }
  setTimeout(tick, 100);
  setTimeout(() => fire('timeout'), MAX_MS);
})();
