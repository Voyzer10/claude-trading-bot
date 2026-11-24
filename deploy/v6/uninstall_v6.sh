#!/usr/bin/env bash
# Roll V6 back off the VPS. Stops/disables the V6 units and removes the V6 code. V6 DATA (/var/lib/trader-v6) and the
# V6 credential (/etc/trader-v6) are KEPT unless --purge-data is given (books with trades are never deleted silently).
# Never touches /opt/trader, /etc/trader or any V4 service.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
for s in trader-v6-runner trader-v6-api; do
  systemctl stop "$s" 2>/dev/null || true
  systemctl disable "$s" 2>/dev/null || true
  rm -f "/etc/systemd/system/$s.service"
done
systemctl daemon-reload
rm -rf /opt/trader-v6
if [ "${1:-}" = "--purge-data" ]; then
  echo "Purging /var/lib/trader-v6 (owner asked for it)"; rm -rf /var/lib/trader-v6
else
  echo "Kept /var/lib/trader-v6 and /etc/trader-v6."
fi
