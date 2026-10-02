#!/usr/bin/env bash
# ============================================================================
# Rayo hardening: the steps that need your password. Safe to run more than once.
#   sudo ./security/security-harden.sh              firewall on (deny all incoming)
#   sudo ./security/security-harden.sh --upgrade    also install pending updates
#   sudo ./security/security-harden.sh --no-printer-discovery   also stop cups-browsed
# After it runs: ./security/security-check.sh
# ============================================================================
set -euo pipefail
[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"
step(){ printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

step "Firewall: deny everything incoming, allow everything outgoing"
command -v ufw >/dev/null || apt-get install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
ufw status verbose | head -8

for arg in "$@"; do case "$arg" in
  --upgrade)
    step "Installing pending updates"; apt-get update -qq; apt-get -y upgrade;;
  --no-printer-discovery)
    step "Stopping network printer auto-discovery (cups-browsed)"
    systemctl disable --now cups-browsed 2>/dev/null || true
    snap stop --disable cups.cups-browsed 2>/dev/null || true;;
esac; done

cat <<'EOF'

✓ Done. What this does NOT cover (see SECURITY.md):
  • Docker published ports bypass this firewall. Publish as 127.0.0.1:PORT:PORT, or stop the container.
  • Gitea (port 3000) is now blocked from the network by the firewall; to reach it from another device,
    use a VPN such as Tailscale/WireGuard rather than opening the port.
  • Disk encryption needs a reinstall. Until then, keep a strong login password and lock the screen.
Run ./security/security-check.sh to see where you stand.
EOF
