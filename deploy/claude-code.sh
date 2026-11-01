#!/usr/bin/env bash
# Claude Code on the VPS, driven from your phone or claude.ai/code with Remote Control.
#
#   sudo bash deploy/claude-code.sh            # 1. install: user, Claude Code, tmux, permissions
#   sudo bash deploy/claude-code.sh login      # 2. sign in with your claude.ai account (once, interactive)
#   sudo bash deploy/claude-code.sh start      # 3. start Remote Control (also after every reboot, by itself)
#   sudo bash deploy/claude-code.sh status     #    is it running? which URL?
#   sudo bash deploy/claude-code.sh attach     #    look at the Remote Control terminal (leave: Ctrl+B then D)
#   sudo bash deploy/claude-code.sh stop       #    stop Remote Control
#
# Needs a Pro, Max, Team or Enterprise plan (Remote Control does not work with an API key).
#
# Safety: Claude runs as its own user "claudeops", NOT root. It can read the bot (/opt/trader: code, logs,
# paper ledger) and the service journals, and may restart the three trader services through a narrow sudo
# rule. It cannot read /etc/trader/trader.env (the dashboard password), cannot change the bot's files, and
# cannot run anything else as root. Code changes go through GitHub (branch -> CI -> deploy), never on the VPS.
set -euo pipefail

U=claudeops
H=/home/$U
APP=/opt/trader
UNIT=claude-remote-control
SUDOERS=/etc/sudoers.d/claudeops-trader
CMD="${1:-install}"

[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
as_u() { sudo -iu "$U" bash -lc "$*"; }
CLAUDE="$H/.local/bin/claude"

install() {
  say "Packages (curl, tmux, git)"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq curl tmux git ca-certificates sudo >/dev/null

  say "User $U (not root)"
  id "$U" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$U"
  # read the trader services' logs with journalctl, nothing more
  getent group systemd-journal >/dev/null && usermod -aG systemd-journal "$U"

  say "Narrow sudo rule: restart or check the trader services only"
  cat > "$SUDOERS.tmp" <<EOF
# Claude Code (user $U) may restart / check the trader bot services and nothing else as root.
$U ALL=(root) NOPASSWD: /usr/bin/systemctl restart trader-runner, /usr/bin/systemctl restart trader-api, /usr/bin/systemctl restart trader-web, /usr/bin/systemctl restart trader-runner trader-api trader-web, /usr/bin/systemctl status trader-runner, /usr/bin/systemctl status trader-api, /usr/bin/systemctl status trader-web
EOF
  chmod 440 "$SUDOERS.tmp"
  if visudo -cf "$SUDOERS.tmp" >/dev/null; then mv "$SUDOERS.tmp" "$SUDOERS"; else rm -f "$SUDOERS.tmp"; echo "sudoers check failed"; exit 1; fi

  say "Claude Code (official installer, as $U)"
  if [ -x "$CLAUDE" ]; then
    as_u "$CLAUDE --version" || true
    echo "already installed (it updates itself)"
  else
    as_u "curl -fsSL https://claude.ai/install.sh | bash"
  fi
  # shellcheck disable=SC2016  # $HOME must expand at login, not now
  grep -q '.local/bin' "$H/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$H/.bashrc"

  say "Project folder"
  if [ -d "$APP" ]; then
    echo "$APP is readable by $U: $(sudo -u "$U" test -r "$APP/live.py" && echo yes || echo NO)"
  else
    echo "$APP not found: run deploy/install.sh first (the bot)."
  fi

  say "Remote Control service (runs Claude in tmux so it survives SSH logout and reboots)"
  cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=Claude Code Remote Control (user $U, folder $APP)
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=$U
WorkingDirectory=$APP
Environment=PATH=$H/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/tmux new-session -d -s rc -x 200 -y 50 "$CLAUDE remote-control"
ExecStop=/usr/bin/tmux kill-session -t rc
RemainAfterExit=yes
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload

  say "Done. Next:"
  echo "  sudo bash $0 login    # sign in once with your claude.ai account"
  echo "  sudo bash $0 start    # start Remote Control"
}

login() {
  [ -x "$CLAUDE" ] || { echo "Run: sudo bash $0   (install first)"; exit 1; }
  [ -t 0 ] || { echo "login is interactive: run it in an SSH terminal"; exit 1; }
  cat <<EOF

Claude Code opens now, as user $U, in $APP.
  1. If it asks to trust the folder: yes.
  2. Type   /login   and pick your claude.ai account (Pro/Max/Team/Enterprise).
     It prints a link: open it on your PC or phone, sign in, paste the code back here.
  3. Type   /exit

EOF
  read -r -p "Press Enter to continue..." _
  sudo -iu "$U" bash -lc "cd '$APP' && '$CLAUDE'"
  say "Accept Remote Control once (it asks 'Enable Remote Control? (y/n)')"
  echo "When it shows the session URL, press Ctrl+C: the service will run it from now on."
  read -r -p "Press Enter to continue..." _
  sudo -iu "$U" bash -lc "cd '$APP' && '$CLAUDE' remote-control" || true
  echo
  echo "Now: sudo bash $0 start"
}

start() {
  systemctl enable "$UNIT" >/dev/null 2>&1
  systemctl restart "$UNIT"
  sleep 6
  status
}

status() {
  printf '%-22s %s\n' "$UNIT" "$(systemctl is-active "$UNIT" 2>/dev/null || true)"
  if sudo -u "$U" tmux has-session -t rc 2>/dev/null; then
    echo "--- last lines of the Remote Control terminal ---"
    sudo -u "$U" tmux capture-pane -p -t rc | grep -v '^[[:space:]]*$' | tail -n 15
    echo "-------------------------------------------------"
    echo "Open the Claude app (Code) or https://claude.ai/code and pick the session named after this server."
  else
    echo "Not running. Start it: sudo bash $0 start   (signed in? sudo bash $0 login)"
  fi
}

attach() { echo "Leave with Ctrl+B then D (do not press Ctrl+C: that stops it)."; sleep 2; sudo -u "$U" tmux attach -t rc; }
stop() { systemctl stop "$UNIT"; systemctl disable "$UNIT" >/dev/null 2>&1; echo "stopped"; }

case "$CMD" in
  install) install ;;
  login) login ;;
  start) start ;;
  status) status ;;
  attach) attach ;;
  stop) stop ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
