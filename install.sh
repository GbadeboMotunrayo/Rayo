#!/usr/bin/env bash
# ============================================================================
# Rayo installer.  Clone-and-run, or one line:
#   curl -fsSL https://raw.githubusercontent.com/GbadeboMotunrayo/Rayo/main/install.sh | bash
#
# What it does (no sudo, all in your home dir):
#   1. puts Rayo in ~/.local/share/rayo (or uses the clone you ran it from)
#   2. mounts the live overlay on your desktop
#   3. offers to start it automatically at every login
# Uninstall any time:  ~/.local/share/rayo/uninstall.sh   (or see the README)
# ============================================================================
set -euo pipefail

REPO="https://github.com/GbadeboMotunrayo/Rayo.git"
DEST="${RAYO_DIR:-$HOME/.local/share/rayo}"

say()  { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '  \033[1;33m! %s\033[0m\n' "$*"; }

# --- 1. locate or fetch the code --------------------------------------------
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && [ -f "$HERE/overlay/rayo-overlay.py" ]; then
  DEST="$HERE"                       # run from an existing clone
  say "Using this clone: $DEST"
else
  if ! command -v git >/dev/null; then
    echo "git is required. Install git and re-run." >&2; exit 1
  fi
  if [ -d "$DEST/.git" ]; then
    say "Updating existing install at $DEST"; git -C "$DEST" pull --ff-only || warn "pull failed, continuing"
  else
    say "Cloning Rayo into $DEST"; mkdir -p "$(dirname "$DEST")"; git clone --depth 1 "$REPO" "$DEST"
  fi
fi
ok "code ready"

# --- 2. dependency sanity ----------------------------------------------------
say "Checking dependencies"
command -v python3 >/dev/null && ok "python3" || warn "python3 not found (required to run the overlay)"
python3 -c "import gi; gi.require_version('WebKit2','4.1')" 2>/dev/null \
  && ok "WebKitGTK 4.1" \
  || warn "WebKitGTK 4.1 not found. On Debian/Ubuntu: sudo apt install gir1.2-webkit2-4.1 python3-gi"

# --- 3. autostart (optional) -------------------------------------------------
AUTOSTART="$HOME/.config/autostart/rayo.desktop"
say "Start Rayo automatically at login?"
printf "  [Y/n] "; read -r ans </dev/tty || ans="y"
if [[ "${ans:-y}" =~ ^[Yy]?$ ]]; then
  mkdir -p "$HOME/.config/autostart"
  cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Rayo HUD
Comment=Animated comic-hero desktop HUD
Exec=$DEST/start.sh
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=12
Terminal=false
EOF
  ok "autostart enabled ($AUTOSTART)"
else
  warn "skipped autostart (start it any time with $DEST/start.sh)"
fi

# --- 4. uninstaller ----------------------------------------------------------
cat > "$DEST/uninstall.sh" <<EOF
#!/usr/bin/env bash
"$DEST/stop.sh" 2>/dev/null || true
rm -f "$HOME/.config/autostart/rayo.desktop"
echo "Rayo stopped and removed from autostart. Delete $DEST to remove the files."
EOF
chmod +x "$DEST/uninstall.sh"

# --- 5. go -------------------------------------------------------------------
say "Starting Rayo"
"$DEST/start.sh" || warn "could not start now — run $DEST/start.sh yourself"

cat <<EOF

  Rayo is installed.  Click the reactor hub for the menu.
  Themes:   click the hub → THEME  (or set hud/user.json)
  Stop:     $DEST/stop.sh
  Uninstall:$DEST/uninstall.sh
EOF
