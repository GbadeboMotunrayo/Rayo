# Rayo

**Turn your Linux desktop into your favourite comic-hero interface.**
Fluid. Animated. Live. Free.

Rayo is an open-source, themeable heads-up display for Linux desktops.
It overlays a living, breathing sci-fi interface on your wallpaper —
a glowing arc-reactor that pulses, glassmorphism panels that show your
*real* system stats (CPU, memory, battery, network), rotating reticles,
drifting scanlines — the works. Theme #1 is **RAYO** (Iron Man style);
the theming system is built so anyone can add Batman, Halo, cyberpunk,
Cortana, or their own.

> Built with plain HTML/CSS/JS so it can *animate* — the thing static
> tools like conky/Rainmeter can never do — and a tiny dependency-free
> Python bridge that feeds it real `/proc` data.

---

## Status

| Piece | State |
|-------|-------|
| Animated HUD front-end (`hud/`) | ✅ working — breathing reactor, glass panels, live gauges, scales to any resolution |
| System-stats bridge (`overlay/stats.py`) | ✅ working — pure stdlib, reads `/proc` + `/sys`, writes `hud/stats.json` |
| Desktop overlay window (transparent, click-through, always-below) | 🔜 next — mounts the HUD *on the desktop* behind your windows |
| Theme system + more themes | 🔜 in progress (RAYO ships first) |
| One-command installer | 🔜 |

## Try it now (browser preview)

```bash
cd herohud
python3 overlay/stats.py --interval 1 &     # start the live data bridge
python3 -m http.server 8099 --directory hud # serve the HUD
# open http://localhost:8099 in any browser — it shows YOUR real stats
```

Without the bridge running it falls back to smooth mock data, so the HUD
always looks alive.

## How it works

```
overlay/stats.py  ──writes──▶  hud/stats.json  ──polled by──▶  hud/core/hud.js  ──renders──▶  the HUD
   (/proc, /sys)                (every 1s)                      (eased, 90ms frames)
```

- **`hud/index.html`** — the whole interface, one file. A fixed 1920×1200
  design that scale-to-fits any screen.
- **`hud/core/hud.js`** — polls `stats.json`, eases every value so bars and
  numbers *glide* instead of jumping, drives the reactor's reaction to load.
- **`hud/themes/`** — a theme is just a palette + a few assets (see
  `themes/rayo/`). Swappable.
- **`overlay/stats.py`** — the only "backend". No pip installs, no daemon
  framework — one file, standard library.

## Roadmap

1. **Desktop overlay window** — a transparent, click-through, always-below
   WebKitGTK window that hosts the HUD on the desktop itself (replaces the
   browser preview; this is what makes it a real rice, not a web page).
2. **Theme gallery** — RAYO (Iron Man) → Batcomputer → Halo/Cortana →
   cyberpunk. Community themes via pull request.
3. **Config UI** — pick theme, toggle panels, set accent, choose which
   corner the reactor lives in.
4. **One-line install** for GNOME / KDE / Hyprland.

## Credits & references

The living-orb technique (three concentric radial-gradient layers animated on
non-synchronising timings for organic motion) and the glassmorphism panel
recipe were studied from [JashanMaan28/Zorin](https://github.com/JashanMaan28/Zorin)
(MIT). Arc-reactor / HUD composition is original. Iron Man, JARVIS, FRIDAY and
related names are trademarks of their owners — Rayo ships no copyrighted
artwork; themes are original interpretations.

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, theme it, share it.
