#!/usr/bin/env bash
# Install the V6 PAPER-ONLY runtime next to V4 WITHOUT touching V4 and WITHOUT starting anything.
#   sudo bash deploy/v6/install_v6.sh            (run from a checkout of the approved commit)
# What it does:
#   - creates system user trader-v6 (no login shell, no home)
#   - copies ONLY scanner_v6/, v6_runtime/, api_v6/ to /opt/trader-v6/app (separate from /opt/trader)
#   - creates /opt/trader-v6/venv with fastapi + uvicorn
#   - creates /var/lib/trader-v6 (0750 trader-v6) and /etc/trader-v6 (0750 root:trader-v6), both empty
#   - installs the two unit files and runs daemon-reload
# What it never does: enable or start a service, create a book, write a credential, write runtime/ENABLED_*,
# read /etc/trader, or modify /opt/trader or any V4 unit.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
APP="${V6_APP_DIR:-/opt/trader-v6}"   # override only for the offline install test
id trader-v6 >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin trader-v6
install -d -m 0755 -o root -g root "$APP" "$APP/app"
for d in scanner_v6 v6_runtime api_v6; do
  rsync -a --delete --exclude '__pycache__' "$SRC/$d/" "$APP/app/$d/"
done
chown -R root:root "$APP/app" && chmod -R go-w "$APP/app"
[ -x "$APP/venv/bin/python" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q "fastapi==0.115.6" "uvicorn==0.32.1"
install -d -m 0750 -o trader-v6 -g trader-v6 /var/lib/trader-v6
install -d -m 0750 -o root -g trader-v6 /etc/trader-v6
install -m 0644 "$SRC/deploy/v6/trader-v6-api.service" "$SRC/deploy/v6/trader-v6-runner.service" /etc/systemd/system/
systemctl daemon-reload
for s in trader-v6-api trader-v6-runner; do
  printf '  %-18s enabled=%s active=%s\n' "$s" "$(systemctl is-enabled $s 2>/dev/null || true)" "$(systemctl is-active $s 2>/dev/null || true)"
done
echo "Installed. Nothing was enabled or started. See deploy/v6/README.md for the owner-only activation steps."
