#!/usr/bin/env bash
# ============================================================================
# Rayo security check: a READ-ONLY audit. Changes nothing, needs no sudo.
#   ./security/security-check.sh
# Looks at what a stranger on your Wi-Fi, or a malicious web page, could reach.
# ============================================================================
BAD=0; WARN=0
ok(){   printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33m⚠\033[0m %s\n' "$*"; WARN=$((WARN+1)); }
bad(){  printf '  \033[31m✗\033[0m %s\n' "$*"; BAD=$((BAD+1)); }
h(){    printf '\n\033[1m%s\033[0m\n' "$*"; }
HERE="$(cd "$(dirname "$0")/.." && pwd)"

h "1. Services reachable from your network (not just this PC)"
exposed="$(ss -tlnpH 2>/dev/null | awk '{print $4"|"$6}' | grep -vE '^(127\.|\[::1\]|localhost)' | awk -F'|' '{p=$1; sub(/.*:/,"",p); if(!(p in seen)){seen[p]=1; print}}' || true)"
if [ -z "$exposed" ]; then ok "no TCP service listens on a network address"; else
  while IFS='|' read -r addr proc; do
    port="${addr##*:}"; name="$(echo "$proc" | grep -o '"[^"]*"' | head -1 | tr -d '"')"
    bad "port $port is open to the network${name:+ ($name)}: anyone on your Wi-Fi can try it"
  done <<< "$exposed"; fi
udp="$(ss -ulnpH 2>/dev/null | awk '{print $5}' | grep -vE '^(127\.|\[::1\]|\[?fe80)' | grep -cvE ':(5353|3702|68|323)$' || true)"
[ "${udp:-0}" -gt 0 ] && warn "$udp UDP listener(s) on network addresses (mDNS/discovery are normal; check with: ss -ulnp)"

h "2. Firewall"
if grep -qs '^ENABLED=yes' /etc/ufw/ufw.conf; then ok "ufw firewall is enabled"
else bad "no firewall: ufw is not enabled. Fix: sudo ./security/security-harden.sh"; fi

h "3. Docker"
if command -v docker >/dev/null 2>&1 && docker ps >/dev/null 2>&1; then
  pub="$(docker ps --format '{{.Names}} {{.Ports}}' | grep -E '0\.0\.0\.0:|\[::\]:' || true)"
  if [ -z "$pub" ]; then ok "no container publishes a port to the network"; else
    while read -r line; do bad "container publishes to the network (and Docker bypasses the firewall): $line"; done <<< "$pub"
    echo "      Fix: publish as 127.0.0.1:PORT:PORT in its compose file, or stop it when unused."; fi
  id -nG | tr ' ' '\n' | grep -qx docker && warn "your account is in the 'docker' group, which is root-equivalent: a hijacked app running as you owns the PC"
else ok "docker not in use"; fi

h "4. Rayo itself"
ss -tlnH 2>/dev/null | awk '{print $4}' | grep -qE '^127\.0\.0\.1:8791$' && ok "HUD server (8791) listens on this PC only" || warn "HUD server not running (start it with ./start.sh)"
if curl -s -m 3 -o /dev/null -w '%{http_code}' -H 'Host: evil.example' http://127.0.0.1:8791/index.html 2>/dev/null | grep -q 421; then ok "HUD server rejects foreign Host headers (DNS-rebinding blocked)"
elif ss -tlnH 2>/dev/null | grep -q ':8791'; then bad "HUD server accepts foreign Host headers. Restart Rayo: ./stop.sh && ./start.sh"; fi
ss -tlnH 2>/dev/null | awk '{print $4}' | grep -qE '^127\.0\.0\.1:11434$' && ok "Ollama listens on this PC only" || { ss -tlnH 2>/dev/null | grep -q ':11434' && bad "Ollama is exposed to the network: set OLLAMA_HOST=127.0.0.1"; }
for f in "$HOME/.config/rayo" "$HOME/Documents/Rayo"; do
  [ -e "$f" ] && { m="$(stat -c %a "$f")"; [ "$m" = 700 ] && ok "$f is private (700)" || warn "$f is $m: run chmod 700 \"$f\""; }; done
for k in "$HOME"/.config/rayo/*.key; do [ -e "$k" ] || continue; m="$(stat -c %a "$k")"; [ "$m" = 600 ] && ok "$(basename "$k") is private (600)" || bad "$(basename "$k") is $m: run chmod 600 \"$k\""; done
if git -C "$HERE" rev-parse >/dev/null 2>&1; then
  PAT='sk-ant-[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9]{30,}|sk_live_[A-Za-z0-9]{10,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}'
  hits="$(for c in $(git -C "$HERE" rev-list --all); do git -C "$HERE" grep -I -l -E "$PAT" "$c" 2>/dev/null; done | sort -u | head -3)"
  [ -z "$hits" ] && ok "no API keys or private keys in the repo or its history" || bad "possible secret committed: $hits"; fi

h "5. This laptop"
lsblk -o TYPE 2>/dev/null | grep -qi crypt && ok "disk is encrypted" || warn "disk is NOT encrypted: anyone holding the laptop can read it (needs a reinstall to fix; use a strong login password and keep it locked)"
n="$(apt list --upgradable 2>/dev/null | grep -vc '^Listing')"; [ "$n" -eq 0 ] && ok "all packages up to date" || warn "$n package update(s) waiting: sudo apt update && sudo apt upgrade"
systemctl is-active --quiet unattended-upgrades 2>/dev/null && ok "automatic security updates are on" || warn "automatic security updates are off"
systemctl is-active --quiet ssh 2>/dev/null && warn "an SSH server is running: disable it if you don't use it (sudo systemctl disable --now ssh)" || ok "no SSH server running"
lock="$(gsettings get org.gnome.desktop.screensaver lock-enabled 2>/dev/null)"; [ "$lock" = true ] && ok "screen locks when idle" || warn "screen lock is off (Settings > Privacy > Screen Lock)"

printf '\n\033[1mResult:\033[0m %s problem(s), %s warning(s)\n' "$BAD" "$WARN"
exit $([ "$BAD" -eq 0 ] && echo 0 || echo 1)
