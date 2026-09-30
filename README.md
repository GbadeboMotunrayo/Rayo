<p align="center">
  <img src="assets/rayo-mark.svg" width="96" alt="Rayo">
</p>

<h1 align="center">Rayo</h1>

<p align="center"><b>Your Linux desktop, but make it a superhero.</b><br>
A free, open-source animated HUD that runs on your wallpaper.</p>

<p align="center"><em>RAYO &mdash; Radiant Assistant, Your Oracle</em><br>
<sub>(<em>rayo</em>: Spanish for &ldquo;ray of light / lightning&rdquo; &mdash; the bolt in the mark)</sub></p>

<p align="center">
  <img src="assets/og-card.png" width="760" alt="Rayo - animated comic-hero HUD for Linux">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-78d2ee?style=flat-square" alt="MIT"></a>
  <img src="https://img.shields.io/badge/deps-0-78d2ee?style=flat-square" alt="Zero dependencies">
  <img src="https://img.shields.io/badge/themes-4-78d2ee?style=flat-square" alt="4 themes">
  <img src="https://img.shields.io/badge/platform-Linux-06080b?style=flat-square" alt="Linux">
</p>

Rayo overlays a living, breathing sci-fi interface on your desktop: a glowing
arc-reactor that pulses, glass panels showing your *real* system stats, a live
fan speedometer, and an interactive control hub. Theme it as Iron Man,
Cyberpunk, Cyborg, Tron, or build your own hero.

It is plain HTML/CSS/JS (so it can actually *animate*, unlike conky/Rainmeter)
plus one dependency-free Python file that feeds it real `/proc` data.

## Try it now, no install

Rayo is a web app at heart, so you can run the interface in your browser:

**[▶ Live demo](https://GbadeboMotunrayo.github.io/Rayo/)** *(enable GitHub Pages on this repo to serve it)*, or locally:

```bash
git clone https://github.com/GbadeboMotunrayo/Rayo.git
cd Rayo && ./run.sh          # opens the HUD at http://localhost:8099
```

## Install (on your desktop)

One line:

```bash
curl -fsSL https://raw.githubusercontent.com/GbadeboMotunrayo/Rayo/main/install.sh | bash
```

or clone and run:

```bash
git clone https://github.com/GbadeboMotunrayo/Rayo.git
cd Rayo && ./start.sh
```

`start.sh` sets a clean backdrop and mounts the transparent, click-through
overlay behind your windows. Turn it off with `./stop.sh`. The installer also
offers to start Rayo at every login.

Most GNOME/KDE systems already have what Rayo needs (`python3-gi`, `gtk-3.0`,
`webkit2gtk-4.1`). If not, on Debian/Ubuntu:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

## The control hub

Click the reactor at the center:

- **Single click** opens a radial menu (files, terminal, web, settings, lock,
  sleep, restart, shutdown, theme, and more), each magnifying on hover.
- **Double click** opens a quick power bar (shutdown / restart / sleep / lock).
- **Triple click** shuts down, with a 4-second cancel countdown.

## Themes

A theme is a single `hud/themes/<name>/theme.json` of colour tokens. Every
colour in the HUD resolves from them, so a new theme is one JSON file.

| Theme | Vibe |
|-------|------|
| **RAYO** | Iron Man. Ice-blue and gold. |
| **Cyberpunk** | Night-city neon. Magenta and yellow. |
| **Cyborg** | Combat chassis. Molten amber. |
| **Tron** | The Grid. Electric cyan on black. |

Switch live from the hub (**THEME**), or load one with `?theme=tron`. Your
choice is remembered. Make it yours without touching themes by copying
`hud/user.example.json` to `hud/user.json` (wordmark, tagline, colours).

New hero themes are the most welcome contribution. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## How it works

```
overlay/stats.py  ── writes ──▶  hud/stats.json  ── polled 1s ──▶  hud/core/*.js  ── renders ──▶  the HUD
   (/proc, /sys)
```

- `hud/index.html` plus `hud/core/` is the whole interface: a fixed 1920x1200
  design that scales to fit any screen.
- `hud/core/theme.js` applies a theme's tokens live; `control.js` drives the
  hub; `hud.js` renders the live data.
- `overlay/stats.py` is the only backend: no pip installs, standard library
  only, reads `/proc` and `/sys` once a second.
- `overlay/rayo-overlay.py` hosts the HUD as a transparent desktop window and
  pauses it when covered, so it idles near 0% CPU.

## Roadmap

- Config UI (toggle panels, pick accent, reactor position)
- More hero themes (Batman, Halo/Cortana, Samus) via community PRs
- Layer-shell backend for pixel-perfect anchoring on wlroots (Hyprland, sway)

## Voice (optional)

Talk to Rayo, offline and private. Recognition runs on-device via Vosk
(~40MB, no cloud). Two ways to use it:

- **Push-to-talk** (zero idle cost): trigger it, say one command, it runs and
  exits. Nothing runs in the background.
- **Wake word**: say **"Rayo"** (or "wake up") and it takes your next command.
  Toggle it from the hub (reactor -> **VOICE**); it's **off by default** because
  keeping an ear open uses a small continuous CPU. On = "Rayo is listening",
  off = back to zero.

```bash
./voice-setup.sh    # one-time: Vosk + Whisper (ears) + Piper (voice), under ~/.local (no sudo)
```

The wake word runs on Vosk (tiny, always listening). What you say after it
is transcribed by [Whisper](https://github.com/SYSTRAN/faster-whisper) `base.en`,
which gets names like "Paystack" right (~1.5s per command, ~200MB while voice
is on). Add your own hard words with `{"ears": {"vocab": ["Adunnwa", "CarPadi"]}}`
in `~/.config/rayo/config.json`, or go back to Vosk-only with `{"ears": {"engine": "vosk"}}`.

Rayo talks back, offline, with [Piper](https://github.com/OHF-Voice/piper1-gpl)
(default voice: British "Jenny"). It answers out loud, asks its follow-up
questions out loud, and the reactor pulses with its voice as it speaks. Say
**"stop talking"** for captions only, and **"talk to me"** to bring the voice back.
Pick another voice with `RAYO_VOICE=en_US-ryan-medium ./voice-setup.sh`.

**Turning it on and off:** tap the reactor once to open the radial menu, then
tap **VOICE**. Do the same to turn it off. The reactor shows you what's happening:

| State | What you see |
|-------|--------------|
| Armed | "VOICE ARMED" in the top strip, a faint ring around the core, VOICE glows in the menu |
| Listening | the core pulses with your voice and a spectrum ring flares around it |
| Thinking | "VOICE · THINKING" in gold while the brain works on an answer |
| Speaking | the core pulses with Rayo's own voice |
| Heard | your words as a subtitle under the reactor, with the result beneath |
| Problem | a red message under the reactor (e.g. "run ./voice-setup.sh") |

Say **"Rayo"**, wait for the chime, then:

| Say | Rayo does |
|-----|-----------|
| "open claude" · "open obs" · "launch calculator" | opens **any installed app** by name |
| "open browser" · "open files" · "open terminal" | your default browser, file manager, terminal |
| "launch browser" | asks *"which browser? brave, chromium or firefox"*, then opens the one you name ("firefox", "the second one", "default") |
| "open documents" · "open downloads" · "open desktop" | your standard folders |
| "open tech" · "open the carpadi folder" | **any folder** by name, fuzzy-matched |
| "open downloads and tech" | several folders at once |
| "open document" | asks *"which document?"*, then opens the one you name |
| "open document readme" | a document by name, straight away |
| "search for weather in lagos" | a web search |
| "open youtube" · "go to github" · "open gmail" | common sites |
| "volume up / down" · "mute" · "unmute" | sound |
| "play" · "pause" · "next song" · "previous song" | any playing media |
| "what time is it" · "what's the date" · "battery" · "temperature" | answers on the HUD |
| "next theme" · "bench mode" · "exit bench" | the HUD itself |
| "settings" · "wifi / bluetooth / sound / display settings" | system settings |
| "lock" · "sleep" · "focus" · "help" | system |

When Rayo needs a detail it asks, and the question shows under the reactor.
Just answer; no wake word is needed. It asks at most twice, and "cancel" or
"never mind" backs out. The same goes for "open folder", "launch app" and
"search".

Apps and folders are discovered from your machine, so new ones work without
changes. Power actions (shutdown/restart) stay on the hub, by design: a
misheard word must never turn your machine off. The full grammar lives in
[`overlay/commands.py`](overlay/commands.py).

### The brain (optional)

Anything that isn't a command goes to a small local LLM through
[Ollama](https://ollama.com): "why is the sky blue", "tell me a joke", "who
wrote Things Fall Apart". The answer types itself out under the reactor. It
remembers the last few exchanges, so "and how old is he?" works.

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma3:1b        # ~800MB; any chat model works
```

- **Private:** it runs on your machine and talks only to `127.0.0.1`.
- **Light:** the model loads when you say "Rayo" and unloads 3 minutes after
  your last question. A 1-2B model uses about 1.3GB of memory while it's loaded.
- **Talk, never act:** the brain can't run commands. Opening apps and folders
  still goes through the fixed command list, so a model mistake can't touch
  your machine.
- **Pick a model:** Rayo uses `gemma3:1b` if you have it, otherwise the first
  model Ollama has. To choose one, set `RAYO_BRAIN_MODEL`, or put
  `{"brain": {"model": "qwen3:1.7b"}}` in `~/.config/rayo/config.json`.

### Memory (an Obsidian vault)

Rayo's memory is plain Markdown in `~/Documents/Rayo`, a folder that opens as
an [Obsidian](https://obsidian.md) vault. Nothing is hidden in a database: what
you see in the vault is what Rayo knows.

| Say | Rayo does |
|-----|-----------|
| "remember that my sister's name is Tolu" | adds a bullet to `Memory/Facts.md` |
| "what's my sister's name?" | the brain reads relevant facts before answering |
| "what do you remember" | reads back your latest facts |
| "forget that" | removes the last fact |
| "open memory" | opens the vault in Obsidian (or the folder) |

Every exchange is also logged to `Daily/YYYY-MM-DD.md`. To change the vault
location, or turn the log off, edit `~/.config/rayo/config.json`:
`{"memory": {"vault": "~/Notes/Rayo", "log": false}}`.

Small models get facts wrong sometimes, especially dates, ages and recent
events. Treat answers as a quick guess, not a source.

## Support

Rayo is free and always will be. If it made your desktop cooler, a tip funds new
themes and build time:

- Ko-fi: [ko-fi.com/motunrayogbadebo](https://ko-fi.com/motunrayogbadebo)

Starring the repo, filing issues, and sending theme PRs help just as much.

## Credits

The living-orb technique and glass-panel recipe were studied from
[JashanMaan28/Zorin](https://github.com/JashanMaan28/Zorin) (MIT). Arc-reactor
composition is original. Iron Man, JARVIS, Tron and related names are
trademarks of their owners; Rayo ships no copyrighted artwork and its themes are
original interpretations.

## License

MIT. See [LICENSE](LICENSE). Use it, fork it, theme it, share it.
