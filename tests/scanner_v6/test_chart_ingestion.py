#!/usr/bin/env python3
"""Scanner V6 Module A, chart-JSON ingestion (interim "Option 2", 23 Nov 2026): the LEGACY from_chart_json keeps its
result (the shared fixture still gives 119 candles) but records every skipped row and the source-position mapping;
the STRICT inspect_chart_json / load_chart_json_strict never skip a row silently. Offline; the shared fixture
tests/scanner_v6/fixtures/synthetic_5m.json is only read.

    python tests/scanner_v6/test_chart_ingestion.py   (or: python -m pytest tests/scanner_v6)
"""
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import load_fixture, raises, run_main  # noqa: E402

from scanner_v6.data.candle_models import (Candle, CandleError, CandleSeries, ChartJSONReport,  # noqa: E402
                                           InvalidRow, InvalidRowsError, inspect_chart_json,
                                           load_chart_json_strict, to_utc)
from scanner_v6.data.integrity import GapKind, GapStream, detect_gaps  # noqa: E402
from scanner_v6.data.market_config import SessionCalendar, SessionKind  # noqa: E402

UTC = timezone.utc
M5 = timedelta(minutes=5)
CONT = SessionCalendar(SessionKind.CONTINUOUS, "UTC")      # TEST-ONLY calendar
FX = load_fixture()
BAD = 50                                                    # the fixture's deliberately invalid row (None prices)
T0 = 1763364600                                             # epoch seconds, synthetic


def chart(rows):
    """rows: (t, o, h, l, c, v) -> chart JSON arrays."""
    return {k: [r[j] for r in rows] for j, k in enumerate("tohlcv")}


def good(n, start=T0):
    return [(start + 300 * j, 10.0, 11.0, 9.0, 10.5, 1.0) for j in range(n)]


# ------------------------------------------------------------------ legacy loader (compatibility)
def test_legacy_fixture_still_gives_119_candles():
    s = CandleSeries.from_chart_json(FX, "SYN", "5m")
    assert len(FX["t"]) == 120 and len(s) == 119
    assert [c.index for c in s] == list(range(119))
    assert (s.symbol, s.timeframe) == ("SYN", "5m")


def test_legacy_records_the_skipped_row_explicitly():
    s = CandleSeries.from_chart_json(FX, "SYN", "5m")
    missing = tuple(f for f, k in zip(("open", "high", "low", "close"), "ohlc") if FX[k][BAD] is None)
    assert missing                                                       # the fixture really has a None price there
    assert s.invalid_rows == (InvalidRow(BAD, to_utc(FX["t"][BAD]), FX["t"][BAD], "MISSING_OHLC", missing),)


def test_legacy_source_positions_map_back_to_the_original_rows():
    s = CandleSeries.from_chart_json(FX, "SYN", "5m")
    assert s.source_positions == tuple(range(BAD)) + tuple(range(BAD + 1, 120))
    assert s.source_position(BAD - 1) == BAD - 1 and s.source_position(BAD) == BAD + 1
    for i, c in enumerate(s):
        p = s.source_positions[i]
        assert c.ts == to_utc(FX["t"][p]) and (c.open, c.close) == (FX["o"][p], FX["c"][p])
    assert raises(IndexError, s.source_position, 119)


def test_prefix_keeps_provenance_without_look_ahead():
    s = CandleSeries.from_chart_json(FX, "SYN", "5m")
    assert s.upto(BAD - 1).invalid_rows == ()                            # row 50 is not known at candle 49
    assert [r.source_position for r in s.upto(BAD).invalid_rows] == [BAD]  # candle 50 = source row 51
    assert s.upto(BAD).source_positions == s.source_positions[:BAD + 1]


def test_replay_audit_assumptions_still_hold():
    # tests/scanner_v6/test_replay_audit.py (staged, untouched) uses this exact call and indexes S[i] up to 92.
    s = CandleSeries.from_chart_json(FX, "SYN", "5m")
    assert len(s) == 119 and s[92].index == 92 and s[50].ts == to_utc(FX["t"][51])


# ------------------------------------------------------------------ strict inspection
def test_strict_reports_and_rejects_the_fixture():
    rep = inspect_chart_json(FX)
    assert isinstance(rep, ChartJSONReport) and not rep.is_complete and rep.total_rows == 120
    assert [r.source_position for r in rep.invalid_rows] == [BAD]
    assert not hasattr(rep, "series")                                    # no ambiguous accessor
    try:
        load_chart_json_strict(FX, "SYN", "5m")
        raise AssertionError("strict loader returned a series for an input with an invalid row")
    except InvalidRowsError as e:
        assert e.total_rows == 120 and [r.source_position for r in e.invalid_rows] == [BAD]
        assert "row 50" in str(e) and "MISSING_OHLC" in str(e)
    assert raises(InvalidRowsError, rep.complete_series)


def test_missing_ohlc_fields_identified():
    rows = good(4)
    rows[1] = (rows[1][0], 10.0, None, 9.0, 10.5, 1.0)
    rows[2] = (rows[2][0], None, 11.0, 9.0, None, 1.0)
    rep = inspect_chart_json(chart(rows))
    assert [(r.source_position, r.reason, r.fields) for r in rep.invalid_rows] == [
        (1, "MISSING_OHLC", ("high",)), (2, "MISSING_OHLC", ("open", "close"))]
    assert [r.ts for r in rep.invalid_rows] == [to_utc(rows[1][0]), to_utc(rows[2][0])]   # timestamps kept


def test_invalid_values_and_rows_classified():
    t = [T0 + 300 * j for j in range(12)]
    rows = [(t[0], 10, 11, 9, 10.5, 1),
            (t[1], math.nan, 11, 9, 10.5, 1),            # INVALID_OHLC_VALUE
            (t[2], 10, math.inf, 9, 10.5, 1),            # INVALID_OHLC_VALUE
            (t[3], "10", 11, 9, True, 1),                # INVALID_OHLC_VALUE (string, bool)
            (t[4], 10, 9.5, 9, 10.5, 1),                 # INCONSISTENT_OHLC (high < close)
            (t[5], 10, 11, 9, 10.5, -1),                 # INVALID_VOLUME
            (t[6], 10, 11, 9, 10.5, math.nan),           # INVALID_VOLUME
            (None, 10, 11, 9, 10.5, 1),                  # MISSING_TIMESTAMP
            ("2026-11-17", 10, 11, 9, 10.5, 1),          # INVALID_TIMESTAMP (not epoch / aware datetime)
            (t[0], 10, 11, 9, 10.5, 1),                  # NON_INCREASING_TIMESTAMP (duplicate of row 0)
            (None, None, 11, 9, 10.5, 1),                # MISSING_TIMESTAMP wins; fields list both problems
            (t[11], 10, 11, 9, 10.5, 1)]
    rep = inspect_chart_json(chart(rows))
    got = [(r.source_position, r.reason, r.fields) for r in rep.invalid_rows]
    assert got == [(1, "INVALID_OHLC_VALUE", ("open",)), (2, "INVALID_OHLC_VALUE", ("high",)),
                   (3, "INVALID_OHLC_VALUE", ("open", "close")), (4, "INCONSISTENT_OHLC", ("open", "high", "low", "close")),
                   (5, "INVALID_VOLUME", ("volume",)), (6, "INVALID_VOLUME", ("volume",)),
                   (7, "MISSING_TIMESTAMP", ("timestamp",)), (8, "INVALID_TIMESTAMP", ("timestamp",)),
                   (9, "NON_INCREASING_TIMESTAMP", ("timestamp",)), (10, "MISSING_TIMESTAMP", ("timestamp", "open"))], got
    assert rep.invalid_rows[7].ts is None and rep.invalid_rows[7].raw_ts == "2026-11-17"   # raw value kept
    assert rep.valid_positions == (0, 11)
    naive = inspect_chart_json(chart([(datetime(2026, 11, 17, 10), 10, 11, 9, 10.5, 1)]))
    assert [r.reason for r in naive.invalid_rows] == ["INVALID_TIMESTAMP"]


def test_strict_preserves_source_positions_and_fabricates_nothing():
    rows = good(6)
    rows[2] = (rows[2][0], None, None, None, None, None)
    rep = inspect_chart_json(chart(rows))
    p = rep.partial_series("TEST", "5m")
    assert p.source_positions == (0, 1, 3, 4, 5) and len(p) == 5 == rep.total_rows - len(rep.invalid_rows)
    assert [c.index for c in p] == [0, 1, 2, 3, 4]
    assert to_utc(rows[2][0]) not in [c.ts for c in p]                   # no candle for the invalid row
    assert [r.source_position for r in p.invalid_rows] == [2]
    (g,) = detect_gaps(p, M5, CONT).gaps                                 # the hole is reported, not filled
    assert (g.kind, g.prev_index, g.index, g.missing_count, g.skipped_source_rows) == \
        (GapKind.MISSING_CANDLES, 1, 2, 1, 1)


def test_valid_input_complete_and_deterministic():
    d = chart(good(5))
    a, b = load_chart_json_strict(d, "TEST", "5m"), load_chart_json_strict(d, "TEST", "5m")
    assert [tuple(vars(c).values()) for c in a] == [tuple(vars(c).values()) for c in b]
    assert a.source_positions == (0, 1, 2, 3, 4) and a.invalid_rows == ()
    assert inspect_chart_json(d) == inspect_chart_json(d) and inspect_chart_json(d).is_complete
    assert [c.close for c in a] == [r[4] for r in good(5)]               # values unchanged


def test_strict_structural_errors():
    assert raises(CandleError, inspect_chart_json, {"t": [T0], "o": [1], "h": [1], "l": [1]})          # no "c"
    assert raises(CandleError, inspect_chart_json, {"t": [T0, T0 + 300], "o": [1], "h": [1, 1], "l": [1, 1],
                                                    "c": [1, 1]})                                       # length
    assert raises(CandleError, inspect_chart_json, {"t": [T0], "o": [1], "h": [1], "l": [1], "c": [1],
                                                    "v": [1, 2]})                                       # v length
    assert raises(CandleError, inspect_chart_json, [])


# ------------------------------------------------------------------ invalid row vs genuine gap
def test_invalid_rows_are_told_apart_from_genuine_gaps():
    legacy = CandleSeries.from_chart_json(FX, "SYN", "5m")
    (g,) = detect_gaps(legacy, M5, CONT).gaps
    assert (g.prev_index, g.index, g.skipped_source_rows) == (BAD - 1, BAD, 1)          # caused by invalid row 50
    genuine = load_chart_json_strict(chart(good(2) + good(2, T0 + 300 * 4)), "TEST", "5m")  # source has no rows there
    (g,) = detect_gaps(genuine, M5, CONT).gaps
    assert (g.missing_count, g.skipped_source_rows) == (2, 0)
    plain = CandleSeries([Candle(0, to_utc(T0), 10, 11, 9, 10.5), Candle(1, to_utc(T0 + 900), 10, 11, 9, 10.5)])
    (g,) = detect_gaps(plain, M5, CONT).gaps
    assert g.skipped_source_rows is None                                                # provenance unknown


def _stream_full_provenance(s, cal=CONT):
    """Feed s to a GapStream with complete provenance: each candle's source row plus the recorded invalid rows
    since the previous candle."""
    st, out, prev = GapStream(M5, cal), [], -1
    for i, c in enumerate(s):
        p = s.source_positions[i]
        inv = [r.source_position for r in s.invalid_rows if prev < r.source_position < p]
        out.extend(st.on_candle(c, p, inv))
        prev = p
    return tuple(out)


def test_gap_stream_parity_with_source_positions():
    legacy = CandleSeries.from_chart_json(FX, "SYN", "5m")
    assert _stream_full_provenance(legacy) == detect_gaps(legacy, M5, CONT).gaps
    st2 = GapStream(M5, CONT)
    st2.on_candle(legacy[0], 0)
    assert raises(ValueError, st2.on_candle, legacy[1])                                 # all-or-nothing
    st3 = GapStream(M5, CONT)
    st3.on_candle(legacy[0], 5)
    assert raises(ValueError, st3.on_candle, legacy[1], 5)                              # must increase


def test_series_provenance_validation():
    cs = [Candle(i, to_utc(T0 + 300 * i), 10, 11, 9, 10.5) for i in range(3)]
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 1))
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 2, 2))
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, True, 3))
    r = InvalidRow(1, None, None, "MISSING_TIMESTAMP", ("timestamp",))
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 1, 2), invalid_rows=(r,))
    assert raises(CandleError, CandleSeries, cs, invalid_rows=("row 1",))
    assert raises(CandleError, InvalidRow, -1, None, None, "MISSING_OHLC", ())
    assert raises(CandleError, InvalidRow, 0, None, None, "SOMETHING_ELSE", ())
    assert CandleSeries(cs).source_positions is None and CandleSeries(cs).invalid_rows == ()


# ------------------------------------------------------------------ review fix 1: upto() provenance
def test_fix1_invalid_rows_need_provenance_and_upto_leaks_nothing():
    cs = [Candle(i, to_utc(T0 + 300 * i), 10, 11, 9, 10.5) for i in range(3)]
    future = InvalidRow(7, to_utc(T0 + 300 * 7), T0 + 300 * 7, "MISSING_OHLC", ("open",))
    assert raises(CandleError, CandleSeries, cs, invalid_rows=(future,))   # cannot attach rows without positions
    plain = CandleSeries(cs)
    assert not plain.provenance_known
    for k in range(3):
        p = plain.upto(k)
        assert (p.source_positions, p.invalid_rows, p.provenance_known) == (None, (), False)
    rows = good(5)
    rows[4] = (rows[4][0], None, 11.0, 9.0, 10.5, 1.0)                    # invalid row AFTER the last candle
    s = inspect_chart_json(chart(rows)).partial_series()
    assert s.provenance_known and [r.source_position for r in s.invalid_rows] == [4]
    assert s.upto(3).invalid_rows == ()                                  # not known at candle 3's close
    assert s.upto(3).source_positions == (0, 1, 2, 3)


# ------------------------------------------------------------------ review fix 2: source timestamp order
def test_fix2_invalid_ohlc_row_still_takes_part_in_timestamp_order():
    d = chart([(100, 10.0, 11.0, 9.0, 10.5, 1.0),
               (200, 10.0, None, 9.0, 10.5, 1.0),        # valid timestamp, invalid OHLC
               (150, 10.0, 11.0, 9.0, 10.5, 1.0)])       # otherwise valid, but earlier than row 1
    rep = inspect_chart_json(d)
    assert [(r.source_position, r.reason, r.fields) for r in rep.invalid_rows] == [
        (1, "MISSING_OHLC", ("high",)), (2, "NON_INCREASING_TIMESTAMP", ("timestamp",))]
    assert rep.valid_positions == (0,) and not rep.is_complete
    assert rep.invalid_rows[1].ts == to_utc(150)
    assert raises(InvalidRowsError, load_chart_json_strict, d)


def test_fix2_order_is_against_the_highest_source_timestamp():
    d = chart([(100, 10, 11, 9, 10.5, 1), (300, 10, 11, 9, 10.5, 1),
               (200, 10, 11, 9, 10.5, 1),               # before 300
               (250, 10, 11, 9, 10.5, 1),               # after row 2 but still before 300
               (220, None, 11, 9, 10.5, 1),             # OHLC problem AND out of order: reason kept, field added
               (400, 10, 11, 9, 10.5, 1)])
    rep = inspect_chart_json(d)
    assert [(r.source_position, r.reason, r.fields) for r in rep.invalid_rows] == [
        (2, "NON_INCREASING_TIMESTAMP", ("timestamp",)), (3, "NON_INCREASING_TIMESTAMP", ("timestamp",)),
        (4, "MISSING_OHLC", ("timestamp", "open"))]
    p = rep.partial_series()
    assert p.source_positions == (0, 1, 5) and [c.ts for c in p] == [to_utc(100), to_utc(300), to_utc(400)]
    assert inspect_chart_json(d) == rep                                  # deterministic


# ------------------------------------------------------------------ review fix 3: explicit empty volume array
def test_fix3_explicit_empty_volume_array_is_a_length_mismatch():
    base = chart(good(2))
    assert raises(CandleError, inspect_chart_json, dict(base, v=[]))
    assert raises(CandleError, load_chart_json_strict, dict(base, v=[]))
    no_v = {k: base[k] for k in "tohlc"}
    assert [c.volume for c in load_chart_json_strict(no_v)] == [0.0, 0.0]          # missing array: default kept
    assert [c.volume for c in load_chart_json_strict(dict(base, v=None))] == [0.0, 0.0]
    assert [c.volume for c in load_chart_json_strict(dict(base, v=[None, 2]))] == [0.0, 2.0]  # None -> 0.0 kept
    assert load_chart_json_strict({"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}).invalid_rows == ()
    legacy = CandleSeries.from_chart_json(dict(base, v=[]))             # legacy compatibility unchanged
    assert [c.volume for c in legacy] == [0.0, 0.0]


# ------------------------------------------------------------------ review fix 4: invalid-row provenance
def test_fix4_invalid_row_provenance_rules():
    cs = [Candle(i, to_utc(T0 + 300 * i), 10, 11, 9, 10.5) for i in range(3)]

    def bad(p):
        return InvalidRow(p, None, None, "MISSING_TIMESTAMP", ("timestamp",))

    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 2, 3), invalid_rows=(bad(1), bad(1)))
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 3, 4), invalid_rows=(bad(2), bad(1)))
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 2, 3), invalid_rows=(bad(2),))     # overlap
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 2, 3))                             # row 1?
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 3, 4), invalid_rows=(bad(1),))     # row 2?
    ok = CandleSeries(cs, source_positions=(1, 3, 4), invalid_rows=(bad(0), bad(2), bad(5)))
    assert ok.provenance_known and [r.source_position for r in ok.invalid_rows] == [0, 2, 5]


def test_fix4_skipped_source_rows_meaning():
    rows = good(6)
    rows[2] = (rows[2][0], None, 11.0, 9.0, 10.5, 1.0)
    rows[3] = (rows[3][0], 10.0, 11.0, None, 10.5, 1.0)
    p = inspect_chart_json(chart(rows)).partial_series()
    (g,) = detect_gaps(p, M5, CONT).gaps
    between = [r.source_position for r in p.invalid_rows
               if p.source_positions[g.prev_index] < r.source_position < p.source_positions[g.index]]
    assert g.skipped_source_rows == 2 == len(between)                   # > 0: every skipped row accounted for
    genuine = load_chart_json_strict(chart(good(2) + good(1, T0 + 300 * 5)))
    assert detect_gaps(genuine, M5, CONT).gaps[0].skipped_source_rows == 0   # 0: nothing skipped
    plain = CandleSeries(list(genuine))
    assert detect_gaps(plain, M5, CONT).gaps[0].skipped_source_rows is None  # None: provenance unknown


# ------------------------------------------------------------------ GapStream provenance (final review fix)
def _gaps_skipped(gaps):
    return [(g.prev_index, g.index, g.skipped_source_rows) for g in gaps]


def test_stream_genuine_missing_source_rows_is_zero():
    s = load_chart_json_strict(chart(good(2) + good(2, T0 + 300 * 5)))      # adjacent source rows, time gap
    st = GapStream(M5, CONT)
    gaps = [g for i, c in enumerate(s) for g in st.on_candle(c, s.source_positions[i])]
    assert _gaps_skipped(gaps) == [(1, 2, 0)] == _gaps_skipped(detect_gaps(s, M5, CONT).gaps)


def test_stream_recorded_invalid_rows_are_counted():
    rows = good(6)
    rows[2] = (rows[2][0], None, 11.0, 9.0, 10.5, 1.0)
    rows[3] = (rows[3][0], 10.0, 11.0, None, 10.5, 1.0)
    p = inspect_chart_json(chart(rows)).partial_series()
    st = GapStream(M5, CONT)
    st.on_candle(p[0], 0, [])
    st.on_candle(p[1], 1, ())
    (g,) = st.on_candle(p[2], 4, [2, 3])
    assert (g.missing_count, g.skipped_source_rows) == (2, 2)


def test_stream_position_difference_alone_is_not_an_invalid_row_count():
    legacy = CandleSeries.from_chart_json(FX, "SYN", "5m")                  # source row 50 is invalid
    st = GapStream(M5, CONT)
    gaps = [g for i, c in enumerate(legacy) for g in st.on_candle(c, legacy.source_positions[i])]
    assert _gaps_skipped(gaps) == [(BAD - 1, BAD, None)]                   # unverified: None, not 1
    assert _gaps_skipped(detect_gaps(legacy, M5, CONT).gaps) == [(BAD - 1, BAD, 1)]   # batch has the records


def test_stream_unknown_provenance_is_none():
    legacy = CandleSeries.from_chart_json(FX, "SYN", "5m")
    st = GapStream(M5, CONT)
    gaps = [g for c in legacy for g in st.on_candle(c)]                    # existing call shape still works
    assert _gaps_skipped(gaps) == [(BAD - 1, BAD, None)]
    plain = CandleSeries(list(legacy))
    assert _gaps_skipped(detect_gaps(plain, M5, CONT).gaps) == [(BAD - 1, BAD, None)]


def test_stream_batch_parity_with_complete_provenance():
    rows = good(10)
    rows[0] = (rows[0][0], None, 11.0, 9.0, 10.5, 1.0)                     # before the first candle
    rows[3] = (rows[3][0], 10.0, 11.0, None, 10.5, 1.0)
    rows[6] = (rows[6][0], 10.0, 9.5, 9.0, 10.5, 1.0)
    rows[7] = (rows[7][0], 10.0, 11.0, 9.0, 10.5, -1.0)
    p = inspect_chart_json(chart(rows + good(2, T0 + 300 * 13)))           # plus a genuine time gap
    s = p.partial_series()
    batch = detect_gaps(s, M5, CONT).gaps
    assert _stream_full_provenance(s) == batch
    assert _gaps_skipped(batch) == [(1, 2, 1), (3, 4, 2), (5, 6, 0)]


def test_stream_incomplete_or_inconsistent_provenance_rejected():
    rows = good(6)
    rows[2] = (rows[2][0], None, 11.0, 9.0, 10.5, 1.0)
    rows[3] = (rows[3][0], 10.0, 11.0, None, 10.5, 1.0)
    p = inspect_chart_json(chart(rows)).partial_series()

    def fresh():
        st = GapStream(M5, CONT)
        st.on_candle(p[0], 0)
        st.on_candle(p[1], 1)
        return st

    for inv in ([2], [3], [], [3, 2], [2, 2, 3], [1, 2, 3], [2, 3, 4], [2, True]):
        assert raises(ValueError, fresh().on_candle, p[2], 4, inv), inv     # incomplete / wrong / out of range
    assert raises(ValueError, GapStream(M5, CONT).on_candle, p[0], None, [])   # needs source_position
    st = GapStream(M5, CONT)
    st.on_candle(p[0], 2, [0, 1])                                          # rows before the first candle: allowed
    assert raises(ValueError, GapStream(M5, CONT).on_candle, p[0], 2, [2])  # not before the candle's own row
    assert (fresh().on_candle(p[2], 4)[0].skipped_source_rows) is None    # omitted -> unverified -> None


# ------------------------------------------------------------------ X03: legacy loader, short volume array
def test_x03_three_rows_two_volumes_records_the_cut_off_row():
    d = chart(good(3))
    d["v"] = [1.0, 2.0]                                                  # non-empty, shorter than t
    s = CandleSeries.from_chart_json(d, "TEST", "5m")
    assert len(s) == 2 and [c.volume for c in s] == [1.0, 2.0]           # legacy candles unchanged
    assert s.source_positions == (0, 1)
    assert s.invalid_rows == (InvalidRow(2, to_utc(d["t"][2]), d["t"][2], "VOLUME_ARRAY_TRUNCATED", ("volume",)),)
    assert raises(CandleError, load_chart_json_strict, d)                # strict still rejects
    assert raises(CandleError, inspect_chart_json, d)


def test_x03_multiple_trailing_rows_with_a_skipped_row_inside():
    rows = good(7)
    rows[1] = (rows[1][0], None, 11.0, 9.0, 10.5, 1.0)                   # MISSING_OHLC between candles
    rows[5] = (rows[5][0], 10.0, None, 9.0, 10.5, 1.0)                   # also beyond the volume array
    d = chart(rows)
    d["v"] = [1.0, 1.0, 2.0, 3.0]                                        # rows 4, 5, 6 have no volume value
    s = CandleSeries.from_chart_json(d, "TEST", "5m")
    assert s.source_positions == (0, 2, 3) and [c.volume for c in s] == [1.0, 2.0, 3.0]
    assert [(r.source_position, r.reason, r.fields) for r in s.invalid_rows] == [
        (1, "MISSING_OHLC", ("open",)), (4, "VOLUME_ARRAY_TRUNCATED", ("volume",)),
        (5, "MISSING_OHLC", ("high", "volume")), (6, "VOLUME_ARRAY_TRUNCATED", ("volume",))]
    assert [r.ts for r in s.invalid_rows] == [to_utc(d["t"][p]) for p in (1, 4, 5, 6)]
    assert [(g.prev_index, g.index, g.skipped_source_rows) for g in detect_gaps(s, M5, CONT).gaps] == [(0, 1, 1)]
    rebuilt = CandleSeries(list(s), source_positions=s.source_positions, invalid_rows=s.invalid_rows)
    assert rebuilt.invalid_rows == s.invalid_rows                         # provenance validation accepts the record
    assert s.upto(2).invalid_rows == s.invalid_rows[:1]                    # trailing rows not known at candle 2
    assert raises(CandleError, load_chart_json_strict, d)


def test_x03_truncated_rows_follow_the_reason_priority():
    t = [T0 + 300 * j for j in range(9)]
    rows = [(t[0], 10, 11, 9, 10.5), (t[1], 10, 11, 9, 10.5),            # rows 0-1: have volume values
            ("bad-ts", 10, 11, 9, 10.5),                                  # 2: invalid timestamp
            (None, 10, 11, 9, 10.5),                                      # 3: missing timestamp
            (t[4], math.nan, 11, 9, math.inf),                            # 4: NaN / Inf OHLC
            (t[5], 10, 9, 11, 10),                                        # 5: inconsistent OHLC (high < low)
            (t[6], 10, None, 9, None),                                    # 6: missing OHLC and volume
            (t[7], 10, 11, 9, 10.5),                                      # 7: otherwise valid
            (t[1], 10, 11, 9, 10.5)]                                      # 8: timestamp not after earlier rows
    d = {k: [r[j] for r in rows] for j, k in enumerate("tohlc")}
    d["v"] = [1.0, 2.0]
    s = CandleSeries.from_chart_json(d, "TEST", "5m")
    assert len(s) == 2 and s.source_positions == (0, 1) and [c.volume for c in s] == [1.0, 2.0]
    assert [(r.source_position, r.reason, r.fields) for r in s.invalid_rows] == [
        (2, "INVALID_TIMESTAMP", ("timestamp", "volume")),
        (3, "MISSING_TIMESTAMP", ("timestamp", "volume")),
        (4, "INVALID_OHLC_VALUE", ("open", "close", "volume")),
        (5, "VOLUME_ARRAY_TRUNCATED", ("volume", "open", "high", "low", "close")),
        (6, "MISSING_OHLC", ("high", "close", "volume")),
        (7, "VOLUME_ARRAY_TRUNCATED", ("volume",)),
        (8, "VOLUME_ARRAY_TRUNCATED", ("timestamp", "volume"))]
    assert [(r.ts, r.raw_ts) for r in s.invalid_rows[:2]] == [(None, "bad-ts"), (None, None)]   # raw values kept
    assert s.invalid_rows[2].ts == to_utc(t[4]) and s.invalid_rows[6].ts == to_utc(t[1])
    rebuilt = CandleSeries(list(s), source_positions=s.source_positions, invalid_rows=s.invalid_rows)
    assert rebuilt.invalid_rows == s.invalid_rows                         # provenance validation unchanged, accepts
    assert raises(CandleError, load_chart_json_strict, d)                # strict still rejects (length mismatch)
    assert detect_gaps(s, M5, CONT).gaps == ()                           # trailing rows never form a gap


def test_x03_unchanged_volume_conventions():
    base = chart(good(3))
    assert [c.volume for c in CandleSeries.from_chart_json(dict(base, v=None))] == [0.0, 0.0, 0.0]
    assert [c.volume for c in CandleSeries.from_chart_json(dict(base, v=[None, 2, None]))] == [0.0, 2.0, 0.0]
    empty = CandleSeries.from_chart_json(dict(base, v=[]))                # explicit [] keeps legacy behaviour
    assert len(empty) == 3 and empty.invalid_rows == () and [c.volume for c in empty] == [0.0, 0.0, 0.0]
    assert raises(CandleError, load_chart_json_strict, dict(base, v=[]))
    fx = CandleSeries.from_chart_json(FX, "SYN", "5m")
    assert len(fx) == 119 and [r.source_position for r in fx.invalid_rows] == [BAD]
    assert [r.reason for r in fx.invalid_rows] == ["MISSING_OHLC"]


def test_x03_longer_volume_array_is_a_documented_limitation():
    d = chart(good(2))
    d["v"] = [1.0, 2.0, 99.0]                                            # extra value has no source row
    s = CandleSeries.from_chart_json(d)
    assert len(s) == 2 and [c.volume for c in s] == [1.0, 2.0]           # established behaviour kept
    assert s.invalid_rows == () and s.source_positions == (0, 1)        # nothing invented for it
    assert raises(CandleError, load_chart_json_strict, d)                # strict rejects


# ------------------------------------------------------------------ known limitation, pinned (not changed)
def test_known_limitation_volume_none_becomes_zero():
    rows = good(2)
    rows[1] = rows[1][:5] + (None,)
    d = chart(rows)
    assert load_chart_json_strict(d)[1].volume == 0.0                   # documented limitation: None -> 0.0
    assert CandleSeries.from_chart_json(d)[1].volume == 0.0
    assert CandleSeries.from_rows([r for r in rows])[1].volume == 0.0



# ------------------------------------------------------------------ stabilization: adversarial matrix (23 Nov 2026)
# Case numbers M01..M25 follow the stabilization task's test matrix; D1..D3 are the defects reproduced there.
def reasons(d):
    return [(r.source_position, r.reason) for r in inspect_chart_json(d).invalid_rows]


def with_row(j, n=4, **vals):
    rows = [list(r) for r in good(n)]
    for k, v in vals.items():
        rows[j]["tohlcv".index(k)] = v
    return chart([tuple(r) for r in rows])


def test_m01_valid_continuous_series():
    d = chart(good(5))
    rep = inspect_chart_json(d)
    assert rep.is_complete and rep.valid_positions == (0, 1, 2, 3, 4) and rep.invalid_rows == ()
    s = load_chart_json_strict(d, "SYN", "5m")
    assert len(s) == 5 and s.source_positions == (0, 1, 2, 3, 4) and s.invalid_rows == ()
    assert [c.index for c in s] == [0, 1, 2, 3, 4] and detect_gaps(s, M5, CONT).gaps == ()


def test_m02_missing_ohlc_field():
    d = with_row(1, h=None)
    assert reasons(d) == [(1, "MISSING_OHLC")] and inspect_chart_json(d).invalid_rows[0].fields == ("high",)
    assert raises(InvalidRowsError, load_chart_json_strict, d)
    leg = CandleSeries.from_chart_json(d)                    # legacy: skipped AND recorded
    assert len(leg) == 3 and leg.source_positions == (0, 2, 3) and leg.invalid_rows[0].reason == "MISSING_OHLC"


def test_m03_nan_and_infinities():
    for bad in (math.nan, math.inf, -math.inf):
        for f in "ohlc":
            r = inspect_chart_json(with_row(2, **{f: bad})).invalid_rows
            assert [(x.source_position, x.reason) for x in r] == [(2, "INVALID_OHLC_VALUE")], (f, bad)
        assert raises(CandleError, Candle, 0, T0, bad, 11, 9, 10)


def test_m04_m05_m06_inconsistent_ohlc():
    cases = {"high below open": dict(o=12.0), "high below close": dict(c=12.0), "low above open": dict(o=8.0, l=8.5),
             "low above close": dict(c=8.0, l=8.5), "high below low": dict(h=8.0, l=9.0)}
    for name, vals in cases.items():
        r = inspect_chart_json(with_row(1, **vals)).invalid_rows
        assert [(x.source_position, x.reason, x.fields) for x in r] == \
            [(1, "INCONSISTENT_OHLC", ("open", "high", "low", "close"))], name


def test_m07_zero_range_candle_is_valid():
    d = with_row(1, o=10.0, h=10.0, l=10.0, c=10.0)
    s = load_chart_json_strict(d)
    assert len(s) == 4 and s[1].range == 0.0


def test_m08_m09_missing_and_invalid_timestamps():
    assert reasons(with_row(1, t=None)) == [(1, "MISSING_TIMESTAMP")]
    for bad in ("2026-11-17T10:00:00Z", math.nan, math.inf, True, [1]):
        r = inspect_chart_json(with_row(1, t=bad)).invalid_rows
        assert [(x.source_position, x.reason, x.ts) for x in r] == [(1, "INVALID_TIMESTAMP", None)], bad


def test_d1_out_of_range_timestamps_are_invalid_rows_not_crashes():
    """D1 (reproduced 23 Nov 2026): an epoch value outside the platform's datetime range raised OverflowError out of
    to_utc, so the strict loader crashed instead of reporting the row. It is now INVALID_TIMESTAMP / CandleError."""
    for bad in (1e20, -1e20, 10 ** 400):
        assert raises(CandleError, to_utc, bad), bad
        r = inspect_chart_json(with_row(1, t=bad)).invalid_rows
        assert [(x.source_position, x.reason, x.ts, x.raw_ts) for x in r] == [(1, "INVALID_TIMESTAMP", None, bad)]
        assert raises(InvalidRowsError, load_chart_json_strict, with_row(1, t=bad))
        assert raises(CandleError, CandleSeries.from_chart_json, with_row(1, t=bad))   # legacy: CandleError, as before


def test_d2_numbers_beyond_float_range_are_invalid_not_crashes():
    """D2 (reproduced): an int too large for a float (e.g. a 400-digit JSON integer) raised OverflowError from
    math.isfinite. It is now INVALID_OHLC_VALUE / INVALID_VOLUME in the strict loader and CandleError in Candle."""
    huge = 10 ** 400
    for f in "ohlc":
        assert reasons(with_row(1, **{f: huge})) == [(1, "INVALID_OHLC_VALUE")], f
    assert reasons(with_row(1, v=huge)) == [(1, "INVALID_VOLUME")]
    assert raises(CandleError, Candle, 0, T0, huge, huge, 1, 1)
    assert raises(CandleError, Candle, 0, T0, 10, 11, 9, 10, huge)
    assert len(load_chart_json_strict(with_row(1, o=10, h=11, l=9, c=10, v=10 ** 15))) == 4   # big but finite: fine


def test_d3_strict_arrays_must_be_real_sequences():
    """D3 (reproduced): a non-sequence array raised TypeError (the docstring promises CandleError); a str array was
    read character by character; a dict was read by its KEYS as prices. Each is now a structural CandleError."""
    for k in "tohlcv":
        for bad in (5, "abcd", {0: 1, 1: 2, 2: 3, 3: 4}, b"abcd"):
            d = chart(good(4))
            d[k] = bad
            assert raises(CandleError, inspect_chart_json, d), (k, bad)
            assert raises(CandleError, load_chart_json_strict, d), (k, bad)
    d = chart(good(4))
    d.update({k: tuple(v) for k, v in d.items()})              # tuples are sequences: accepted
    assert inspect_chart_json(d).is_complete


def test_m10_m11_duplicate_and_out_of_order_timestamps():
    d = with_row(2, t=T0 + 300)                                # duplicate of row 1
    assert reasons(d) == [(2, "NON_INCREASING_TIMESTAMP")]
    d = with_row(2, t=T0 - 300)                                # older than every earlier row
    assert reasons(d) == [(2, "NON_INCREASING_TIMESTAMP")]
    s = inspect_chart_json(d).partial_series()
    assert s.source_positions == (0, 1, 3) and [r.source_position for r in s.invalid_rows] == [2]


def test_m12_to_m15_volume_arrays():
    d = chart(good(3)); del d["v"]                             # M12 missing: documented all-zero policy
    assert [c.volume for c in load_chart_json_strict(d)] == [0.0, 0.0, 0.0]
    for vols in ([], [1.0, 1.0], [1.0] * 4):                   # M13 empty, M14 shorter, M15 longer
        d = chart(good(3)); d["v"] = vols
        assert raises(CandleError, inspect_chart_json, d) and raises(CandleError, load_chart_json_strict, d), vols
    d = chart(good(3)); d["v"] = [1.0, 1.0]                    # legacy: shorter -> recorded (X03)
    leg = CandleSeries.from_chart_json(d)
    assert len(leg) == 2 and [(r.source_position, r.reason) for r in leg.invalid_rows] == [(2, "VOLUME_ARRAY_TRUNCATED")]
    d = chart(good(3)); d["v"] = [1.0] * 4                     # legacy: longer -> extra value ignored (documented)
    assert len(CandleSeries.from_chart_json(d)) == 3


def test_m16_multiple_invalid_rows_all_reported_in_source_order():
    rows = [list(r) for r in good(8)]
    rows[1][2] = None; rows[3][0] = "bad"; rows[4][1] = math.nan; rows[6][0] = rows[5][0]
    d = chart([tuple(r) for r in rows])
    assert reasons(d) == [(1, "MISSING_OHLC"), (3, "INVALID_TIMESTAMP"), (4, "INVALID_OHLC_VALUE"),
                          (6, "NON_INCREASING_TIMESTAMP")]
    try:
        load_chart_json_strict(d)
        assert False
    except InvalidRowsError as e:
        assert [r.source_position for r in e.invalid_rows] == [1, 3, 4, 6] and e.total_rows == 8
    rep = inspect_chart_json(d)
    assert sorted(rep.valid_positions + tuple(r.source_position for r in rep.invalid_rows)) == list(range(8))


def test_m17_m18_invalid_ohlc_with_parseable_or_invalid_timestamp():
    r = inspect_chart_json(with_row(1, h=8.0)).invalid_rows[0]                  # M17
    assert r.reason == "INCONSISTENT_OHLC" and r.ts == to_utc(T0 + 300) and r.raw_ts == T0 + 300
    r = inspect_chart_json(with_row(1, t="x", h=None)).invalid_rows[0]          # M18
    assert r.reason == "INVALID_TIMESTAMP" and r.ts is None and r.fields == ("timestamp", "high")


def test_m19_source_position_gaps_vs_genuine_missing_candles():
    rows = good(6)
    rows = [rows[0], (rows[1][0], None, 11.0, 9.0, 10.5, 1.0), rows[2], rows[4], rows[5]]   # row 1 invalid; t[3] absent
    s = inspect_chart_json(chart(rows)).partial_series()
    assert s.source_positions == (0, 2, 3, 4)
    g = detect_gaps(s, M5, CONT).gaps
    assert [(x.prev_index, x.index, x.slots, x.skipped_source_rows) for x in g] == [(0, 1, 1, 1), (1, 2, 1, 0)]


def test_m20_unknown_provenance():
    s = CandleSeries.from_rows([(T0, 10, 11, 9, 10), (T0 + 900, 10, 11, 9, 10)])
    assert not s.provenance_known and s.source_position(1) is None
    assert [x.skipped_source_rows for x in detect_gaps(s, M5, CONT).gaps] == [None]
    assert raises(CandleError, CandleSeries, list(s), invalid_rows=(InvalidRow(1, None, "x", "INVALID_TIMESTAMP",
                                                                                   ("timestamp",)),))


def test_m21_upto_at_boundaries():
    rows = good(6)
    rows = [(rows[0][0], None, 11.0, 9.0, 10.5, 1.0)] + rows[1:3] + [(rows[3][0], 10.0, 8.0, 9.0, 10.0, 1.0)] + rows[4:] + \
        [(T0 + 300 * 6, None, 1, 1, 1, 1)]                     # invalid rows at 0 (leading), 3 (inside), 6 (trailing)
    s = inspect_chart_json(chart(rows)).partial_series()
    assert s.source_positions == (1, 2, 4, 5) and [r.source_position for r in s.invalid_rows] == [0, 3, 6]
    expect = {0: ((1,), [0]), 1: ((1, 2), [0]), 2: ((1, 2, 4), [0, 3]), 3: ((1, 2, 4, 5), [0, 3])}
    for k, (sp, inv) in expect.items():
        p = s.upto(k)
        assert len(p) == k + 1 and p.source_positions == sp and [r.source_position for r in p.invalid_rows] == inv, k
        assert [c for c in p] == [s[i] for i in range(k + 1)]
    for k in (-1, 4):
        assert raises(IndexError, s.upto, k)
    # documented: upto(k) holds what was known at candle k's close, so the trailing invalid row 6 is not in upto(3)
    assert 6 in [r.source_position for r in s.invalid_rows] and 6 not in [r.source_position for r in s.upto(3).invalid_rows]


def _gap_series():
    rows = good(8)
    keep = [rows[0], rows[1], (rows[2][0], None, 1, 1, 1, 1), (rows[3][0], None, 1, 1, 1, 1), rows[4], rows[6], rows[7]]
    return inspect_chart_json(chart(keep)).partial_series()   # source rows 2,3 invalid; t[5] genuinely absent


def test_m22_m23_m24_gap_stream_with_and_without_invalid_positions_and_parity():
    s = _gap_series()
    assert s.source_positions == (0, 1, 4, 5, 6)
    inv = {r.source_position for r in s.invalid_rows}
    batch = detect_gaps(s, M5, CONT).gaps
    gs_full, gs_none, full, none = GapStream(M5, CONT), GapStream(M5, CONT), [], []
    for i, c in enumerate(s):
        lo = -1 if i == 0 else s.source_positions[i - 1]
        full += gs_full.on_candle(c, s.source_positions[i], [p for p in sorted(inv) if lo < p < s.source_positions[i]])
        none += gs_none.on_candle(c, s.source_positions[i])
    assert full == list(batch)                                                        # M24 parity
    assert [(g.index, g.skipped_source_rows) for g in full] == [(2, 2), (3, 0)]       # M22
    assert [(g.index, g.skipped_source_rows) for g in none] == [(2, None), (3, 0)]    # M23: difference alone -> None


def test_m25_invalid_or_overlapping_provenance_rejected():
    cs = list(CandleSeries.from_rows([(T0, 10, 11, 9, 10), (T0 + 300, 10, 11, 9, 10)]))
    ir = lambda p: InvalidRow(p, None, "x", "INVALID_TIMESTAMP", ("timestamp",))
    assert raises(CandleError, CandleSeries, cs, source_positions=(3, 3))              # not strictly increasing
    assert raises(CandleError, CandleSeries, cs, source_positions=(3, 1))
    assert raises(CandleError, CandleSeries, cs, source_positions=(-1, 0))
    assert raises(CandleError, CandleSeries, cs, source_positions=(0,))                 # wrong length
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 2))               # row 1 unaccounted
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 2), invalid_rows=(ir(2),))   # overlap
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 3), invalid_rows=(ir(2), ir(1)))
    assert raises(CandleError, CandleSeries, cs, source_positions=(0, 3), invalid_rows=(ir(1), ir(1), ir(2)))
    assert len(CandleSeries(cs, source_positions=(0, 3), invalid_rows=(ir(1), ir(2)))) == 2
    gs = GapStream(M5, CONT)
    gs.on_candle(cs[0], 0)
    for bad in ([0], [3], [2, 1], [1, 1], [1]):                                         # out of range / unordered / incomplete
        assert raises(ValueError, gs.on_candle, cs[1], 3, bad), bad
    assert raises(ValueError, gs.on_candle, cs[1])                                      # all-or-nothing positions
    assert raises(ValueError, gs.on_candle, cs[1], 0)                                   # not increasing
    assert [g.skipped_source_rows for g in gs.on_candle(cs[1], 3, [1, 2])] == []        # adjacent ts: no gap, accepted

if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
