# Trader bot: notes for Claude Code

Paper-trading bot (testing phase: no broker, no real money) with a Next.js dashboard and a FastAPI backend.
Owner: Ansh. Replies in Hinglish, direct and candid.

## On the VPS (Debian, user `claudeops`)

- Code and data: `/opt/trader` (read-only for you). Bot data: `/opt/trader/trader/`
  - `live/log.txt` runner log, `live/decisions.jsonl` every candidate and why it was traded or skipped,
    `live/state.json`, `paper/ledger.json` paper accounts and trades, `live/auto_config.json` crypto rules.
- Services: `trader-runner` (live.py), `trader-api` (FastAPI on 127.0.0.1:8000), `trader-web` (Next.js :3000),
  `trader-ticker` (Zerodha prices), `trader-crypto-ticker` (Coinbase public crypto prices, no API key),
  `trader-us-ticker` (Alpaca IEX US prices, paper key, data only), `trader-pov` (hourly 1h/4h/D/W/M v4
  direction per chart, `live/pov.json`, display only).
  - status: `systemctl status trader-runner`, logs: `journalctl -u trader-runner -n 100 --no-pager`
  - restart (allowed via sudo): `sudo systemctl restart trader-runner` (or trader-api / trader-web)
- API without password from inside the VPS: `curl -s localhost:8000/api/py/health`,
  `/api/py/ops/system`, `/api/py/ops/performance`, `/api/py/snapshot`.
- Never read or print `/etc/trader/trader.env` (dashboard password) or any key.

## Rules

- Do not change files in `/opt/trader`: every deploy (`deploy/update.sh`) replaces them. Code changes go to
  GitHub (`Voyzer10/claude-trading-bot`): branch -> PR -> CI -> merge -> auto-deploy to the VPS.
- Strategy changes need a backtest first (`research.py`, or the dashboard's Backtest section). Report the
  out-of-sample numbers, not the in-sample ones. Do not loosen filters just to get more trades.
- Paper trading only for now; going live needs the checklist in README ("Before real money").

## Layout

`live.py` runner · `paper.py` paper engine + paper Broker (`execute_order`) · `risk.py` Risk agent (approval required to fill) · `scan_crypto.py` / `scan_nse.py` scanners ·
`auto_crypto.py` / `auto_nse.py` / `auto_fno.py` / `auto_us.py` agents · `research.py` backtests ·
`api/index.py` + `api/_ops.py` backend · `app/`, `components/`, `lib/` dashboard · `deploy/` VPS scripts ·
`.github/workflows/` CI and deploy.
