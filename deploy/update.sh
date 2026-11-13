#!/usr/bin/env bash
# Update the bot on the VPS after you changed the code.
#   From a git clone:   cd ~/trader && git pull && sudo bash deploy/update.sh
#   From a copied folder: copy the new files to the VPS, then run this from that folder.
# Your data (/opt/trader/trader) and settings (/etc/trader/trader.env) are kept.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/trader
if [ "$SRC" != "$APP" ]; then
  rsync -a --delete --exclude node_modules --exclude .next --exclude .venv --exclude trader/ --exclude us/trader/ \
    --exclude '__pycache__' "$SRC/" "$APP/"
fi
chown -R trader:trader "$APP"
cd "$APP"
sudo -u trader "$APP/.venv/bin/pip" install -q -r deploy/requirements.txt
sudo -u trader npm ci --no-audit --no-fund --loglevel=error
sudo -u trader env NEXT_TELEMETRY_DISABLED=1 npm run build
# the dashboard moved from port 3000 to 8080 (owner, 13 Nov 2026): carry the firewall and Caddy over (no-op later)
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -qE '^3000/tcp +ALLOW'; then
  ufw allow 8080/tcp >/dev/null
  ufw delete allow 3000/tcp >/dev/null || true
  echo "  firewall: 8080 opened, 3000 closed"
fi
if [ -f /etc/caddy/Caddyfile ] && grep -q '127\.0\.0\.1:3000' /etc/caddy/Caddyfile; then
  sed -i 's/127\.0\.0\.1:3000/127.0.0.1:8080/' /etc/caddy/Caddyfile
  systemctl reload caddy || systemctl restart caddy || true
  echo "  caddy: now proxies to 127.0.0.1:8080"
fi
cp deploy/trader-{runner,api,web,ticker,crypto-ticker,us-ticker,pov}.service /etc/systemd/system/ && systemctl daemon-reload
systemctl enable trader-ticker trader-crypto-ticker trader-us-ticker trader-pov >/dev/null 2>&1 || true
systemctl restart trader-api trader-web trader-runner trader-ticker trader-crypto-ticker trader-us-ticker trader-pov
sleep 3
for s in trader-runner trader-api trader-web trader-ticker trader-crypto-ticker trader-us-ticker trader-pov; do printf '  %-21s %s\n' "$s" "$(systemctl is-active $s)"; done
if command -v ss >/dev/null; then
  printf '  %-21s %s\n' "port 8080 (dashboard)" "$(ss -ltn 'sport = :8080' | grep -q LISTEN && echo listening || echo 'NOT listening')"
  printf '  %-21s %s\n' "port 3000" "$(ss -ltn 'sport = :3000' | grep -q LISTEN && echo 'IN USE (should be free)' || echo free)"
fi
