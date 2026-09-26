# Contributing to Rayo

Thanks for helping make Linux desktops look heroic. Rayo is intentionally
small and dependency-free, so contributing is easy.

## Ground rules

- **No build step, no framework, no dependencies.** The HUD is plain
  HTML/CSS/JS; the bridge is one stdlib Python file. Keep it that way.
- Test your change in the browser first (`./run.sh` then open the printed URL),
  and on the real desktop (`./stop.sh && ./start.sh`) if it touches the overlay.
- One change per pull request. Keep commits focused.

## Add a theme (the most wanted contribution)

A theme is a single JSON file of colour tokens. To add "Batman":

1. Copy an existing theme folder:
   ```bash
   cp -r hud/themes/tron hud/themes/batman
   ```
2. Edit `hud/themes/batman/theme.json`. Set the palette (all `--*` tokens),
   plus `wordmark`, `subtitle`, and `callsign`. The `--ice*` tokens are the
   hero colour; `--gold` is the accent; `--red` stays for alerts. The
   `*-rgb` tokens must match their hex counterparts as `R G B` triples.
3. Register it: add `'batman'` to the `THEMES` array in
   [`hud/core/theme.js`](hud/core/theme.js).
4. Preview it: `./run.sh`, then open the demo with `?theme=batman`, or cycle to
   it from the hub's THEME control.

Good themes are legible (bars, text, and the fan gauge's red zone must all read
clearly) and distinct from the ones that already ship.

## Code style

- CSS colours resolve from the theme tokens in `:root`. Never hard-code a hero
  colour as a literal `rgba(...)`; use `rgb(var(--ice-rgb) / <alpha>)`.
- Keep animations compositor-friendly (`transform`/`opacity`), and honour
  `prefers-reduced-motion`.
- The overlay only runs actions from the `ACTIONS` whitelist in
  [`overlay/rayo-overlay.py`](overlay/rayo-overlay.py). Do not open that up to
  arbitrary commands.

## Reporting bugs

Open an issue with your distro, desktop environment (GNOME/KDE/…), and whether
you are on Wayland or X11. A screenshot helps a lot.
