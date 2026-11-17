/* ============================================================
   Living dials — the clock's and the weather orb's rings turn.
   Rotating the CSS rings (masked conic gradients) made the software renderer
   recompute the masks every step: measured ~50% -> ~83% of a core. Here each
   ring is drawn ONCE into a small image, and each tick just turns that image
   with a plain CSS rotation. (A first version redrew a 2D canvas each tick: it
   worked in test renders, but the desktop overlay window only ever showed the
   canvas's first frame. CSS transforms always reach the screen.)
   They TICK once a second, like a watch: 10 updates a second still cost ~+20% of
   a core (measured), one a second costs almost nothing. The clock's outer ring
   is a real seconds ring, in step with the wall clock. They keep ticking in calm
   mode (a clock whose seconds ring stops looks broken, and one tick a second is
   nearly free); they stop only when the desktop is covered or the page hidden.
   Colours come from the theme tokens and follow a theme change.
   ============================================================ */
(() => {
  'use strict';
  const root = document.documentElement;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // which rings turn, and how: [cluster, child index (1-based, as in the markup), seconds per turn, direction]
  // seconds per turn of 60 on the clock's outer ring = a seconds hand, set from the wall clock
  const SPIN = [['.clock', 2, 60, 1], ['.clock', 4, 120, -1], ['.clock', 5, 300, 1],
                ['.worb', 2, 90, -1], ['.worb', 3, 180, 1], ['.worb', 5, 45, 1]];
  const tok = (n) => getComputedStyle(root).getPropertyValue(n).trim();
  const rgb = (n) => tok(n).split(/\s+/).join(',');
  const dials = [];

  function ringBitmap(el, size) {
    // draw one ring (as the CSS draws it) into its own canvas at the dial's size
    const cs = getComputedStyle(el);
    const inner = parseFloat(cs.getPropertyValue('--i')), outer = parseFloat(cs.getPropertyValue('--o'));
    const from = parseFloat(cs.getPropertyValue('--f')) || 0;
    const c = document.createElement('canvas'); c.width = c.height = size;
    const g = c.getContext('2d'), k = size / el.offsetWidth, mid = size / 2;
    g.translate(mid, mid); g.scale(k, k);
    if (el.classList.contains('tk')) {                           // tick ring: a 0.5° mark every 5°
      g.strokeStyle = `rgba(${rgb('--ice-rgb')},.5)`; g.lineWidth = (outer - inner);
      for (let a = 0; a < 360; a += 5) {
        g.beginPath(); g.arc(0, 0, (inner + outer) / 2, (a - 90) * Math.PI / 180, (a - 89.5) * Math.PI / 180); g.stroke();
      }
    } else {                                                     // travelling arc: bright head fading over 180°
      const cg = g.createConicGradient((from - 90) * Math.PI / 180, 0, 0);
      cg.addColorStop(0, tok('--ice-bright')); cg.addColorStop(60 / 360, tok('--ice'));
      cg.addColorStop(130 / 360, `rgba(${rgb('--ice-rgb')},.1)`); cg.addColorStop(180 / 360, 'rgba(0,0,0,0)'); cg.addColorStop(1, 'rgba(0,0,0,0)');
      g.strokeStyle = cg; g.lineWidth = outer - inner + 0.5;
      g.beginPath(); g.arc(0, 0, (inner + outer) / 2, 0, Math.PI * 2); g.stroke();
    }
    return c;
  }

  function build() {
    dials.forEach((d) => d.rings.forEach((r) => r.img.remove())); dials.length = 0;
    for (const sel of ['.clock', '.worb']) {
      const box = document.querySelector('.stage ' + sel); if (!box) continue;
      const rings = SPIN.filter((s) => s[0] === sel).map(([, n, secs, dir]) => ({ el: box.children[n - 1], secs, dir }))
        .filter((r) => r.el && r.el.classList.contains('cring'));
      if (!rings.length) continue;
      const b = box.getBoundingClientRect();
      const px = Math.max(32, Math.round(Math.max(b.width, b.height) * Math.min(devicePixelRatio || 1, 1.5)));
      const face = box.querySelector('.face');
      rings.forEach((r) => {
        r.img = new Image(); r.img.className = 'dial-ring'; r.img.alt = ''; r.img.setAttribute('aria-hidden', 'true');
        r.img.src = ringBitmap(r.el, px).toDataURL('image/png');
        box.insertBefore(r.img, face);
        r.el.classList.add('dial-off');
      });
      dials.push({ rings });
    }
    draw();
  }

  function draw() {
    const t = Math.floor(Date.now() / 1000);                     // whole seconds: a tick, in step with the clock
    for (const d of dials) for (const r of d.rings) {
      const deg = ((r.dir * t / r.secs) % 1) * 360;
      r.img.style.transform = `rotate(${deg.toFixed(2)}deg)`;
    }
  }

  let raf = 0, last = 0;
  const stopped = () => document.hidden || root.classList.contains('rayo-idle');
  function frame(now) {
    raf = 0;
    if (stopped()) return;
    const sec = Math.floor(Date.now() / 1000);
    if (sec !== last) { last = sec; draw(); }                      // one tick a second
    raf = requestAnimationFrame(frame);
  }
  function go() { if (!raf && !reduced && dials.length && !stopped()) raf = requestAnimationFrame(frame); }

  new MutationObserver((list) => {
    if (list.some((m) => m.attributeName === 'data-theme' || m.attributeName === 'style')) build();
    go();
  }).observe(root, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] });
  document.addEventListener('visibilitychange', go);
  addEventListener('resize', () => setTimeout(build, 80));
  // wait for the theme's tokens before drawing the bitmaps
  setTimeout(() => { build(); go(); }, 400);
})();
