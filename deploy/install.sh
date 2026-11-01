#!/usr/bin/env bash
# Trader bot: one-command install on a fresh Ubuntu 22.04 / 24.04 or Debian 12 / 13 VPS.
#
#   sudo bash deploy/install.sh                          # dashboard on http://<VPS-IP>:3000 (password, plain HTTP)
#   sudo bash deploy/install.sh --tailscale              # dashboard only inside your Tailscale network (recommended)
#   sudo bash deploy/install.sh --domain trader.you.com  # HTTPS with Caddy (point the domain's A record here first)
#
# Run it from the repo folder (git clone or a copy of D:\trader). Safe to run again: it updates in place.
# It installs to /opt/trader, runs everything as the user "trader" with three systemd services
# (trader-runner, trader-api, trader-web), and keeps your data in /opt/trader/trader.
set -euo pipefail

MODE=open
DOMAIN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tailscale) MODE=tailscale ;;
    --domain) MODE=domain; DOMAIN="${2:?--domain needs a name}"; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
  shift
done

[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/trader
ENVF=/etc/trader/trader.env
say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

say "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl rsync ca-certificates ufw >/dev/null

if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  say "Node.js 20"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
  apt-get install -y -qq nodejs >/dev/null
fi
node -v

say "Swap (so the Next.js build does not run out of memory on small plans)"
if [ "$(swapon --show | wc -l)" -eq 0 ] && [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "2 GB swap added"
else
  echo "swap already present"
fi

say "User and files ($APP)"
id trader >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/trader --shell /usr/sbin/nologin trader
mkdir -p "$APP"
if [ "$SRC" != "$APP" ]; then
  rsync -a --delete \
    --exclude node_modules --exclude .next --exclude .venv --exclude trader/ --exclude us/trader/ \
    --exclude '__pycache__' --exclude '*.bat' "$SRC/" "$APP/"
fi
mkdir -p "$APP/trader/live" "$APP/trader/paper"
chown -R trader:trader "$APP"

say "Python packages"
sudo -u trader python3 -m venv "$APP/.venv"
sudo -u trader "$APP/.venv/bin/pip" install -q --upgrade pip
sudo -u trader "$APP/.venv/bin/pip" install -q -r "$APP/deploy/requirements.txt"

say "Dashboard build (1-3 minutes)"
cd "$APP"
sudo -u trader npm ci --no-audit --no-fund --loglevel=error
sudo -u trader env NEXT_TELEMETRY_DISABLED=1 npm run build

say "Settings ($ENVF)"
mkdir -p /etc/trader
if [ ! -f "$ENVF" ]; then
  PW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
  cat > "$ENVF" <<EOF
# Trader bot settings. After editing: sudo systemctl restart trader-runner trader-api trader-web
DASHBOARD_PASSWORD=$PW
TRADER_SERVICE=1
RUNNER_MARKETS=NSE,FNO,CRYPTO,US
WEB_HOST=0.0.0.0
TZ=Asia/Kolkata
EOF
  NEW_PW=1
fi
case "$MODE" in
  domain) sed -i 's/^WEB_HOST=.*/WEB_HOST=127.0.0.1/' "$ENVF" ;;
  *) sed -i 's/^WEB_HOST=.*/WEB_HOST=0.0.0.0/' "$ENVF" ;;
esac
chown root:trader "$ENVF"
chmod 640 "$ENVF"

say "Services"
cp "$APP"/deploy/trader-{runner,api,web}.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now trader-api trader-web trader-runner >/dev/null 2>&1
systemctl restart trader-api trader-web trader-runner

say "Firewall"
# keep SSH open on whatever port sshd really listens on, before the firewall is switched on
SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"
SSH_PORT="${SSH_PORT:-22}"
ufw allow "$SSH_PORT"/tcp >/dev/null
echo "SSH stays open on port $SSH_PORT"
case "$MODE" in
  open) ufw allow 3000/tcp >/dev/null ;;
  tailscale) ufw delete allow 3000/tcp >/dev/null 2>&1 || true ;;
  domain) ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw delete allow 3000/tcp >/dev/null 2>&1 || true ;;
esac

if [ "$MODE" = tailscale ]; then
  say "Tailscale"
  command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
  ufw allow in on tailscale0 >/dev/null
  tailscale status >/dev/null 2>&1 || tailscale up
fi

if [ "$MODE" = domain ]; then
  say "Caddy (HTTPS for $DOMAIN)"
  if ! command -v caddy >/dev/null; then
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https >/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy >/dev/null
  fi
  printf '%s {\n\treverse_proxy 127.0.0.1:3000\n}\n' "$DOMAIN" > /etc/caddy/Caddyfile
  systemctl reload caddy || systemctl restart caddy
fi
ufw --force enable >/dev/null

say "Market data check (can this VPS reach Yahoo and Coinbase?)"
sudo -u trader "$APP/.venv/bin/python" "$APP/deploy/check_data.py" || true

sleep 3
say "Status"
for s in trader-runner trader-api trader-web; do printf '  %-14s %s\n' "$s" "$(systemctl is-active $s)"; done
IP="$(curl -fsS https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
echo
case "$MODE" in
  open) echo "  Dashboard: http://$IP:3000   (plain HTTP: use --tailscale or --domain for anything serious)" ;;
  tailscale) echo "  Dashboard: http://$(tailscale ip -4 2>/dev/null | head -1):3000  (from devices on your Tailscale)" ;;
  domain) echo "  Dashboard: https://$DOMAIN" ;;
esac
echo "  Login: any username + password: $(grep '^DASHBOARD_PASSWORD=' "$ENVF" | cut -d= -f2-)"
if [ "${NEW_PW:-0}" = 1 ]; then echo "  (generated now; change it in $ENVF, then restart trader-web)"; fi
echo "  Logs: journalctl -u trader-runner -f      Update later: sudo bash $APP/deploy/update.sh"
