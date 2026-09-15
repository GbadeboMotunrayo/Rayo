#!/usr/bin/env bash
# Rayo — start the live desktop overlay.
# Portable: derives its own paths, works from any clone location.
#   ./start.sh          switch on the Rayo overlay
#   ./start.sh --keep-wallpaper   don't touch the current wallpaper
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. stop anything that would fight the overlay (old conky, previous overlay)
pkill -f "conky" 2>/dev/null || true
pkill -f "rayo-overlay.py" 2>/dev/null || true
pkill -f "overlay/stats.py" 2>/dev/null || true
sleep 0.4

# 2. set a clean dark backdrop so the transparent overlay reads clearly
if [[ "$1" != "--keep-wallpaper" ]] && command -v gsettings >/dev/null; then
  # remember the current wallpaper once, so stop.sh can restore it
  STATE="$DIR/.wallpaper.prev"
  [[ -f "$STATE" ]] || gsettings get org.gnome.desktop.background picture-uri > "$STATE" 2>/dev/null || true
  WP="$DIR/hud/themes/rayo/wallpaper.png"
  gsettings set org.gnome.desktop.background picture-uri "file://$WP" 2>/dev/null || true
  gsettings set org.gnome.desktop.background picture-uri-dark "file://$WP" 2>/dev/null || true
  gsettings set org.gnome.desktop.background picture-options "zoom" 2>/dev/null || true
fi

# 3. launch the overlay detached so it survives this terminal
#    (it starts the stats bridge itself)
setsid python3 "$DIR/overlay/rayo-overlay.py" </dev/null >/tmp/rayo-overlay.log 2>&1 &
disown 2>/dev/null || true
sleep 1

if pgrep -f rayo-overlay.py >/dev/null; then
  echo "▸ Rayo overlay is running. Your desktop is live."
  echo "  stop it with:  $DIR/stop.sh"
else
  echo "✗ overlay did not stay up — see /tmp/rayo-overlay.log"
  tail -5 /tmp/rayo-overlay.log 2>/dev/null || true
fi
