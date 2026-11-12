# Trader bot: runner + dashboard (one repo)

**Current phase: paper trading (testing).** Every trade is virtual (paper.py) and nothing is sent to a broker yet.
After the testing phase the plan is to connect real brokers and trade real money; that step adds a broker
integration plus hard safety limits (see "Before real money" below).

```
claude-trading-bot              (this repo; on the VPS: /opt/trader)
├── app/, components/, lib/     Next.js dashboard (frontend)
├── api/                        FastAPI: the dashboard API (index.py, _ops.py, _kite.py)
├── *.py                        the bot: live.py (runner), paper.py, scanners, auto_* agents, research*.py, tickers
├── us/                         the US agents' helper scripts (scanner, entry, exit, budget, risk, ...)
├── deploy/                     VPS install / update scripts and the systemd services
├── tests/                      offline tests (run in CI)
└── trader/                     the bot's data (ledger, logs, control.json): NOT in git
```

The bot runs 24x7 on the VPS (below). For development on a PC: `npm install`, `pip install -r requirements.txt`,
then `python live.py` (runner) and `npm run dev` (dashboard at http://localhost:3000, API on 127.0.0.1:8000).

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

## Claude Code on the VPS

Claude Code runs on the VPS as its own user `claudeops` (Remote Control service, set up once). It can read the
bot and its logs and restart the services, nothing else as root, and it cannot read `/etc/trader/trader.env`.
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
- **Scanner version**: Settings > Risk limits > "Scanner version", per account (CRYPTO, INDIA, FNO, US). Versions
  never mix. `v4` (`scanner_v4.py`, the owner's rules): BOS = a close beyond the last swing high / low; then a
  close below an old low (above an old high), a signal candle (doji / gravestone / long-legged doji / inverted
  hammer to buy; doji / dragonfly / long-legged doji / hammer to sell), then the next 1-2 candles close past it;
  target the next liquidity, trailing +1R -> entry, +2R -> +1R; after that trade closed, one OB / FVG secondary.
  Only yesterday's unswept BOS setups carry into today (NSE / US: the session; crypto: the day from 00:00 UTC). `v5`, `v3`, `v2` and `rules`
  are the older versions. The broker skips a setup of another version. Backtest first: Backtest > "Scanner v4 ...".
- **Accounts**: INDIA (NSE stocks, Rs 50,000), FNO (Nifty 50 / Bank Nifty options, Rs 1,00,000), US ($50,000),
  CRYPTO ($1,000). All paper money.
- **Bigger picture (POV)**: chips 1h / 4h / D / W / M next to each chart: the direction of the last complete v4
  setup on that timeframe (`pov.py`, hourly). Display only.
- **Trade Manager** (Settings > Risk limits, per account; on by default): every open paper trade with a fixed
  target is managed: stop to the entry at +1R, half the move locked once 80% of the way to the target is covered,
  out on a reversal candle near the high (5-minute candles; 15 for crypto) after +1R, out when a trade goes nowhere
  (60 min; crypto 4h). The crypto trailing exits are left alone. Each trade records mfe_r / mae_r. Backtest:
  Backtest > "Trade Manager US / NSE / crypto" (also the US playbook backtest).
- **Why a trade was taken**: every paper position records its setup, the scanner that found it, the liquidity it
  swept (or the zone it retested) and the entry reason; Positions shows them and the downloads include them.
- **Operations**: scan now, restart the runner, CPU / memory / disk, market-data check, downloads
  (trades CSV, ledger, log, decisions, settings).
- **Backtest**: runs research.py on the machine with fresh data and shows the report.
- **Alerts**: Telegram messages for trades, errors, runner restarts and a daily summary.

## Cloud mode (parked)

`api/index.py` can also run against Upstash Redis instead of local files (it switches automatically when Redis is
configured); `cloud_seed.py` copies the bot's files there. Not used: everything runs on the VPS.

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
