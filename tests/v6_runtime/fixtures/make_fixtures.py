"""Regenerate the SYNTHETIC backtest fixtures (deterministic; no market data).

The price path is the independent Module E test path from tests/scanner_v6/test_execution.py (BASE + CONFIRM +
TWO_CLOSED: a BUY setup that is stopped out, then a SELL setup that reaches its target), re-stamped onto the NYSE
session of Monday 23 Nov 2026 (14:30Z = 09:30 New York, 5-minute bars, 77 bars). It exists to test the engine and
must never be presented as market performance.

    python tests/v6_runtime/fixtures/make_fixtures.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests", "scanner_v6")]

import test_execution as T  # noqa: E402

from v6_runtime.backtest.dataset import write_csv  # noqa: E402

T0 = datetime(2026, 11, 23, 14, 30, tzinfo=timezone.utc)
META = {"source": "SYNTHETIC test fixture (tests/scanner_v6 Module E path); NOT market data", "symbol": "SYNTH",
        "generator": "tests/v6_runtime/fixtures/make_fixtures.py"}


def main():
    rows = T.BASE + T.CONFIRM + T.TWO_CLOSED
    out = [(T0 + timedelta(minutes=5 * i), o, h, l, c, 1000.0) for i, (o, h, l, c) in enumerate(rows)]
    write_csv(os.path.join(HERE, "synth_nyse_5m.csv"), out, META)
    print("wrote %d bars" % len(out))


if __name__ == "__main__":
    main()
