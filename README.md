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
| Desktop overlay window (transparent, click-through, always-below) | ✅ working — `start.sh` mounts the HUD on the desktop |
| Theme system + more themes | 🔜 in progress (RAYO ships first) |
| One-command installer | 🔜 |

## Quickstart (clone & run)

```bash
git clone https://github.com/GbadeboMotunrayo/Rayo.git
cd Rayo
./start.sh          # switches on the live desktop overlay
```

That stops anything competing (old conky), sets a clean dark backdrop, and
launches the transparent overlay — your desktop goes live, showing your real
CPU, memory, battery (with charge/discharge ETA), disk, and network up/down.

Turn it off and restore your wallpaper:

```bash
./stop.sh
```

**Auto-start on login:** copy `overlay/rayo.desktop.example` to
`~/.config/autostart/rayo.desktop`, with `Exec=` pointing at this repo's
`start.sh`.

### Just want to preview the HUD in a browser?

```bash
./run.sh            # serves the HUD at http://localhost:8099 with live data
```

Without the bridge it falls back to smooth mock data, so it always looks alive.

## Run it on your desktop (the real overlay)

No extra install on most GNOME systems (uses `python3-gi`, `gtk-3.0`,
`webkit2gtk-4.1` — already present). If missing:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

Then:

```bash
python3 overlay/rayo-overlay.py     # transparent, click-through, sits on the desktop
```

It mounts the HUD as an XWayland desktop-type window (the same technique conky
uses), behind your normal windows, and starts the stats bridge itself. Quit with
`pkill -f rayo-overlay.py`. To auto-start on login, copy
`overlay/rayo.desktop.example` into `~/.config/autostart/` (edit the path first).

> Note: true desktop-layer placement on GNOME/Wayland relies on XWayland
> window hints; on wlroots compositors (Hyprland, sway) a layer-shell backend
> is planned for pixel-perfect anchoring.

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

## Support / Donate

Rayo is free and open-source, built in the open. If it made your desktop
cooler, a small tip helps cover hosting and buys build time for new hero
themes and the one-line installer:

- ☕ **Ko-fi:** [ko-fi.com/motunrayogbadebo](https://ko-fi.com/motunrayogbadebo)
<!-- - 💳 **Paystack** (Nigeria-friendly): https://paystack.com/pay/your-slug -->

Not into money? **Starring the repo**, filing issues, and sending **theme
pull requests** help just as much. 🙏

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, theme it, share it.
