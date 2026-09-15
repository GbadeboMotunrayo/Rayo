#!/usr/bin/env bash
# Rayo — stop the overlay and (optionally) restore the previous wallpaper.
#   ./stop.sh           stop overlay + bridge, restore wallpaper
#   ./stop.sh --keep    stop but leave the dark wallpaper in place
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

pkill -f "rayo-overlay.py" 2>/dev/null || true
pkill -f "overlay/stats.py" 2>/dev/null || true

STATE="$DIR/.wallpaper.prev"
if [[ "$1" != "--keep" && -f "$STATE" ]] && command -v gsettings >/dev/null; then
  PREV="$(tr -d "'" < "$STATE")"
  if [[ -n "$PREV" ]]; then
    gsettings set org.gnome.desktop.background picture-uri "$PREV" 2>/dev/null || true
    gsettings set org.gnome.desktop.background picture-uri-dark "$PREV" 2>/dev/null || true
  fi
  rm -f "$STATE"
fi
echo "▸ Rayo overlay stopped."
