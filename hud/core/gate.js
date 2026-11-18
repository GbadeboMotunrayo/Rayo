/* Startup gate: play the startup only once the PC has settled (see GATE in the styles).
   Settled = 0.8 s in which a 100 ms timer never runs more than 60 ms late (the page isn't
   starved of CPU) and, once stats arrive, CPU under 45%. Frame rate isn't used: Rayo's
   window draws few frames by design. Never waits more than 10 s; the check stops on firing. */
(() => {
  const root = document.documentElement, T0 = performance.now();
  let go = false, cpuOk = false, calmSince = T0, last = T0;
  const fire = (why) => { if (go) return; go = true; root.classList.replace('boot-hold', 'boot-go'); root.dataset.bootWhy = why; };
  addEventListener('rayo:data', (e) => { const c = e.detail && e.detail.cpu; if (c != null && c < 45) cpuOk = true; });
  function tick() {
    if (go) return;
    const now = performance.now(), late = now - last - 100; last = now;
    if (late > 60) calmSince = now;
    const waited = now - T0;
    if (waited > 10000) return fire('timeout');
    if (now - calmSince > 800 && (cpuOk || waited > 4000) && waited > 400) return fire('calm');
    setTimeout(tick, 100);
  }
  setTimeout(tick, 100);
  setTimeout(() => fire('timeout'), 10000);
})();
