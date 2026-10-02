#!/usr/bin/env bash
# ============================================================================
# Rayo voice setup. Offline, no sudo (everything goes under ~/.local).
#   ./voice-setup.sh                        ears (Vosk + Whisper) + voice (Piper, "Jenny")
#   RAYO_VOICE=en_US-ryan-medium ./voice-setup.sh     pick another Piper voice
# Voices: https://huggingface.co/rhasspy/piper-voices
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/.local/share/rayo-voice"; VENV="$BASE/venv"; MODEL="$BASE/model"; TTS="$BASE/tts"
URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
VOICE="${RAYO_VOICE:-en_GB-jenny_dioco-medium}"
say(){ printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
fetch(){ if command -v curl >/dev/null; then curl -fL "$1" -o "$2"; else wget -O "$2" "$1"; fi; }

say "Creating Python venv at $VENV"
mkdir -p "$BASE"; [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" -q install --upgrade pip
say "Installing Vosk (wake word), Whisper (hearing commands), Piper (voice) and the Anthropic SDK (optional Claude brain)"
"$VENV/bin/pip" -q install vosk faster-whisper piper-tts anthropic

if [ ! -d "$MODEL" ] || [ -z "$(ls -A "$MODEL" 2>/dev/null)" ]; then
  say "Downloading the small English speech model (~40MB, one time)"
  tmp="$BASE/model.zip"; fetch "$URL" "$tmp"
  command -v unzip >/dev/null || { echo "need 'unzip' (sudo apt install unzip)"; exit 1; }
  unzip -oq "$tmp" -d "$BASE"; rm -f "$tmp"
  rm -rf "$MODEL"; mv "$BASE"/vosk-model-small-en-us-* "$MODEL"
fi

if [ ! -f "$TTS/$VOICE.onnx" ]; then
  say "Downloading Rayo's voice: $VOICE (~60MB, one time)"
  loc="${VOICE%%-*}"; quality="${VOICE##*-}"; name="${VOICE#*-}"; name="${name%-*}"   # en_GB / alan / medium
  src="https://huggingface.co/rhasspy/piper-voices/resolve/main/${loc%%_*}/$loc/$name/$quality/$VOICE"
  mkdir -p "$TTS"; fetch "$src.onnx" "$TTS/$VOICE.onnx"; fetch "$src.onnx.json" "$TTS/$VOICE.onnx.json"
fi
if [ "$VOICE" != "en_GB-jenny_dioco-medium" ]; then
  mkdir -p "$HOME/.config/rayo"
  "$VENV/bin/python" -c "import sys; sys.path.insert(0, '$HERE/overlay'); import config; config.set('speech', 'voice', '$VOICE')"
fi

cat <<EOF

✓ Rayo can hear and speak.
  Turn it on: tap the reactor → VOICE, then say "Rayo".
  Push-to-talk once:  $HERE/overlay/voice.sh
  Silence Rayo's voice any time: say "stop talking" (captions stay). "talk to me" turns it back on.

  Optional brain (answers questions, runs locally):
      curl -fsSL https://ollama.com/install.sh | sh && ollama pull gemma3:1b
EOF
