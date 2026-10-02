#!/usr/bin/env bash
# ============================================================================
# Give Rayo her Claude brain: store your Anthropic API key privately.
#   ./set-claude-key.sh
# The key is typed into a hidden prompt (it never appears on screen or in shell
# history) and saved to ~/.config/rayo/anthropic.key, readable only by you.
# Get a key at https://console.anthropic.com -> API keys, and set a monthly
# spend limit there. Rayo has her own cap too (default 3 dollars a month).
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HOME/.local/share/rayo-voice/venv/bin/python"
KEY_FILE="$HOME/.config/rayo/anthropic.key"
[ -x "$PY" ] || { echo "Run ./voice-setup.sh first."; exit 1; }
"$PY" -c "import anthropic" 2>/dev/null || "$HOME/.local/share/rayo-voice/venv/bin/pip" -q install anthropic

read -rsp "Paste your Anthropic API key (input is hidden): " KEY; echo
KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
case "$KEY" in sk-ant-*) ;; *) echo "That doesn't look like an Anthropic key (it should start with sk-ant-)."; exit 1;; esac

mkdir -p "$(dirname "$KEY_FILE")"; umask 077
printf '%s\n' "$KEY" > "$KEY_FILE"; chmod 600 "$KEY_FILE"

echo "Checking the key with Anthropic (this is free)..."
if KEY="$KEY" "$PY" - <<'PY'
import os, anthropic
try:
    anthropic.Anthropic(api_key=os.environ["KEY"], base_url="https://api.anthropic.com", max_retries=0, timeout=15).models.list(limit=1)
    print("✓ The key works.")
except anthropic.AuthenticationError:
    raise SystemExit("✗ Anthropic rejected that key. Check it and run this again.")
except anthropic.APIConnectionError:
    print("(Couldn't reach Anthropic to check it. The key is saved; try again when you're online.)")
PY
then
  echo "Saved to $KEY_FILE. Restart Rayo, then say: \"Rayo, ask Claude why the sky is blue.\""
else
  rm -f "$KEY_FILE"; exit 1
fi
