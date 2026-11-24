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

## US Stocks data feed (owner 2026-11-24, provisional)

Alpaca **IEX real-time** 5-minute bars through the separate V6 DATA-ONLY credential. IEX is one venue, not the
consolidated tape, and is never described as consolidated. Delayed SIP is never used and never a fallback; real-time
SIP is an optional future upgrade (paid subscription). Fail closed: a fetch error accepts nothing and tries no other
feed; an in-session missing bar (IEX prints no bar for an interval without IEX trades) becomes DATA_INTERRUPTED /
DATA_RESUMED and is never filled in or interpolated (a pending entry that needed it expires); a stale feed interrupts
the stream, so no new entry can fill. `data_source` is recorded on every signal, booked trade, heartbeat and backtest
trade; gaps, missing bars and the longest run of consecutive missing bars are reported per symbol. Initial symbol
allowlist (owner 2026-11-24): SPY, QQQ, AAPL, MSFT (IEX coverage checked 18-24 Nov 2026: 0 missing bars); any other
symbol is refused. `bar_settle_seconds` and `stale_after_bars` are config values that stay NOT APPROVED until approved.

## US Stocks intraday decisions (owner 2026-11-24, PR #98)

| Decision | Implementation |
|---|---|
| NYSE calendar | `calendars/nyse.json` verified against the official NYSE Group 2026-2028 list (holidays + 1:00 p.m. early closes); the runner and Module E use the FULL 2026-2027 range (no rolling window); outside it readiness blocks the runner and the feed refuses bars (OUT_OF_SESSION) |
| EOD flat (Module E ME-6) | entry cutoff `entry_cutoff_minutes` before the ACTUAL close (13:00 on early-close days); flatten on the first candle ending at/after close - `eod_flatten_buffer_minutes`, after the SL / TP check, at that close moved adversely by `stop_exit_ticks`, status `EOD_FLATTEN`. If data is missing until the close, the position exits at the next available OPEN with detail `EOD_DATA_MISSING` (no price is invented; the overnight exposure is recorded) |
| Long + short (ME-7) | SELL entries use `short_margin_rate` / `short_quantity_step` / `short_min_quantity`; every short assumption (incl. `short_borrow_assumption`) must be APPROVED, otherwise SELL entries are refused (`BOOK_SHORT_NOT_READY`, SHADOW) and only the short side is NOT READY. Ledger and backtests report LONG / SHORT separately |
| Fractional 0.01 | `lot_size` = `quantity_step` = 0.01; sizing rounds DOWN, so the PLANNED loss at the stop never exceeds the 1% budget and the notional never exceeds capital (a gap through the stop or an `EOD_DATA_MISSING` exit can lose more than planned) |
| Fees (ME-5, `fees_us.py`) | per fill: BUY = commission only; SELL = commission + SEC Section 31 (dated: $0.00/M to 2026-04-03, $20.60/M from 2026-04-04) + FINRA TAF ($0.000195/share cap $9.79 in 2026; $0.000232 cap $11.61 from 2027), each rounded UP to the cent (Alpaca's pass-through convention); commission $0 (Alpaca published pricing); components recorded per fill; readiness blocks if the rate table was last verified > 120 days ago |

Short-selling assumptions (simulation only, never a reproduction of a real $1,000 account: FINRA Rule 4210 requires
$2,000 minimum equity for a margin account, and Alpaca does not support fractional short sales): borrow is assumed
available for the allowlist (easy-to-borrow), no locate / hard-to-borrow simulation, no borrow fee (positions never
held overnight by design; Alpaca: no borrow fee on ETB shorts held overnight since 2025-10-01), margin per
`short_margin_rate` as approved. NOT MODELLED: the CAT pass-through fee (rate not verified); short financing.

Fail-closed rules added after the independent pre-merge audit (claude.ai project doc `claude/V6_PRE_MERGE_PR_AUDIT.md`, not in this repo): the flatten buffer must
be >= the timeframe and the entry cutoff >= buffer + timeframe (else `EXECUTION_CONFIG_INCOMPLETE`, reported by
readiness, never a crash-looping runner); with shorts NOT READY a SELL setup is `NO_TRADE` / `SHORT_SIDE_DISABLED` inside
Module E, so it never occupies the instrument's single position; a flatten on a candle that started at/after the flatten
time is marked `EOD_FLATTEN_LATE`; the live feed refuses bars too old to have been acted on in real time (`TOO_OLD`,
after downtime: the hole becomes a data interruption, nothing is traded retroactively; consequently the strategy starts
cold, without history, on the first start and after any outage); the data adapter refuses HTTP
redirects. Known differences: backtests add `half_spread_ticks` to `stop_exit_ticks` (so EOD fills include the spread)
while the live config has no separate spread term; after an `EOD_DATA_MISSING` exit the book's and the stream's
daily-loss measures can differ for that day; the US fee table makes readiness block 120 days after
`RATES_VERIFIED_ON` (2027-03-24) until the rates are re-verified in code.

## NOT APPROVED (must be decided by the owner before the US book can run)

tick_size · entry / stop-exit / MTM slippage ticks · max_gap_ticks · SL buffer / TP offset · contract_multiplier ·
min_quantity · price_rounding_mode (IC-3) · initial_margin_rate · exchange_day_rule (IC-6) · alignment_rule (O-1) ·
bar_settle_seconds · stale_after_bars · eod_flatten_buffer_minutes · entry_cutoff_minutes · symbols to trade (from the
allowlist). Short side additionally: short_margin_rate · short_quantity_step · short_min_quantity ·
short_borrow_assumption. Design points also NOT APPROVED: Module E sizes on the stream's own equity (the book's 1% risk
gate rejects anything larger); same-timestamp entries across instruments resolve in instrument-id order.

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
