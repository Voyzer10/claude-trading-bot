#!/usr/bin/env python3
"""Scanner V6 foundation: candle and event models, ordering, timestamps, indices, and module independence
(no V4 / broker / live / network imports). Offline.

    python tests/scanner_v6/test_models.py        (or: python -m pytest tests/scanner_v6)
"""
import ast
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ROOT, load_fixture, raises, run_main  # noqa: E402

from scanner_v6 import PAPER_ONLY, PLACES_ORDERS  # noqa: E402
from scanner_v6.data.candle_models import Candle, CandleError, CandleSeries, to_utc  # noqa: E402
from scanner_v6.models import (BOSEvent, CHoCHEvent, Direction, EventStamp, LiquidityPool, ModelError,  # noqa: E402
                               PoolSide, ReclaimEvent, StructureEvent, SweepEvent, SwingKind, SwingPoint,
                               check_stamp_against)

UTC = timezone.utc
T0 = datetime(2026, 11, 17, 7, 30, tzinfo=UTC)
IST = timezone(timedelta(hours=5, minutes=30))


def series(n=10):
    return CandleSeries([Candle(i, T0 + timedelta(minutes=5 * i), 10, 11, 9, 10.5, 1) for i in range(n)], "X", "5m")


# ------------------------------------------------------------------ candles
def test_candle_valid_and_utc():
    c = Candle(0, datetime(2026, 11, 17, 13, 0, tzinfo=IST), 10, 11, 9, 10.5, 100)
    assert c.ts == datetime(2026, 11, 17, 7, 30, tzinfo=UTC) and c.ts.tzinfo == UTC
    assert to_utc(1763364600) == datetime(2025, 11, 17, 7, 30, tzinfo=UTC)
    assert c.range == 2.0 and isinstance(c.open, float)


def test_candle_rejects_bad_data():
    assert raises(CandleError, Candle, 0, datetime(2026, 1, 1), 1, 2, 0.5, 1)            # naive datetime
    assert raises(CandleError, Candle, 0, T0, 10, 9.9, 9, 10)                            # high below open/close
    assert raises(CandleError, Candle, 0, T0, 10, 11, 10.2, 10.5)                        # low above open
    assert raises(CandleError, Candle, 0, T0, float("nan"), 11, 9, 10)                   # not finite
    assert raises(CandleError, Candle, -1, T0, 10, 11, 9, 10)                            # negative index
    assert raises(CandleError, Candle, 0, T0, 10, 11, 9, 10, -5)                         # negative volume
    assert raises(CandleError, Candle, True, T0, 10, 11, 9, 10)                          # bool is not an index


def test_series_order_and_indices():
    s = series(5)
    assert len(s) == 5 and [c.index for c in s] == list(range(5))
    a, b = Candle(0, T0, 1, 2, 0.5, 1), Candle(1, T0, 1, 2, 0.5, 1)
    assert raises(CandleError, CandleSeries, [a, b])                                     # same timestamp
    b2 = Candle(1, T0 - timedelta(minutes=5), 1, 2, 0.5, 1)
    assert raises(CandleError, CandleSeries, [a, b2])                                    # out of order
    assert raises(CandleError, CandleSeries, [a, Candle(2, T0 + timedelta(minutes=5), 1, 2, 0.5, 1)])  # index gap
    assert raises(TypeError, lambda: s[1:3])                                             # slicing is upto() only
    assert s.index_at(T0 + timedelta(minutes=10)) == 2 and s.index_at(T0 + timedelta(minutes=11)) is None


def test_series_upto_is_a_prefix():
    s = series(8)
    p = s.upto(3)
    assert len(p) == 4 and p[3] is s[3] and p.symbol == "X" and p.timeframe == "5m"
    assert raises(IndexError, s.upto, 8) and raises(IndexError, s.upto, -1)


def test_series_from_repo_shapes():
    d = load_fixture()
    s = CandleSeries.from_chart_json(d, "SYN", "5m")
    assert len(d["t"]) == 120 and len(s) == 119                                          # the None candle skipped
    assert [c.index for c in s] == list(range(119))
    assert s[50].ts == to_utc(d["t"][51])                                                # re-indexed after the gap
    rows = [(c.ts, c.open, c.high, c.low, c.close, c.volume) for c in s]
    s2 = CandleSeries.from_rows(rows)
    assert all(x == y for x, y in zip(s, s2))
    assert raises(CandleError, CandleSeries.from_rows, [(T0, 1, 2, 0.5)])                # too few fields


# ------------------------------------------------------------------ events
def test_stamp_rules():
    st = EventStamp(3, T0, 5, T0 + timedelta(minutes=10))
    assert st.is_confirmed and st.known_at(5) and not st.known_at(4)
    assert not EventStamp(3, T0).is_confirmed and not EventStamp(3, T0).known_at(100)
    assert raises(ModelError, EventStamp, 5, T0, 4)                                      # confirmed before source
    assert raises(ModelError, EventStamp, 5, T0, 6, T0 - timedelta(minutes=1))           # confirmed_ts before ts
    assert raises(ModelError, EventStamp, 5, T0, None, T0)                               # ts without index
    assert raises(ModelError, EventStamp, 5, datetime(2026, 1, 1))                       # naive
    s = series(6)
    assert EventStamp.from_candles(s[2], s[4]) == EventStamp(2, s[2].ts, 4, s[4].ts)


def test_each_event_type_builds_and_validates():
    st = EventStamp(2, T0, 4)
    sw = SwingPoint("sw1", st, kind=SwingKind.HIGH, price=101.5)
    bos = BOSEvent("bos1", EventStamp(6, T0 + timedelta(minutes=20), 6), related=("sw1",),
                   direction=Direction.BULLISH, level=101.5, broken_swing_id="sw1")
    ch = CHoCHEvent("ch1", EventStamp(9, T0 + timedelta(minutes=45), 9), direction=Direction.BEARISH, level=99.0)
    pool = LiquidityPool("lp1", st, related=("sw1",), side=PoolSide.ABOVE, price=101.5)
    sweep = SweepEvent("sp1", EventStamp(7, T0 + timedelta(minutes=35), 7), related=("lp1",), pool_id="lp1",
                       level=101.5, extreme=102.0)
    rec = ReclaimEvent("rc1", EventStamp(8, T0 + timedelta(minutes=40), 8), related=("sp1",), sweep_id="sp1",
                       level=101.5)
    assert isinstance(bos, StructureEvent) and isinstance(ch, StructureEvent)
    assert bos.index == 6 and bos.confirmed_index == 6 and bos.related == ("sw1",) and sw.price == 101.5
    assert pool.side is PoolSide.ABOVE and sweep.pool_id == "lp1" and rec.sweep_id == "sp1"
    # integrity, not strategy
    assert raises(ModelError, SwingPoint, "", st, kind=SwingKind.LOW, price=1)           # empty id
    assert raises(ModelError, SwingPoint, "a", st, related=("a",), price=1)              # self-reference
    assert raises(ModelError, SwingPoint, "a", st, kind="high", price=1)                 # not an enum
    assert raises(ModelError, BOSEvent, "b", st, level=float("inf"))                     # price not finite
    assert raises(ModelError, SweepEvent, "s", st, pool_id="", level=1, extreme=1)       # no pool
    assert raises(ModelError, SweepEvent, "s", st, pool_id="s", level=1, extreme=1)      # its own pool
    assert raises(ModelError, ReclaimEvent, "r", st, sweep_id="", level=1)               # no sweep
    assert raises(ModelError, SwingPoint, "a", "not a stamp", price=1)
    # frozen: an event cannot be edited after it is reported
    assert raises(Exception, setattr, bos, "level", 1.0)


def test_models_hold_no_rules():
    """The models accept any direction / side / level combination: deciding what is valid is the concept modules'
    job, not the models'."""
    st = EventStamp(1, T0, 1)
    assert BOSEvent("b", st, direction=Direction.BEARISH, level=0.0)
    assert SweepEvent("s", st, pool_id="p", level=100.0, extreme=90.0)          # an extreme on either side is allowed
    assert SweepEvent("s2", st, pool_id="p", level=100.0, extreme=110.0)


def test_event_indices_checked_against_series():
    s = series(6)
    ok = BOSEvent("b", EventStamp.from_candles(s[2], s[3]), level=10.0)
    check_stamp_against(s, ok)
    assert raises(ModelError, check_stamp_against, s, BOSEvent("b", EventStamp(2, s[3].ts, 3), level=10.0))
    assert raises(ModelError, check_stamp_against, s, BOSEvent("b", EventStamp(2, s[2].ts, 9), level=10.0))
    assert raises(ModelError, check_stamp_against, s,
                  BOSEvent("b", EventStamp(2, s[2].ts, 3, s[4].ts), level=10.0))


# ------------------------------------------------------------------ independence
FORBIDDEN = ("scanner_v4", "scanner_v5", "scanner_v3", "smc_playbook", "smc", "sweep_reversal", "abcd", "paper",
             "live", "auto_crypto", "auto_nse", "auto_fno", "auto_us", "fno", "fno_stock", "us_options", "kite",
             "alpaca", "coinbase", "scan_crypto", "scan_nse", "research", "research_costs", "api",
             "requests", "urllib", "http", "socket", "subprocess")


def test_v6_imports_nothing_from_v4_broker_live_or_network():
    pkg = os.path.join(ROOT, "scanner_v6")
    bad = []
    for d, _, files in os.walk(pkg):
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(d, f)
            for node in ast.walk(ast.parse(open(p).read(), p)):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                for n in names:
                    if n.split(".")[0] in FORBIDDEN:
                        bad.append("%s imports %s" % (os.path.relpath(p, ROOT), n))
    assert not bad, bad


def test_importing_v6_loads_no_v4_or_broker_module():
    code = ("import sys, scanner_v6, scanner_v6.engine, scanner_v6.models, scanner_v6.config\n"
            "import scanner_v6.structure.swings, scanner_v6.structure.bos, scanner_v6.structure.choch\n"
            "import scanner_v6.structure.protected_levels, scanner_v6.liquidity.liquidity_pools\n"
            "import scanner_v6.liquidity.sweep, scanner_v6.liquidity.reclaim, scanner_v6.entry.candlesticks\n"
            "import scanner_v6.entry.confirmation, scanner_v6.exit.stop_loss, scanner_v6.exit.targets\n"
            "import scanner_v6.exit.trade_management, scanner_v6.order_blocks, scanner_v6.fvg\n"
            "bad=[m for m in %r if m in sys.modules]\nprint(','.join(bad))" % (FORBIDDEN,))
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", "loaded: " + out.stdout


def test_v6_is_research_only():
    assert PAPER_ONLY is True and PLACES_ORDERS is False
    src = []
    for d, _, files in os.walk(os.path.join(ROOT, "scanner_v6")):
        src += [open(os.path.join(d, f)).read() for f in files if f.endswith(".py")]
    blob = "\n".join(src)
    for word in ("cmd_buy", "execute_order", "place_order", "submit_order", "setup_decision", "PAPER_LEDGER"):
        assert word not in blob, word


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
