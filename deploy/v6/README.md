# V6 PAPER-ONLY runtime: install, activate, roll back

V6 runs beside V4 as a separate Linux user (`trader-v6`), from a separate code copy (`/opt/trader-v6/app`), with its
own data root (`/var/lib/trader-v6`), its own credential directory (`/etc/trader-v6`) and its own API port
(`127.0.0.1:8001`). V4's `deploy/update.sh` does not install, enable or restart any V6 unit.

Merging to `main` still runs `deploy/update.sh`, which restarts all seven V4 services and rebuilds the dashboard (the
`/v6` page and the V4|V6 switch ship with that build). Without the V6 API running, `/v6` shows **V6 NOT CONNECTED**.

## Install (owner-authorised, nothing starts)

    sudo bash deploy/v6/install_v6.sh

## Owner-only activation steps (each one separately authorised)

1. Start the read API: `sudo systemctl enable --now trader-v6-api` → `/v6` shows **V6 NOT ACTIVE**.
2. Create a fresh book (refuses if it already exists):
   `sudo -u trader-v6 env V6_DATA_ROOT=/var/lib/trader-v6 /opt/trader-v6/venv/bin/python -m v6_runtime.runner init-book --book US --owner-authorised`
   (run from `/opt/trader-v6/app`).
3. Write `/var/lib/trader-v6/config/us_stocks.json` from `v6_runtime/config/us_stocks.template.json` with every value
   APPROVED (IC-1 fees, IC-2 quantity grid, IC-6 day rule, IC-7 MTM slippage, O-1 alignment, feed iex/sip, symbols).
4. Verify `v6_runtime/calendars/nyse.json` against the NYSE holiday list and set `"verified": true` (code change → PR).
5. Supply the V6 DATA-ONLY Alpaca credential (never the V4 key):
   `/etc/trader-v6/alpaca-data.json`, mode 0600, owner trader-v6:
   `{"purpose": "v6-data-only", "key_id": "...", "secret": "..."}`
6. Check: `... -m v6_runtime.runner status` (no blockers listed under readiness.US).
7. Owner switch: `sudo -u trader-v6 touch /var/lib/trader-v6/runtime/ENABLED_US`, then
   `sudo systemctl enable --now trader-v6-runner`. Removing the file stops the loop (exit 3, no restart).

## Roll back

- Stop paper execution only: `sudo rm /var/lib/trader-v6/runtime/ENABLED_US` (or `systemctl stop trader-v6-runner`).
- Remove V6 from the VPS, keep its data: `sudo bash deploy/v6/uninstall_v6.sh`.
- Remove the dashboard page/switch: revert the merge commit on `main` (V4 redeploys as before).
V4 files, services, ledgers and `/etc/trader` are untouched by every step above.
