#!/usr/bin/env bash
# Move your paper account, rules and logs from the PC to the VPS (do this once, with the PC runner STOPPED).
#   On the PC (PowerShell):  scp -r D:\trader\trader  <user>@<vps-ip>:/tmp/trader-data
#   On the VPS:              sudo bash /opt/trader/deploy/import_data.sh /tmp/trader-data
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
FROM="${1:?usage: import_data.sh /tmp/trader-data}"
[ -f "$FROM/paper/ledger.json" ] || [ -d "$FROM/live" ] || { echo "$FROM does not look like D:\\trader\\trader"; exit 1; }
APP=/opt/trader
systemctl stop trader-runner
if [ -d "$APP/trader" ]; then cp -a "$APP/trader" "$APP/trader.before-import.$(date +%Y%m%d-%H%M%S)"; fi
mkdir -p "$APP/trader"
rsync -a --exclude 'dashboard_password.txt' --exclude 'research/jobs' "$FROM/" "$APP/trader/"
rm -f "$APP/trader/live/commands.jsonl"
chown -R trader:trader "$APP/trader"
systemctl start trader-runner
echo "Imported. The runner continues from the PC's ledger. Keep the PC runner OFF from now on (one ledger, one runner)."
