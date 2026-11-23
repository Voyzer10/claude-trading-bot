# Scanner V6: independent Smart Money Concepts scanner (research)

Branch: `research/v6-smc-scanner` (the only V6 branch). Research only: **PAPER ONLY, no orders, no broker, not wired
to the live runner.**

Status (22 Nov 2026): swings, BOS, protected swings and CHoCH are implemented **for the approved rules only** (see research/v6/specs/choch_v0_9/PHASE1_2_DECISIONS.md). Earlier status: **foundation only.** The data models, candle handling and the no-look-ahead harness exist. **No trading rule
is implemented**: no swing, BOS, CHoCH, pool, sweep, reclaim, pattern, confirmation, stop, target or trade-management
logic.

## Architecture

```
candles (rows / chart JSON)
   └─ data/candle_models.py   Candle, CandleSeries (validated, UTC, indices 0..n-1, upto(k) = known at candle k)
        └─ engine.py          runs detectors; no_lookahead_violations(); events_known_at()
             ├─ structure/    swings → protected levels → BOS / CHoCH
             ├─ liquidity/    pools → sweep → reclaim
             ├─ entry/        candlestick pattern → confirmation
             ├─ exit/         stop-loss, targets, trade management (simulation only)
             ├─ order_blocks/ fvg/   (later)
             └─ models.py     the event types every module returns
```

Every detector has the same contract: `detector(series) -> list[Event]`. Each event carries:
- an `EventStamp`: the source candle `index` / `ts`, and the `confirmed_index` / `confirmed_ts` at whose close it is first known
- a stable `id`
- the `related` ids of the events it builds on (e.g. sweep → pool → swing)

The engine's `no_lookahead_violations(detector, series)` replays a detector candle by candle. It reports:
- any event shown before it is confirmed
- any event that refers to a future candle
- any event that is later revised (repainting)

## Modules

| Module | Responsibility | State |
|---|---|---|
| `config.py` | Neutral run settings; `PAPER_ONLY = True`, `PLACES_ORDERS = False` (constants) | done |
| `models.py` | `EventStamp`, `Event`, `SwingPoint`, `StructureEvent`, `BOSEvent`, `CHoCHEvent`, `LiquidityPool`, `SweepEvent`, `ReclaimEvent`; integrity checks only | done |
| `data/candle_models.py` | `Candle`, `CandleSeries`, loading from the repo's row and chart-JSON shapes, UTC timestamps | done |
| `engine.py` | Detector contract, `run()`, the one-way `no_lookahead_violations()`, and the G12 oracle `replay_audit()` (batch + streaming: premature / early / late / missing / duplicate / unexpected / repaint / parity) | done |
| `structure/swings.py` | Swing highs / lows, **approved baseline only**: fixed window L2/R2 (configurable), strict, equal levels unresolved (diagnostic only), dual pivots allowed; batch `detect_swings` + streaming `SwingStream` | done (21 Nov 2026) |
| `structure/protected_levels.py` | Protected swings, **D2 P-B**: the BOS-origin swing becomes protected only after its own L2/R2 confirmation; until then the previous one is kept; A5 HL / LH qualification | done (22 Nov 2026) |
| `structure/bos.py` | BOS, **approved rules only**: BOS-001…005, Option A, D4 latest-confirmed reference (no latest-unbroken fallback), D5 order; batch `detect_bos` + streaming `BOSStream` | done (22 Nov 2026) |
| `structure/choch.py` | Structure state + CHoCH: A1–A10, D1 (CHoCH → TRANSITION → a separate later BOS confirms), D3 (X1 / COMPLEX guard), D5. **Not final:** O4, O7, O8, O9, CHU04, CHU05 are diagnostics only. Batch `analyze_structure` / `detect_structure` + streaming `StructureStream` | done for the approved rules (22 Nov 2026) |
| `liquidity/liquidity_pools.py` | Where resting liquidity sits | not started |
| `liquidity/sweep.py` | A pool taken out | not started |
| `liquidity/reclaim.py` | Back across a swept level | not started |
| `entry/candlesticks.py` | Entry candle patterns | not started |
| `entry/confirmation.py` | Confirmation after the pattern | not started |
| `exit/stop_loss.py`, `exit/targets.py`, `exit/trade_management.py` | Stops, targets, management (research simulation) | not started |
| `order_blocks/`, `fvg/` | Order blocks, fair value gaps | later |

## Separation from V4

- V6 imports **nothing** from:
  - `scanner_v4.py` (or v3 / v5)
  - `smc_playbook.py`, `paper.py`, `live.py`, the `auto_*` agents, the scanners, the broker / data clients
  - `research*.py`
  - any network library

  It does not copy V4's BOS or sweep code. `tests/scanner_v6/test_models.py` enforces this: it checks the source imports and the modules loaded at import time.
- **No V4 or production file was changed.** Production routing (`scanner_version`) does not know V6 exists.
- V6 reuses only the repo's **data shapes** (rows `(ts, o, h, l, c, v)` and chart JSON `{t,o,h,l,c,v}`). It has its own loader.

## Development plan (one concept at a time)

Each concept goes through the same steps before the next concept starts:
1. Written definition from the owner's spec.
2. Implementation.
3. Unit tests on hand-built candles.
4. A no-look-ahead test with the harness.
5. A review.

| Step | Concept |
|---|---|
| 1 | Swings: definition, confirmation delay, equal highs / lows |
| 2 | Protected levels and trend state |
| 3 | BOS: close or wick, which swing, one BOS per swing |
| 4 | CHoCH |
| 5 | Liquidity pools |
| 6 | Sweep (wick / close) and its link to the structure |
| 7 | Reclaim |
| 8 | Candlestick patterns |
| 9 | Confirmation |
| 10 | Stop-loss, targets, trade management (simulation) |
| 11 | Order blocks, FVG |
| 12 | Research backtests with costs and an IS / OOS split declared in advance (`research/v6/`) |

Connecting V6 to paper trading is a separate decision, after the research evidence. It is not part of this plan.

## Tests

```
python tests/scanner_v6/test_models.py
python tests/scanner_v6/test_no_lookahead.py
python tests/scanner_v6/test_replay_audit.py      # G12 harness
python tests/scanner_v6/test_swings.py            # swing unit tests
python tests/scanner_v6/test_swing_fixtures.py    # all Volume-1 fixtures (-v for per-case lines)
python tests/scanner_v6/test_swing_mutants.py     # faulty detectors must fail
python tests/scanner_v6/test_regression_medium_bos.py   # permanent regression: the exam-chart BOS mistakes (MED01/MED02 = Easy charts 1/2)
python tests/scanner_v6/test_bos.py               # BOS module vs Volume-1 drafts, regression, parity
python tests/scanner_v6/test_choch.py             # CHoCH / structure vs CHD01-CHD16 (approved D1-D5)
python research/v6/experiments/medium_bos_retest.py grade   # blind visual retest (reads PNG pixels only)
python -m pytest -q tests/scanner_v6          # same tests under pytest
```
