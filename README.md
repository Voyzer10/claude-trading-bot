# Trader bot: runner + dashboard (one repo)

**Current phase: paper trading (testing).** Every trade is virtual (paper.py) and nothing is sent to a broker yet.
After the testing phase the plan is to connect real brokers and trade real money; that step adds a broker
integration plus hard safety limits (see "Before real money" below).

```
D:\trader                       (this repo)
├── app/, components/, lib/     Next.js dashboard (frontend)
├── api/index.py                FastAPI: the dashboard API (and a cloud runner, parked for later)
├── *.py                        the bot: live.py (runner), paper.py, scan_crypto.py, auto_crypto.py, ...
├── start_all.bat               starts the runner
├── start_dashboard.bat         starts the dashboard (http://localhost:3000)
├── cloud_seed.py, vercel.json  for the optional cloud setup later
└── trader/                     the bot's data (ledger, logs, control.json): NOT in git
```

## Run it on your PC (current setup)

Two windows, both from `D:\trader`:

1. **`start_all.bat`**: the runner. Scans NSE, F&O, crypto and US, takes paper trades and checks stops and
   targets every 5 minutes. After every cycle it writes `trader\live\dashboard_snapshot.json`.
2. **`start_dashboard.bat`**: the dashboard at http://localhost:3000, and on your phone on the same WiFi at
   `http://<PC's IP>:3000` (the window prints the address). First run: installs the packages (needs Node.js LTS
   and Python) and asks for a password, saved in `trader\dashboard_password.txt`; login is any username + that
   password. The Python API listens on 127.0.0.1:8000 only; the phone reaches it through Next.js.
   Away from home: install Tailscale on the PC and the phone and open `http://<PC's Tailscale IP>:3000`.

The **Automation control** switches on the dashboard write `trader\live\control.json`. The runner reads it
before every cycle, so a switch takes effect within ~5 minutes, without restarting. "Pause everything" stops
new trades in every market; open paper positions are still watched (stops and targets keep working).
A market only runs if `start_all.bat` started it.

The runner only works while the PC is on and awake: set Windows sleep to "Never" while testing.

Development without the .bat: `npm install`, `pip install fastapi uvicorn`, `npm run dev`.

## Run it on a VPS (24x7, PC can be off)

Ubuntu 22.04/24.04 or Debian 12/13, 2 vCPU / 4 GB is plenty. Copy this folder to the VPS (or push it to a private GitHub repo
and `git clone` it there), then from that folder:

```
sudo bash deploy/install.sh --tailscale        # recommended: dashboard only on your Tailscale network
sudo bash deploy/install.sh --domain t.you.com # or HTTPS on your own domain (A record -> VPS IP first)
sudo bash deploy/install.sh                    # or plain http://<IP>:3000 with a password (not encrypted)
```

It installs Python, Node 20, a 2 GB swap file, builds the dashboard, and runs three systemd services as the
user `trader`: `trader-runner` (live.py), `trader-api` (FastAPI, 127.0.0.1 only) and `trader-web` (Next.js).
It ends with a market-data check (Yahoo blocks some datacenters) and prints the dashboard address and password.
Settings: `/etc/trader/trader.env` (password, markets). Data: `/opt/trader/trader`.

- Move the PC's paper account once (PC runner stopped): `scp -r D:\trader\trader user@VPS:/tmp/trader-data`,
  then `sudo bash /opt/trader/deploy/import_data.sh /tmp/trader-data`. Then keep the PC runner off.
- Update after code changes: `sudo bash deploy/update.sh` from the new copy.
- Logs: `journalctl -u trader-runner -f`. The dashboard's Operations section shows the same health.

## Claude Code on the VPS (Remote Control)

Run Claude Code on the VPS and drive it from the Claude app or claude.ai/code (needs a Pro/Max/Team/Enterprise
plan). It runs as its own user `claudeops`: it can read the bot and its logs and restart the three services,
nothing else as root, and it cannot read `/etc/trader/trader.env`.

```
cd ~/claude-trading-bot && git pull
sudo bash deploy/claude-code.sh          # install
sudo bash deploy/claude-code.sh login    # sign in once (prints a link to open on your phone/PC)
sudo bash deploy/claude-code.sh start    # Remote Control, restarts by itself after a reboot
sudo bash deploy/claude-code.sh status   # running? last lines of its terminal
```
Or without SSH for the non-interactive steps: GitHub -> Actions -> **Claude Code on VPS** -> Run workflow ->
`install` -> `login-begin` -> `keys` (repeat: answer what the screen in the log asks; the sign-in link shows
up there, open it on your phone and send back the code) -> `start`. `screen` shows the terminal again.
`CLAUDE.md` tells that session where everything is and the rules (no edits on the VPS; changes go through GitHub).

## CI / CD (GitHub Actions)

- **CI** (`.github/workflows/ci.yml`) runs on every push and pull request: the dashboard build (lint and type
  checks), a compile check of every Python file plus an API smoke test (`tests/smoke_api.py`, no network), and
  shellcheck on `deploy/*.sh`.
- **Deploy** (`.github/workflows/deploy.yml`) runs after CI passes on `main`: it SSHes into the VPS, pulls `main`
  and runs `deploy/update.sh`, then checks the three services. It needs repository secrets `VPS_HOST`,
  `VPS_USER` and `VPS_SSH_KEY` (a separate key for GitHub; its public half goes into the VPS user's
  `~/.ssh/authorized_keys`), optionally `VPS_KNOWN_HOSTS` and `VPS_REPO_DIR`. Without them it skips.
  It can also be run by hand from the Actions tab.

## What the dashboard controls

- **Performance**: P&L in rupees vs the daily goal, per account, daily bars.
- **Automation control**: markets on/off, pause everything.
- **Positions**: close one position or all, at the market price (the runner does it within ~5 s).
- **Settings**: crypto strategy rules (with the backtested defaults and a reset), risk limits per account,
  coins watched, goal and US$ rate. Every change is written to the runner log as "Dashboard: ...".
- **Operations**: scan now, restart the runner, CPU / memory / disk, market-data check, downloads
  (trades CSV, ledger, log, decisions, settings).
- **Backtest**: runs research.py on the machine with fresh data and shows the report.
- **Alerts**: Telegram messages for trades, errors, runner restarts and a daily summary.

## Later: cloud (optional, not set up)

The repo can also deploy to Vercel (Next.js + `api/index.py`) with Upstash Redis and an outside scheduler
calling `/api/py/cron/tick` every 5 minutes, so the PC can be off. Only crypto fits a 60-second cloud tick.
That path is parked for now; `vercel.json`, `cloud_seed.py` and `github-workflow-tick.yml` are kept for it.
In the cloud the API switches to Redis automatically (it runs in local mode only when no Redis is configured
and it is not on Vercel).

## Before real money

Going live is planned after testing. It needs, at minimum:
- enough paper results to judge: 30+ trades and at least a month that ends in profit, close to the backtest;
- a broker/exchange API integration (order placement, fills, cancels) behind the same risk checks paper.py uses;
- hard limits enforced in code: max loss per trade, daily loss limit, max open positions, a kill switch
  (the dashboard's "Pause everything"), and alerts when anything fails. While paper testing the account limits are
  OFF (paper config `risk_limits: false`, the owner's decision of 4 Nov 2026): turn `risk_limits` ON for every
  account (Settings > Risk limits) before any real money;
- starting with a small amount, and tax handled (crypto in India: 30% on gains, 1% TDS on sells; check with a CA).

## Known limits

- Yahoo Finance data is free and unofficial: it can lag or refuse requests; crypto falls back to Coinbase.
- PC asleep or runner window closed = no scans and no stop checks. Open paper positions are checked again on
  the next cycle after it restarts.
