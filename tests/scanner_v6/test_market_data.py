#!/usr/bin/env python3
"""Scanner V6 Module A (market data and candle integrity): OHLCV validation, UTC, ordering and indices; completed vs
incomplete candles; gap detection with explicit timeframe / session calendar; tick-size metadata; test-only fixture
configuration isolation (IR-3 / OQ-15); OQ-3 data_state. Offline: no provider, no network, no real instrument values.
Every session interval and tick size below is a synthetic TEST value, not a market fact.

    python tests/scanner_v6/test_market_data.py   (or: python -m pytest tests/scanner_v6)
"""
import dataclasses
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import load_fixture, raises, run_main  # noqa: E402

from scanner_v6.data.candle_models import (Candle, CandleError, CandleSeries, inspect_chart_json,  # noqa: E402
                                          to_utc)
from scanner_v6.data.integrity import (CandleUpdate, CompletedCandleGate, DataState, DataStateError,  # noqa: E402
                                       DataStateTracker, GapKind, GapReportStatus, GapStream, GateError,
                                       StalenessPolicy, detect_gaps, drive_completed)
from scanner_v6.data.market_config import (ConfigError, ConfigIsolationError, ConfigOrigin,  # noqa: E402
                                           MarketDataConfig, SessionCalendar, SessionKind, TickSizeStatus,
                                           require_instrument_config, validate_tick_size)
from scanner_v6.structure.choch import StructureStream, detect_structure  # noqa: E402
from scanner_v6.structure.swings import SwingStream  # noqa: E402

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
M5 = timedelta(minutes=5)
D1 = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)       # synthetic test session day 1
D2 = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)       # synthetic test session day 2
# TEST-ONLY calendar: two one-hour sessions. Not any real exchange's hours.
CAL = SessionCalendar(SessionKind.EXCHANGE, "UTC", ((D1, D1 + timedelta(hours=1)), (D2, D2 + timedelta(hours=1))))
CONT = SessionCalendar(SessionKind.CONTINUOUS, "UTC")


def C(i, ts, o=10.0, h=11.0, l=9.0, c=10.5, v=1.0):
    return Candle(i, ts, o, h, l, c, v)


def ser(times):
    return CandleSeries([C(i, t) for i, t in enumerate(times)])


def U(ts, done, o=10.0, h=11.0, l=9.0, c=10.5, v=1.0):
    return CandleUpdate(ts, o, h, l, c, v, done)


def day(start, n):
    return [start + M5 * j for j in range(n)]


# ------------------------------------------------------------------ A1 candle integrity
def test_a1_valid_and_invalid_ohlcv():
    c = C(0, D1, 10, 12, 8, 11, 5)
    assert (c.open, c.high, c.low, c.close, c.volume) == (10.0, 12.0, 8.0, 11.0, 5.0)
    bad = [(10, 9.5, 8, 9), (10, 12, 10.5, 11), (10, 8, 12, 10), (math.nan, 12, 8, 11), (10, 12, 8, math.inf),
           (True, 12, 8, 11), ("10", 12, 8, 11)]
    for o, h, l, cl in bad:
        assert raises(CandleError, Candle, 0, D1, o, h, l, cl, 1), (o, h, l, cl)
    assert raises(CandleError, Candle, 0, D1, 10, 12, 8, 11, -1)
    assert raises(CandleError, Candle, -1, D1, 10, 12, 8, 11, 1)


def test_a1_utc_normalisation_and_naive_rejection():
    ist = datetime(2026, 11, 17, 15, 30, tzinfo=IST)
    assert C(0, ist).ts == D1 and C(0, ist).ts.tzinfo == UTC
    assert to_utc(int(D1.timestamp())) == D1
    assert raises(CandleError, to_utc, datetime(2026, 11, 17, 10, 0))
    assert raises(CandleError, to_utc, math.nan)
    assert raises(CandleError, to_utc, "2026-11-17T10:00:00Z")


def test_a1_candles_are_immutable():
    c = C(0, D1)
    assert raises(dataclasses.FrozenInstanceError, setattr, c, "close", 99.0)
    assert c.close == 10.5


def test_a1_duplicates_out_of_order_and_indices_rejected_not_repaired():
    assert raises(CandleError, ser, [D1, D1])                              # duplicate timestamp
    assert raises(CandleError, ser, [D1 + M5, D1])                         # out of order: not sorted silently
    assert raises(CandleError, CandleSeries, [C(0, D1), C(2, D1 + M5)])     # index gap
    assert raises(CandleError, CandleSeries, [C(1, D1)])                    # not zero-based
    s = CandleSeries.from_rows([(D1, 10, 11, 9, 10.5, 1), (D1 + M5, 10.5, 12, 10, 11.75, 2)])
    assert [c.index for c in s] == [0, 1] and s[1].close == 11.75          # values kept exactly


# ------------------------------------------------------------------ A2 completed vs incomplete candles
def test_a2_incomplete_updates_are_never_returned():
    g = CompletedCandleGate()
    assert g.feed(U(D1, False, 10, 10.2, 9.9, 10.1)) is None
    assert g.feed(U(D1, False, 10, 10.8, 9.5, 10.6)) is None
    assert len(g.completed) == 0 and g.forming.close == 10.6
    c = g.feed(U(D1, True, 10, 11, 9, 10.5))
    assert isinstance(c, Candle) and c.index == 0 and (c.high, c.low, c.close) == (11.0, 9.0, 10.5)
    assert g.forming is None and len(g.completed) == 1


def test_a2_completion_must_be_an_explicit_bool():
    for v in (1, 0, None, "yes"):
        assert raises(CandleError, CandleUpdate, D1, 10, 11, 9, 10.5, 1, v), v
    assert raises(TypeError, CandleUpdate, D1, 10, 11, 9, 10.5, 1)          # no default
    assert raises(CandleError, CandleUpdate, D1, 10, 9, 11, 10, 1, True)    # invalid OHLC rejected
    assert raises(CandleError, CandleUpdate, datetime(2026, 11, 17, 10), 10, 11, 9, 10.5, 1, False)  # naive


def test_a2_completed_candle_never_duplicated_reordered_or_changed():
    g = CompletedCandleGate()
    g.feed(U(D1, True))
    for done in (True, False):
        assert raises(GateError, g.feed, U(D1, done, c=10.9))              # same candle again
        assert raises(GateError, g.feed, U(D1 - M5, done))                 # older candle
    g.feed(U(D1 + M5, False))
    assert raises(GateError, g.feed, U(D1 + M5 - timedelta(minutes=1), False))   # before the forming candle
    assert g.completed[0].close == 10.5 and len(g.completed) == 1


def test_a2_unfinished_candle_is_abandoned_not_completed():
    g = CompletedCandleGate()
    g.feed(U(D1, True))
    g.feed(U(D1 + M5, False))                                              # never completed by the source
    c = g.feed(U(D1 + 2 * M5, True))
    assert c.index == 1 and c.ts == D1 + 2 * M5
    assert [u.ts for u in g.abandoned] == [D1 + M5]
    rep = detect_gaps(g.completed, M5, CONT)                               # the hole is visible, not filled
    assert [(x.kind, x.prev_index, x.index, x.missing_count) for x in rep.gaps] == [(GapKind.MISSING_CANDLES, 0, 1, 1)]


def test_a2_no_lookahead_at_candle_boundaries():
    s = inspect_chart_json(load_fixture()).partial_series("SYN", "5m")   # explicit: fixture row 50 is invalid
    updates = []
    for c in s:   # two misleading forming updates per candle, then the true completed candle
        updates.append(CandleUpdate(c.ts, c.open, c.high + 50, c.low - 50, c.high + 49, c.volume, False))
        updates.append(CandleUpdate(c.ts, c.open, c.high + 5, max(c.low - 5, 0.0), c.low - 1 if c.low > 6 else c.low,
                                    c.volume, False))
        updates.append(CandleUpdate(c.ts, c.open, c.high, c.low, c.close, c.volume, True))
    events, gate = drive_completed(updates, StructureStream())
    assert [(x.open, x.high, x.low, x.close, x.ts) for x in gate.completed] == \
        [(x.open, x.high, x.low, x.close, x.ts) for x in s]
    assert events == detect_structure(s)                                   # forming values never leaked
    assert events                                                          # the check is not vacuous
    st, g2 = StructureStream(), CompletedCandleGate()                      # emitted at k -> known at k
    for u in updates:
        c = g2.feed(u)
        if c is not None:
            assert all(e.confirmed_index is not None and e.confirmed_index <= c.index for e in st.on_candle(c))
    assert raises(TypeError, SwingStream().on_candle, updates[0])          # a detector refuses a non-Candle


# ------------------------------------------------------------------ A3 gaps
def test_a3_contiguous_series_has_no_gaps():
    rep = detect_gaps(ser(day(D1, 12)), M5, CAL)
    assert rep.status is GapReportStatus.OK and rep.gaps == ()


def test_a3_missing_candles_are_reported_never_filled():
    s = ser([D1, D1 + M5, D1 + 4 * M5])
    rep = detect_gaps(s, M5, CONT)
    assert rep.status is GapReportStatus.OK and len(s) == 3
    (g,) = rep.gaps
    assert (g.kind, g.prev_index, g.index, g.prev_ts, g.ts) == (GapKind.MISSING_CANDLES, 1, 2, D1 + M5, D1 + 4 * M5)
    assert (g.slots, g.missing_count, g.first_missing_ts, g.last_missing_ts) == (2, 2, D1 + 2 * M5, D1 + 3 * M5)


def test_a3_session_closure_vs_unexpected_gap():
    closure = ser(day(D1, 12) + day(D2, 3))
    (g,) = detect_gaps(closure, M5, CAL).gaps
    assert (g.kind, g.missing_count, g.crosses_session_break) == (GapKind.SESSION_CLOSURE, 0, True)
    t = day(D1, 12)
    del t[5]                                                               # 10:25 missing inside the session
    (g,) = detect_gaps(ser(t), M5, CAL).gaps
    assert (g.kind, g.missing_count, g.first_missing_ts, g.crosses_session_break) == \
        (GapKind.MISSING_CANDLES, 1, D1 + 5 * M5, False)
    late = ser(day(D1, 12) + day(D2 + 2 * M5, 2))                          # day 2 opens late: 10:00, 10:05 absent
    (g,) = detect_gaps(late, M5, CAL).gaps
    assert (g.kind, g.missing_count, g.first_missing_ts, g.last_missing_ts, g.crosses_session_break) == \
        (GapKind.MISSING_CANDLES, 2, D2, D2 + M5, True)


def test_a3_out_of_session_candle_and_irregular_interval():
    rep = detect_gaps(ser([D1 + timedelta(minutes=55), D1 + timedelta(minutes=60)]), M5, CAL)
    assert [(g.kind, g.index) for g in rep.gaps] == [(GapKind.OUT_OF_SESSION_CANDLE, 1)]
    rep = detect_gaps(ser([D1 - M5, D1]), M5, CAL)
    assert [(g.kind, g.index) for g in rep.gaps] == [(GapKind.OUT_OF_SESSION_CANDLE, 0)]
    rep = detect_gaps(ser([D1, D1 + timedelta(minutes=7)]), M5, CAL)
    assert [g.kind for g in rep.gaps] == [GapKind.IRREGULAR_INTERVAL]


def test_a3_missing_timeframe_or_calendar_is_unknown_not_assumed():
    s = ser([D1, D1 + 3 * M5])
    rep = detect_gaps(s, None, CAL)
    assert (rep.status, rep.reason, rep.gaps) == (GapReportStatus.UNKNOWN, "TIMEFRAME_MISSING", ())
    rep = detect_gaps(s, M5, None)
    assert (rep.status, rep.reason) == (GapReportStatus.UNKNOWN, "SESSION_CALENDAR_MISSING")
    assert [(g.kind, g.slots, g.missing_count) for g in rep.gaps] == [(GapKind.UNCLASSIFIED_GAP, 2, None)]
    # calendar reconciliation (23 Nov 2026): no calendar -> UNKNOWN even without a gap (was: OK)
    assert (detect_gaps(ser(day(D1, 4)), M5, None).status, detect_gaps(ser(day(D1, 4)), M5, None).reason) == \
        (GapReportStatus.UNKNOWN, "SESSION_CALENDAR_MISSING")
    assert raises(ConfigError, detect_gaps, s, timedelta(0), CAL)
    assert raises(ConfigError, GapStream, None)


def test_a3_batch_stream_parity_and_determinism():
    t = day(D1, 12)
    del t[3]
    cases = [(ser(t + day(D2 + 2 * M5, 4)), CAL), (ser([D1, D1 + 4 * M5, D1 + 9 * M5]), CONT),
             (ser([D1, D1 + 3 * M5]), None), (ser([D1 - M5] + day(D1, 3)), CAL)]
    for s, cal in cases:
        batch = detect_gaps(s, M5, cal)
        st = GapStream(M5, cal)
        stream = [g for c in s for g in st.on_candle(c)]
        assert tuple(stream) == batch.gaps, (stream, batch.gaps)
        assert detect_gaps(s, M5, cal) == batch
    st = GapStream(M5, CAL)
    st.on_candle(C(0, D1))
    assert raises(CandleError, st.on_candle, C(2, D1 + M5))


# ------------------------------------------------------------------ A4 tick size
def test_a4_tick_size_must_be_positive_and_finite():
    assert validate_tick_size(0.05) == 0.05 and validate_tick_size(1) == 1.0
    for v in (0, -0.01, math.nan, math.inf, True, "0.05", None):
        assert raises(ConfigError, validate_tick_size, v), v
    assert raises(ConfigError, MarketDataConfig, ConfigOrigin.INSTRUMENT_CONFIG, tick_size=0)


def test_a4_missing_tick_size_stays_missing_and_is_never_inferred():
    for cfg in (MarketDataConfig(ConfigOrigin.INSTRUMENT_CONFIG), MarketDataConfig.from_fixture({})):
        r = cfg.tick_size_result()
        assert (r.status, r.value, cfg.tick_size) == (TickSizeStatus.MISSING, None, None)
    ok = MarketDataConfig.from_fixture({"tick_size": 0.05}).tick_size_result()
    assert (ok.status, ok.value) == (TickSizeStatus.AVAILABLE, 0.05)
    c = C(0, D1, 10.033, 10.071, 10.001, 10.049)                           # off-grid prices are kept unchanged
    assert (c.open, c.high, c.low, c.close) == (10.033, 10.071, 10.001, 10.049)


# ------------------------------------------------------------------ IR-3 / OQ-15 config isolation
def test_fixture_config_is_test_only_and_never_instrument_config():
    fx = MarketDataConfig.from_fixture({"instrument_id": "TEST-SYN", "timeframe_seconds": 300, "tick_size": 0.05,
                                        "session": {"kind": "continuous_24_7", "timezone": "UTC"}})
    assert fx.origin is ConfigOrigin.TEST_FIXTURE and fx.timeframe == M5 and fx.session == CONT
    assert raises(ConfigIsolationError, require_instrument_config, fx)
    real = MarketDataConfig(ConfigOrigin.INSTRUMENT_CONFIG)
    assert require_instrument_config(real) is real
    assert raises(TypeError, MarketDataConfig)                             # no default origin
    assert raises(ConfigError, MarketDataConfig, "test_fixture")
    assert MarketDataConfig.from_fixture({"tick_size": 0.05}) == MarketDataConfig.from_fixture({"tick_size": 0.05})


def test_fixture_config_missing_stays_missing_and_typos_fail():
    fx = MarketDataConfig.from_fixture({})
    assert (fx.instrument_id, fx.timeframe, fx.tick_size, fx.session) == (None, None, None, None)
    for bad in ({"tick": 0.05}, {"tick_size": -1}, {"timeframe_seconds": 0}, {"timeframe_seconds": True},
                {"session": {"kind": "weekdays", "timezone": "UTC"}}, {"session": {"kind": "continuous_24_7"}},
                {"session": {"kind": "continuous_24_7", "timezone": "UTC", "hours": "9-5"}}):
        assert raises(ConfigError, MarketDataConfig.from_fixture, bad), bad


def test_session_calendar_validation():
    naive = datetime(2026, 11, 17, 10)
    bad = [lambda: SessionCalendar(SessionKind.EXCHANGE, "Not/AZone", ((D1, D1 + M5),)),
           lambda: SessionCalendar(SessionKind.EXCHANGE, "", ((D1, D1 + M5),)),
           lambda: SessionCalendar(SessionKind.EXCHANGE, "UTC", ((naive, naive + M5),)),
           lambda: SessionCalendar(SessionKind.EXCHANGE, "UTC", ((D1, D1),)),
           lambda: SessionCalendar(SessionKind.EXCHANGE, "UTC", ((D1, D1 + 2 * M5), (D1 + M5, D1 + 3 * M5))),
           lambda: SessionCalendar(SessionKind.EXCHANGE, "UTC", ()),
           lambda: SessionCalendar(SessionKind.CONTINUOUS, "UTC", ((D1, D1 + M5),)),
           lambda: SessionCalendar("continuous_24_7", "UTC")]
    for i, f in enumerate(bad):
        assert raises(ConfigError, f), i
    assert CAL.session_index(D1) == 0 and CAL.session_index(D1 + timedelta(hours=1)) is None
    assert CAL.session_index(D2 + M5) == 1 and CAL.session_index(D1 - M5) is None
    assert CONT.session_index(D1) == 0


# ------------------------------------------------------------------ A5 data state (OQ-3)
def test_a5_normal_interrupted_resumed_transitions():
    tr = DataStateTracker()
    assert tr.state is DataState.NORMAL and not tr.new_entries_suspended
    tr.mark_interrupted(D1, "DISCONNECTED")
    assert tr.state is DataState.DATA_INTERRUPTED and tr.new_entries_suspended and tr.interrupted_at == D1
    tr.mark_resumed(D1 + 3 * M5, "RECONNECTED")
    assert tr.state is DataState.DATA_RESUMED and not tr.new_entries_suspended and tr.resumed_at == D1 + 3 * M5
    tr.mark_interrupted(D1 + 6 * M5, "DISCONNECTED")
    assert [(h.before, h.after) for h in tr.history] == [
        (DataState.NORMAL, DataState.DATA_INTERRUPTED), (DataState.DATA_INTERRUPTED, DataState.DATA_RESUMED),
        (DataState.DATA_RESUMED, DataState.DATA_INTERRUPTED)]
    assert tr.interrupted_at == D1 + 6 * M5 and tr.resumed_at == D1 + 3 * M5


def test_a5_invalid_transitions_and_times_rejected():
    tr = DataStateTracker()
    assert raises(DataStateError, tr.mark_resumed, D1, "x")
    tr.mark_interrupted(D1, "x")
    assert raises(DataStateError, tr.mark_interrupted, D1 + M5, "x")
    assert raises(DataStateError, tr.mark_resumed, D1 - M5, "x")
    assert raises(CandleError, tr.mark_resumed, datetime(2026, 11, 17, 11), "x")
    assert tr.state is DataState.DATA_INTERRUPTED and len(tr.history) == 1


def test_a5_stale_and_disconnected_data_suspend_entries():
    pol = StalenessPolicy(timedelta(minutes=10))     # explicit TEST value, not a recommended threshold
    tr = DataStateTracker()
    assert tr.observe(D1, D1 - M5, pol) is None and tr.state is DataState.NORMAL
    ch = tr.observe(D1 + 20 * M5, D1, pol)
    assert (ch.after, ch.reason, tr.new_entries_suspended) == (DataState.DATA_INTERRUPTED, "STALE", True)
    assert tr.observe(D1 + 21 * M5, D1, pol) is None                       # still stale: one change only
    ch = tr.observe(D1 + 22 * M5, D1 + 21 * M5, pol)
    assert (ch.after, tr.new_entries_suspended) == (DataState.DATA_RESUMED, False)
    tr2 = DataStateTracker()
    assert tr2.observe(D1, None, pol).reason == "NO_DATA"
    assert raises(ConfigError, tr.observe, D1 + 30 * M5, D1, None)
    assert raises(DataStateError, DataStateTracker().observe, D1, D1 + M5, pol)
    for v in (timedelta(0), 600):
        assert raises(ConfigError, StalenessPolicy, v)


def test_a5_interruption_fabricates_nothing_and_resumes_chronologically():
    g, tr = CompletedCandleGate(), DataStateTracker()
    for t in day(D1, 3):
        g.feed(U(t, True))
    tr.mark_interrupted(D1 + 3 * M5, "DISCONNECTED")
    assert len(g.completed) == 3                                           # nothing added while interrupted
    tr.mark_resumed(D1 + 7 * M5, "RECONNECTED")
    for t in (D1 + 6 * M5, D1 + 7 * M5):                                    # backlog processed in time order
        g.feed(U(t, True))
    assert raises(GateError, g.feed, U(D1 + 5 * M5, True))                 # a late older candle is refused
    assert [c.index for c in g.completed] == [0, 1, 2, 3, 4]
    (gap,) = detect_gaps(g.completed, M5, CAL).gaps
    assert (gap.kind, gap.prev_index, gap.index, gap.missing_count) == (GapKind.MISSING_CANDLES, 2, 3, 3)


# ------------------------------------------------------------------ determinism (A7 boundary, no provider)
class _ToyProvider:
    """In-test stand-in for the provider boundary: replays fixed updates. No network, no credentials."""

    def __init__(self, ups):
        self._ups = list(ups)

    def updates(self):
        return iter(self._ups)


def test_deterministic_replay_through_the_provider_boundary():
    s = inspect_chart_json(load_fixture()).partial_series("SYN", "5m")   # explicit: fixture row 50 is invalid
    ups = [CandleUpdate(c.ts, c.open, c.high, c.low, c.close, c.volume, k) for c in s for k in (False, True)]
    runs = [drive_completed(_ToyProvider(ups).updates(), StructureStream()) for _ in range(2)]
    assert runs[0][0] == runs[1][0]
    assert [tuple(vars(c).values()) for c in runs[0][1].completed] == [tuple(vars(c).values()) for c in s]



# ------------------------------------------------------------------ stabilization: adversarial matrix (23 Nov 2026)
def test_m26_missing_tick_size_is_missing_status():
    for cfg in (MarketDataConfig(ConfigOrigin.INSTRUMENT_CONFIG), MarketDataConfig.from_fixture({})):
        r = cfg.tick_size_result()
        assert r.status is TickSizeStatus.MISSING and r.value is None and cfg.tick_size is None


def test_m27_invalid_tick_size_rejected():
    for bad in (0, -0.05, math.nan, math.inf, -math.inf, "0.05", True, None.__class__):
        assert raises(ConfigError, validate_tick_size, bad), bad
        assert raises(ConfigError, MarketDataConfig, ConfigOrigin.TEST_FIXTURE, tick_size=bad), bad
        assert raises(ConfigError, MarketDataConfig.from_fixture, {"tick_size": bad}), bad
    assert MarketDataConfig.from_fixture({"tick_size": 0.05}).tick_size_result().value == 0.05


def test_m28_missing_timeframe_or_session_configuration():
    cfg = MarketDataConfig.from_fixture({"instrument_id": "SYN"})
    assert cfg.timeframe is None and cfg.session is None and cfg.origin is ConfigOrigin.TEST_FIXTURE
    s = ser([D1, D1 + 3 * M5])
    r = detect_gaps(s, None, CAL)
    assert r.status is GapReportStatus.UNKNOWN and r.reason == "TIMEFRAME_MISSING" and r.gaps == ()
    r = detect_gaps(s, M5, None)
    assert r.status is GapReportStatus.UNKNOWN and r.reason == "SESSION_CALENDAR_MISSING"
    assert [g.kind for g in r.gaps] == [GapKind.UNCLASSIFIED_GAP] and r.gaps[0].missing_count is None
    assert raises(ConfigError, GapStream, None) and raises(ConfigError, detect_gaps, s, 300, CAL)
    assert raises(ConfigError, detect_gaps, s, M5, "UTC")
    for bad in ({"timeframe_seconds": 0}, {"timeframe_seconds": -300}, {"timeframe_seconds": "300"},
                {"timeframe_seconds": math.nan}, {"session": {"kind": "exchange_sessions", "timezone": "UTC"}},
                {"session": {"kind": "continuous_24_7"}}, {"session": {"kind": "weekly", "timezone": "UTC"}}):
        assert raises(ConfigError, MarketDataConfig.from_fixture, bad), bad


def test_d4_malformed_configuration_is_config_error_not_crash():
    """D4 (reproduced 23 Nov 2026): malformed configuration escaped as TypeError / OverflowError instead of
    ConfigError (timeframe_seconds too large for a timedelta; a non-iterable session list or session pair; a session
    bound outside the datetime range)."""
    tz = "Asia/Kolkata"
    bad_fixtures = ({"timeframe_seconds": 1e300},
                    {"session": {"kind": "exchange_sessions", "timezone": tz, "sessions": 5}},
                    {"session": {"kind": "exchange_sessions", "timezone": tz, "sessions": [5]}},
                    {"session": {"kind": "exchange_sessions", "timezone": tz, "sessions": [[1e20, 2e20]]}},
                    {"session": {"kind": "exchange_sessions", "timezone": tz, "sessions": "ab"}})
    for d in bad_fixtures:
        assert raises(ConfigError, MarketDataConfig.from_fixture, d), d
    for sessions in (5, ((1e20, 2e20),), "ab", ((D1, None),)):
        assert raises(ConfigError, SessionCalendar, SessionKind.EXCHANGE, "UTC", sessions), sessions
    ok = MarketDataConfig.from_fixture({"session": {"kind": "exchange_sessions", "timezone": tz,
                                                    "sessions": [[D1.timestamp(), D1.timestamp() + 3600]]}})
    assert ok.session.contains(D1) and not ok.session.contains(D1 + timedelta(hours=1))


def test_m29_data_interrupted_state():
    tr, pol = DataStateTracker(), StalenessPolicy(timedelta(minutes=10))
    assert tr.state is DataState.NORMAL and not tr.new_entries_suspended
    assert tr.observe(D1, D1 - timedelta(minutes=5), pol) is None                # fresh: no change
    ch = tr.observe(D1 + timedelta(minutes=20), D1, pol)                          # 20 min old > 10 min: stale
    assert (ch.before, ch.after, ch.reason) == (DataState.NORMAL, DataState.DATA_INTERRUPTED, "STALE")
    assert tr.new_entries_suspended and tr.interrupted_at == D1 + timedelta(minutes=20)
    assert tr.observe(D1 + timedelta(minutes=30), D1, pol) is None                # once only, no repeated change
    assert raises(DataStateError, tr.mark_interrupted, D1 + timedelta(minutes=31), "again")
    t2 = DataStateTracker()
    assert t2.observe(D1, None, pol).reason == "NO_DATA"
    assert raises(DataStateError, DataStateTracker().observe, D1, D1 + M5, pol)  # data from the future
    assert raises(ConfigError, DataStateTracker().observe, D1, D1, None)          # no hidden default policy
    assert raises(ConfigError, StalenessPolicy, timedelta(0))


def test_m30_recovery_only_as_implemented():
    """DATA_INTERRUPTED -> DATA_RESUMED is implemented. DATA_RESUMED -> NORMAL is NOT_IMPLEMENTED (the spec does not
    define it): fresh data keeps DATA_RESUMED, and no method returns to NORMAL."""
    tr, pol = DataStateTracker(), StalenessPolicy(timedelta(minutes=10))
    tr.observe(D1 + timedelta(minutes=20), D1, pol)
    ch = tr.observe(D1 + timedelta(minutes=25), D1 + timedelta(minutes=24), pol)
    assert (ch.before, ch.after, ch.reason) == (DataState.DATA_INTERRUPTED, DataState.DATA_RESUMED, "FRESH_DATA")
    assert not tr.new_entries_suspended and tr.resumed_at == D1 + timedelta(minutes=25)
    for k in range(3):
        assert tr.observe(D1 + timedelta(minutes=26 + k), D1 + timedelta(minutes=26 + k), pol) is None
    assert tr.state is DataState.DATA_RESUMED
    assert not [m for m in dir(tr) if "normal" in m.lower()]
    assert raises(DataStateError, tr.mark_resumed, D1 + timedelta(minutes=40), "again")
    assert tr.observe(D1 + timedelta(minutes=50), D1 + timedelta(minutes=29), pol).after is DataState.DATA_INTERRUPTED
    assert [h.after for h in tr.history] == [DataState.DATA_INTERRUPTED, DataState.DATA_RESUMED,
                                             DataState.DATA_INTERRUPTED]


# ------------------------------------------------------------------ calendar behaviour reconciliation (23 Nov 2026)
# Status rule, in priority order: TIMEFRAME_MISSING > SESSION_CALENDAR_MISSING > IRREGULAR_INTERVAL > OK.
# Findings (gaps) are reported in every case; only the status says whether session validity was actually checked.
def _irregular():
    return ser([D1, D1 + timedelta(minutes=7), D1 + timedelta(minutes=12)])


def test_cal1_timeframe_missing_is_unknown():
    for s in (ser([]), ser([D1]), ser(day(D1, 4)), ser([D1, D1 + 3 * M5]), _irregular()):
        for cal in (CAL, CONT, None):
            r = detect_gaps(s, None, cal)
            assert (r.status, r.reason, r.gaps) == (GapReportStatus.UNKNOWN, "TIMEFRAME_MISSING", ()), (len(s), cal)


def test_cal2_calendar_missing_is_always_unknown():
    """A missing calendar never implies that session validity was checked: UNKNOWN even when no gap is found.
    The timestamp findings themselves are still reported (unchanged)."""
    for s in (ser([]), ser([D1]), ser(day(D1, 4))):
        r = detect_gaps(s, M5, None)
        assert (r.status, r.reason, r.gaps) == (GapReportStatus.UNKNOWN, "SESSION_CALENDAR_MISSING", ()), len(s)
    r = detect_gaps(ser([D1, D1 + 3 * M5]), M5, None)
    assert (r.status, r.reason) == (GapReportStatus.UNKNOWN, "SESSION_CALENDAR_MISSING")
    assert [(g.kind, g.slots, g.missing_count) for g in r.gaps] == [(GapKind.UNCLASSIFIED_GAP, 2, None)]
    r = detect_gaps(_irregular(), M5, None)                                # calendar missing outranks irregular
    assert (r.status, r.reason, [g.kind for g in r.gaps]) == \
        (GapReportStatus.UNKNOWN, "SESSION_CALENDAR_MISSING", [GapKind.IRREGULAR_INTERVAL])
    assert not any(g.kind in (GapKind.MISSING_CANDLES, GapKind.SESSION_CLOSURE, GapKind.OUT_OF_SESSION_CANDLE)
                   for g in r.gaps)                                         # no session judgement without a calendar


def test_cal3_calendar_configured_and_classifiable_is_ok():
    for s, cal in ((ser([]), CAL), (ser(day(D1, 12)), CAL), (ser(day(D1, 4)), CONT), (ser([D1]), CAL)):
        r = detect_gaps(s, M5, cal)
        assert (r.status, r.reason, r.gaps) == (GapReportStatus.OK, None, ()), (len(s), cal)
    t = day(D1, 12)                                                        # classified findings keep status OK
    del t[5]
    cases = [(ser(t), CAL, [GapKind.MISSING_CANDLES]), (ser(day(D1, 12) + day(D2, 2)), CAL, [GapKind.SESSION_CLOSURE]),
             (ser([D1 - M5, D1]), CAL, [GapKind.OUT_OF_SESSION_CANDLE]), (ser([D1, D1 + 4 * M5]), CONT,
                                                                       [GapKind.MISSING_CANDLES])]
    for s, cal, kinds in cases:
        r = detect_gaps(s, M5, cal)
        assert (r.status, r.reason, [g.kind for g in r.gaps]) == (GapReportStatus.OK, None, kinds), kinds


def test_cal4_calendar_configured_but_interval_unclassifiable_is_unknown():
    """With a calendar, a spacing that is not a whole multiple of the timeframe (or shorter than it) cannot be
    classified as missing data or session closure: UNKNOWN / IRREGULAR_INTERVAL, with the finding kept."""
    for cal in (CAL, CONT):
        r = detect_gaps(_irregular(), M5, cal)
        assert (r.status, r.reason) == (GapReportStatus.UNKNOWN, "IRREGULAR_INTERVAL"), cal
        assert [(g.kind, g.prev_index, g.index, g.slots) for g in r.gaps] == \
            [(GapKind.IRREGULAR_INTERVAL, 0, 1, None)]                       # 10:07 -> 10:12 is regular
        r = detect_gaps(ser([D1, D1 + timedelta(minutes=3)]), M5, cal)      # shorter than the timeframe
        assert (r.status, r.reason, [g.kind for g in r.gaps]) == \
            (GapReportStatus.UNKNOWN, "IRREGULAR_INTERVAL", [GapKind.IRREGULAR_INTERVAL])
    t = day(D1, 8)                                                         # 10:00..10:35, all inside the session
    del t[5]
    r = detect_gaps(ser(t + [t[-1] + timedelta(minutes=7)]), M5, CAL)      # mixed: classified + unclassifiable (10:42)
    assert (r.status, r.reason, [g.kind for g in r.gaps]) == \
        (GapReportStatus.UNKNOWN, "IRREGULAR_INTERVAL", [GapKind.MISSING_CANDLES, GapKind.IRREGULAR_INTERVAL])


def test_cal5_stream_report_equals_batch_at_every_prefix_with_provenance():
    t = day(D1, 12)
    del t[3]
    plain = [ser([]), ser(t + day(D2 + 2 * M5, 4)), ser([D1, D1 + 4 * M5, D1 + 9 * M5]), ser([D1, D1 + 3 * M5]),
             ser([D1 - M5] + day(D1, 3)), _irregular(), ser(day(D1, 4))]
    rows = [(int(x.timestamp()), 10.0, 11.0, 9.0, 10.5, 1.0) for x in day(D1, 8)]
    rows[2] = (rows[2][0], None, 11.0, 9.0, 10.5, 1.0)                     # invalid source row 2
    del rows[5]                                                            # genuinely absent timestamp
    prov = inspect_chart_json({k: [r[j] for r in rows] for j, k in enumerate("tohlcv")}).partial_series()
    assert prov.source_positions == (0, 1, 3, 4, 5, 6) and [r.source_position for r in prov.invalid_rows] == [2]
    for s in plain + [prov]:
        sp = s.source_positions
        inv = sorted(r.source_position for r in s.invalid_rows)
        for cal in (CAL, CONT, None):
            st = GapStream(M5, cal)
            assert st.report() == detect_gaps(ser([]), M5, cal)              # before any candle
            for k, c in enumerate(s):
                if sp is None:
                    st.on_candle(c)
                else:
                    lo = -1 if k == 0 else sp[k - 1]
                    st.on_candle(c, sp[k], [p for p in inv if lo < p < sp[k]])
                assert st.report() == detect_gaps(s.upto(k), M5, cal), (len(s), cal, k)
    st = GapStream(M5, None)
    assert (st.report().status, st.report().reason) == (GapReportStatus.UNKNOWN, "SESSION_CALENDAR_MISSING")

if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
