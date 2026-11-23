# How to run the V6 BOS + CHoCH tests

**Repository:** `Voyzer10/claude-trading-bot`, branch `research/v6-smc-scanner`. Research only; nothing here places orders.

```bash
cd <repo or worktree>                        # e.g. /home/claude/v6_wt
python3 -m pytest -q tests/scanner_v6        # full V6 suite; result at audit time: 114 passed
```

## Individual suites (each also runs as a plain script)

```bash
python3 tests/scanner_v6/test_models.py               # models, V4 isolation
python3 tests/scanner_v6/test_no_lookahead.py         # harness
python3 tests/scanner_v6/test_replay_audit.py         # G12 batch / stream oracle harness
python3 tests/scanner_v6/test_swings.py               # swing unit tests
python3 tests/scanner_v6/test_swing_fixtures.py       # Volume-1 swing fixtures (-v for per case)
python3 tests/scanner_v6/test_swing_mutants.py        # faulty detectors must fail
python3 tests/scanner_v6/test_regression_medium_bos.py  # permanent BOS regression (MED01 / MED02)
python3 tests/scanner_v6/test_bos.py                  # BOS vs Volume-1 drafts, regression, parity
python3 tests/scanner_v6/test_choch.py                # structure / CHoCH vs CHD01–CHD16 (D1–D5)
```

| Test file | Tests at audit time |
|---|---|
| test_bos | 7 |
| test_choch | 11 |
| test_models | 12 |
| test_no_lookahead | 5 |
| test_regression_medium_bos | 6 |
| test_replay_audit | 12 |
| test_swing_fixtures | 41 |
| test_swing_mutants | 8 |
| test_swings | 12 |

## Using the 12-chart pack (`visual_regression/inputs/`)

Each `*.json` holds `candles: [{index, open, high, low, close}]`. To recompute the detector output:

```python
import json, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "<repo>")
from scanner_v6.data.candle_models import CandleSeries
from scanner_v6.structure.choch import analyze_structure
C = json.load(open("visual_regression/inputs/V6_Hard_BOS_CHOCH_Chart_1.json"))["candles"]
t0 = datetime(2026, 1, 5, tzinfo=timezone.utc)
s = CandleSeries.from_rows([(t0 + timedelta(minutes=5 * i), c["open"], c["high"], c["low"], c["close"], 0)
                            for i, c in enumerate(C)])
r = analyze_structure(s)       # r.bos, r.events (CHoCH / state changes), r.diagnostics, r.timeline
```

Compare with `visual_regression/marked/EVENTS.csv` and `RESULTS_SUMMARY.md`. Candle numbers there are 1-based; event indices in code are 0-based.

## Rules

- Do **not** turn UNSCORED cases (CHU01, CHU04, CHU05, and anything O4 / O7 / O8 / O9 / S-1) into pass / fail.
- Do not edit fixtures to make a run pass. Report a mismatch instead.
