#!/usr/bin/env bash
# ============================================================================
# Rayo voice setup — offline, push-to-talk. No sudo (installs into ~/.local).
#   ./voice-setup.sh
# Zero idle cost: nothing runs in the background; the listener only wakes when
# you trigger it (hub VOICE item, or a keyboard shortcut you bind).
# ============================================================================
set -euo pipefail
BASE="$HOME/.local/share/rayo-voice"; VENV="$BASE/venv"; MODEL="$BASE/model"
URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
say(){ printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

say "Creating Python venv at $VENV"
mkdir -p "$BASE"; python3 -m venv "$VENV"
"$VENV/bin/pip" -q install --upgrade pip
say "Installing Vosk + sounddevice (offline speech)"
"$VENV/bin/pip" -q install vosk sounddevice || {
  echo "pip install failed. You may need PortAudio:  sudo apt install libportaudio2"; exit 1; }

if [ ! -d "$MODEL" ] || [ -z "$(ls -A "$MODEL" 2>/dev/null)" ]; then
  say "Downloading the small English model (~40MB, one time)"
  tmp="$BASE/model.zip"
  if command -v curl >/dev/null; then curl -fL "$URL" -o "$tmp"; else wget -O "$tmp" "$URL"; fi
  command -v unzip >/dev/null || { echo "need 'unzip' (sudo apt install unzip)"; exit 1; }
  unzip -oq "$tmp" -d "$BASE"; rm -f "$tmp"
  rm -rf "$MODEL"; mv "$BASE"/vosk-model-small-en-us-* "$MODEL"
fi

cat <<EOF

✓ Rayo voice is ready.
  Test it now (say e.g. "open browser"):
      $HOME/Desktop/Tech/herohud/overlay/voice.sh
  Wake word: click the reactor → VOICE to toggle "say Rayo" listening.
  Or push-to-talk once:
  Or bind a key: GNOME Settings → Keyboard → Shortcuts → add
      Command:  $HOME/Desktop/Tech/herohud/overlay/voice.sh
  Commands: "open browser / files / terminal / settings / displays",
            "lock", "sleep", "focus".  (Shutdown/restart stay on the hub.)
EOF
