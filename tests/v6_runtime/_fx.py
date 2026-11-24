"""Shared fixtures for the V6 runtime tests. Market data is the SYNTHETIC Module E fixture from
tests/scanner_v6/test_execution.py (no recorded or live data; no network)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, os.path.join(ROOT, "tests", "scanner_v6")):
    if p not in sys.path:
        sys.path.insert(0, p)

import test_execution as T  # noqa: E402

from v6_runtime.ledger import BookLedger  # noqa: E402
from v6_runtime.paths import DataRoot  # noqa: E402
from v6_runtime.portfolio import InstrumentSpec, Portfolio  # noqa: E402

TWO_CLOSED_ROWS = T.BASE + T.CONFIRM + T.TWO_CLOSED      # BUY stopped at 58, SELL entered 72, target 76
OPEN_ROWS = T.BASE + T.CONFIRM + [T.N, T.Q]              # BUY entered at 51, still open at the end


def cfg(equity="1000", **kw):
    return T.cfg(starting_equity=equity, mtm_exit_slippage_ticks=2, **kw)


def spec(iid, book="US", equity="1000", **kw):
    return InstrumentSpec(iid, book, "5m", T.market(iid), cfg(equity, **kw))


def book(tmp, book_id="US"):
    root = DataRoot(str(tmp))
    return root, BookLedger.create(root, book_id, owner_authorised=True, created_by="test")


def candles(rows, iid):
    return list(T.series(rows, iid))


def feed(pf, streams):
    """streams: {iid: [Candle]} fed in timestamp order (ties in instrument-id order)."""
    allc = sorted(((c.ts, iid, c) for iid, cs in streams.items() for c in cs), key=lambda x: (x[0], x[1]))
    for _, iid, c in allc:
        pf.on_candle(iid, c)


def portfolio(root, led, specs):
    return Portfolio(root, led, specs)
