# v6_runtime (PAPER ONLY)

Wraps the V6 scanner (`scanner_v6`, Modules A–E) in a five-book paper portfolio. No broker, no order path.

| Module | Purpose |
|---|---|
| `identity.py` | backend-verified "V6 SMC Scanner" identity (`PAPER_ONLY`, `PLACES_ORDERS=False`, source fingerprint) |
| `paths.py` | data root guard: `/var/lib/trader-v6` (or `V6_DATA_ROOT`); refuses `/opt/trader`, `/etc/trader`, V4 ledgers |
| `books.py` | INDIA ₹100,000 · FNO ₹100,000 · US $1,000 · USFNO $2,000 · CRYPTO $1,000 (owner decisions) |
| `ledger.py` | per-book ledger: owner-authorised creation only, never reset, reconcile on every load/write, duplicate refusal, atomic writes + event log |
| `portfolio.py` | one Module E stream per instrument; book gates (position limit, daily loss, MTM, 1% risk, cash); write-ahead journal + replay recovery |
| `us_stocks.py` | US Stocks config (only APPROVED values used), NYSE calendar sessions, readiness blockers |
| `data/alpaca.py` | Alpaca DATA-ONLY bars adapter (GET data.alpaca.markets bars only; V6 credential file only) |
| `data/feed.py` | completed-bar validation (complete / duplicate / revision / late / out-of-session / misaligned / invalid / stale) |
| `options.py` | US F&O interfaces only; always BLOCKED / NOT READY |
| `status.py`, `runner.py` | aggregated status; gated runner (`status`, `init-book`, `run`) |
| `backtest/` | historical backtesting over the same pipeline (dataset validation, engine, metrics, CLI) |

## NOT APPROVED (must be decided by the owner before the US book can run)

IC-1 fee schedule · IC-2 quantity grid / lot / min quantity · IC-3 price rounding · IC-6 exchange-day rule ·
IC-7 MTM exit slippage · O-1 bar alignment rule · tick sizes and entry/exit slippage ticks · margin rate ·
bar settle seconds / stale threshold · data feed (IEX vs SIP) · symbol list · NYSE calendar verification.
Design points also NOT APPROVED: Module E sizes on the stream's own equity (the book's 1% risk gate rejects anything
larger); same-timestamp entries across instruments resolve in instrument-id order.

## Backtesting (simulation; never a paper or live result)

    python -m v6_runtime.backtest validate --config CFG.json --data AAPL=aapl_5m.csv --start 2026-01-05 --end 2026-03-31
    python -m v6_runtime.backtest run      --config CFG.json --data AAPL=aapl_5m.csv --start 2026-01-05 --end 2026-03-31
    python -m v6_runtime.backtest list
    python -m v6_runtime.backtest show bt-<id> --trades --equity
    python -m v6_runtime.backtest fetch --symbol AAPL --timeframe 5m --start 2026-01-05 --end 2026-03-31 \
        --feed iex --out aapl_5m.csv            # needs the V6 DATA-ONLY credential; refuses (exit 3) without it

- Same pipeline as paper trading: every candle goes through `Portfolio` -> Module E streams (CHoCH -> BOS -> sweep ->
  candlestick -> confirmation -> entry), with the same book gates. Nothing in Modules A-E is changed or bypassed.
- One candle at a time in timestamp order; gaps become DATA_INTERRUPTED / DATA_RESUMED (`gap_policy: interrupt`) or
  stop the run (`fail`). Duplicates, out-of-order rows, invalid OHLCV, off-grid and out-of-session bars are refused.
- Each run has its own SIMULATION ledger (`ledger_kind: BACKTEST`) in `<root>/backtests/<run_id>/`; a paper book is
  never opened. The run id hashes engine version + config + dataset SHA-256s + range, so identical inputs give the
  identical run and `results_sha256`. An interrupted run resumes from its write-ahead journal.
- Configuration (`tests/v6_runtime/fixtures/backtest_us_synthetic.json` is an example) is a RESEARCH ASSUMPTION: every
  Module E value explicit, nothing defaulted, nothing owner-approved. Spread = `half_spread_ticks` added to entry and
  stop-exit slippage (a target fills exactly at TP). US F&O backtests are refused (BLOCKED).
- Metrics: start / end equity, gross / net P&L, return %, trades, wins / losses, win rate, average win / loss, profit
  factor, max drawdown, average planned net R:R and realized R, fees, slippage (incl. spread), equity curve, per-trade
  details with the stage path. Undefined metrics are null with a note, never 0.
- The only bundled dataset is SYNTHETIC (`tests/v6_runtime/fixtures/synth_nyse_5m.csv`): engine tests only.

Tests: `python -m pytest tests/v6_runtime -q`. Operations and rollback: `deploy/v6/README.md`.
