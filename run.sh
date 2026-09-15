#!/usr/bin/env bash
# HeroHUD — start the live data bridge + serve the HUD, then open it.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8099}"

# start stats bridge (idempotent: kill any prior)
pkill -f "overlay/stats.py" 2>/dev/null || true
python3 "$DIR/overlay/stats.py" --interval 1 &
echo "▸ stats bridge running (pid $!)"

echo "▸ serving HUD at http://localhost:$PORT"
echo "  open that in your browser — it shows YOUR live system."
cd "$DIR/hud"
exec python3 -m http.server "$PORT"
