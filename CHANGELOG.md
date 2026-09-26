# Changelog

All notable changes to Rayo are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com); versions follow semver.

## [1.0.0] - 2026-09-26

First stable release. Rayo is a themeable, animated, interactive HUD that runs
as a transparent layer on the Linux desktop.

### Added
- **Animated HUD** (`hud/`): breathing arc-reactor, glassmorphism panels, and
  live readouts that scale to any resolution.
- **Live system bridge** (`overlay/stats.py`): dependency-free, reads
  `/proc` + `/sys` for CPU, memory, disk, battery (with charge ETA), network
  throughput, wifi, and **fan RPM**. Weather via wttr.in.
- **Fan speedometer** in Live Telemetry, ported from the Carpadi gauge concept,
  colour-shifting ice → gold → red with load.
- **Interactive control hub**: single-click radial menu, double-click power bar,
  triple-click shutdown with a cancellable countdown. Actions run through a
  whitelisted JS→system bridge.
- **Theme system** with four themes: RAYO, Cyberpunk, Cyborg, Tron. A theme is a
  single JSON file; switch live from the hub, persisted across restarts.
- **Personal overrides** via `hud/user.json` (wordmark / subtitle / callsign /
  tokens) that survive updates.
- **Desktop overlay** (`overlay/rayo-overlay.py`): transparent, click-through,
  always-below WebKitGTK window; pauses animation when covered to idle near 0%
  CPU; auto-picks the external screen when present.
- **Auto multi-monitor calibration + HDMI audio routing**
  (`rayo-autodisplay.py`, distributed separately as a user service).
- Brand identity (logo, favicon, social card), a live **landing page**
  (`index.html`, GitHub-Pages ready), one-line **installer**, and docs.

### Performance
- Rings promoted to compositor layers (`will-change`) and step-rendered; overlay
  dropped from ~96% of a CPU core to ~18%, and to ~0% when hidden.

[1.0.0]: https://github.com/GbadeboMotunrayo/Rayo/releases/tag/v1.0.0
