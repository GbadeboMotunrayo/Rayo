#!/usr/bin/env bash
# Launch the one-shot Rayo voice listener (used by the HUD's VOICE action and
# by any keyboard shortcut you bind). Prefers the voice venv from voice-setup.sh.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HOME/.local/share/rayo-voice/venv"
if [ -x "$VENV/bin/python" ]; then exec "$VENV/bin/python" "$DIR/voice.py" "$@"; fi
exec python3 "$DIR/voice.py" "$@"
