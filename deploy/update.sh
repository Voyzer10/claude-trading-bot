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
    --exclude '__pycache__' --exclude '*.bat' "$SRC/" "$APP/"
fi
chown -R trader:trader "$APP"
cd "$APP"
sudo -u trader "$APP/.venv/bin/pip" install -q -r deploy/requirements.txt
sudo -u trader npm ci --no-audit --no-fund --loglevel=error
sudo -u trader env NEXT_TELEMETRY_DISABLED=1 npm run build
cp deploy/trader-{runner,api,web,ticker,crypto-ticker}.service /etc/systemd/system/ && systemctl daemon-reload
systemctl enable trader-ticker trader-crypto-ticker >/dev/null 2>&1 || true
systemctl restart trader-api trader-web trader-runner trader-ticker trader-crypto-ticker
sleep 3
for s in trader-runner trader-api trader-web trader-ticker trader-crypto-ticker; do printf '  %-21s %s\n' "$s" "$(systemctl is-active $s)"; done
