# Security

Rayo runs on your desktop, can launch apps, and (with your confirmation) can power the
machine off, so it is built to expose as little as possible.

## What Rayo exposes

| Surface | Exposure |
|---------|----------|
| HUD web server (port 8791) | **This PC only** (`127.0.0.1`). Requests must carry a `127.0.0.1` or `localhost` Host header (blocks DNS-rebinding from web pages). GET/HEAD only, no directory listings, no dotfiles, nothing outside `hud/` (symlinks included). |
| Page security | Strict Content-Security-Policy (only our own scripts run), no inline scripts, `nosniff`, no framing, no referrer, no mic/camera/location. No `innerHTML`/`eval` anywhere. |
| The HUD window | Locked to its own origin: other URLs, redirects and pop-ups are refused; the page gets no permissions; the hub bridge ignores messages unless our own page is loaded. Only a fixed list of actions can run. |
| Ollama (port 11434) | This PC only (its default). Keep it updated. |
| Commands | Run as argument lists, never through a shell. Power actions always ask "Are you sure?" first (turn off with `{"security": {"voice_power": false}}`). The AI model can talk but cannot act. |
| Secrets | API keys live in `~/.config/rayo/*.key` (`chmod 600`, folder `700`), are never committed (`*.key` is ignored), and are only ever sent to their own provider. Your notes and memory (`~/Documents/Rayo`) are `700`. |
| What leaves the laptop | Only the question you asked and the last couple of exchanges, to the cloud brain you chose, and never your vault, memories, files or battery. |

## Check yourself

```bash
./security/security-check.sh          # read-only audit; changes nothing, needs no sudo
sudo ./security/security-harden.sh    # turns on the firewall (deny all incoming)
```

## Not covered by Rayo (your machine)

- **A firewall is off by default on Ubuntu.** Anything listening on `0.0.0.0` is reachable by everyone on the
  same Wi-Fi. `security-harden.sh` enables `ufw`.
- **Docker bypasses the firewall.** A container published as `8087:80` is open to the network. Publish as
  `127.0.0.1:8087:80`, or stop the container.
- **Membership of the `docker` group is root-equivalent.** Only do it if you accept that.
- **The disk is not encrypted** unless you chose that at install. Keep a strong login password and lock the screen.
- **Voice can be spoofed by audio.** A video playing "Rayo, shut down... yes" through your speakers is, in
  principle, enough. If that worries you, turn voice power off (above) and use the hub.
- **Supply chain.** Rayo installs packages from PyPI and downloads speech models over HTTPS without checksums.
  Install only on machines you trust.

## Reporting a problem

Open an issue on the repository, or email the maintainer for anything sensitive. Please don't post exploits publicly
before there is a fix.
