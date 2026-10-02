#!/usr/bin/env bash
# ============================================================================
# Give Rayo a cloud brain: store an API key privately.
#   ./set-key.sh groq      free plan, no card: https://console.groq.com/keys
#   ./set-key.sh claude    pay-as-you-go:      https://console.anthropic.com
# The key goes into a hidden prompt (never on screen, never in shell history) and is
# saved to ~/.config/rayo/<provider>.key, readable only by you. It is checked
# with a free request before it is kept.
# ============================================================================
set -euo pipefail
WHO="${1:-}"
case "$WHO" in
  groq)             FILE="groq.key";      PROVIDER="groq";      LABEL="Groq";   PKG="groq";      HINT="gsk_";;
  claude|anthropic) FILE="anthropic.key"; PROVIDER="anthropic"; LABEL="Claude"; PKG="anthropic"; HINT="sk-ant-";;
  *) echo "Usage: ./set-key.sh groq   or   ./set-key.sh claude"; exit 1;;
esac
PY="$HOME/.local/share/rayo-voice/venv/bin/python"
KEY_FILE="$HOME/.config/rayo/$FILE"
[ -x "$PY" ] || { echo "Run ./voice-setup.sh first."; exit 1; }
"$PY" -c "import $PKG" 2>/dev/null || "$HOME/.local/share/rayo-voice/venv/bin/pip" -q install "$PKG"

read -rsp "Paste your $LABEL API key (input is hidden): " KEY; echo
KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
case "$KEY" in "$HINT"*) ;; *) echo "That doesn't look like a $LABEL key (it should start with $HINT)."; exit 1;; esac

mkdir -p "$(dirname "$KEY_FILE")"; umask 077
printf '%s\n' "$KEY" > "$KEY_FILE"; chmod 600 "$KEY_FILE"

echo "Checking the key with $LABEL (this is free)..."
if KEY="$KEY" PROVIDER="$PROVIDER" "$PY" - <<'PY'
import os
p, key = os.environ["PROVIDER"], os.environ["KEY"]
if p == "groq":
    import groq as sdk
    client = sdk.Groq(api_key=key, base_url="https://api.groq.com", max_retries=0, timeout=15)
    check = lambda: client.models.list()
else:
    import anthropic as sdk
    client = sdk.Anthropic(api_key=key, base_url="https://api.anthropic.com", max_retries=0, timeout=15)
    check = lambda: client.models.list(limit=1)
try:
    check()
    print("✓ The key works.")
except sdk.AuthenticationError:
    raise SystemExit("✗ The key was rejected. Check it and run this again.")
except sdk.APIConnectionError:
    print("(Couldn't reach the service to check it. The key is saved; try again when you're online.)")
PY
then
  echo "Saved to $KEY_FILE. Restart Rayo, then ask her something hard."
else
  rm -f "$KEY_FILE"; exit 1
fi
