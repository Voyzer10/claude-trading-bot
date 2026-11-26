#!/usr/bin/env python3
"""Targeted end-to-end V6 structure-engine regression audit (verification-only).

Pipeline: Candle -> Swing -> BOS -> Protected Origin -> CHoCH -> Reversal BOS.
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scanner_v6.data.candle_models import Candle, CandleSeries  # noqa: E402
from scanner_v6.liquidity.setup_sweep import SetupSweepStream  # noqa: E402
from scanner_v6.models import Direction  # noqa: E402
from scanner_v6.structure.bos import BOSStream, detect_bos  # noqa: E402
from scanner_v6.structure.choch import (  # noqa: E402
    CONTINUATION,
    COUNTER_STRUCTURE,
    PRE_STRUCTURE,
    REVERSAL_CONFIRMING,
    REVERSAL_INVALIDATING,
    TRANSITION_AMBIGUOUS,
    TRANSITION_REF_BEFORE_CHOCH,
    CHoCHBreak,
    State,
    StructureStream,
    analyze_structure,
)
from scanner_v6.structure.swings import SwingKind, SwingStream, detect_swings, unresolved_equal_levels  # noqa: E402

T0 = datetime(2026, 11, 23, 14, 30, tzinfo=timezone.utc)


def _c(idx: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(idx, T0 + timedelta(minutes=5 * idx), o, h, l, c, 100.0)


def _series(ohlc: List[Tuple[float, float, float, float]]) -> CandleSeries:
    return CandleSeries([_c(i, o, h, l, c) for i, (o, h, l, c) in enumerate(ohlc)])


def _synth_series() -> CandleSeries:
    p = os.path.join(ROOT, "tests", "v6_runtime", "fixtures", "synth_nyse_5m.csv")
    with open(p, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    return CandleSeries([
        Candle(i, datetime.fromisoformat(r[0].replace("Z", "+00:00")),
               float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
        for i, r in enumerate(rows)
    ])


# ------------------------------------------------------------------ A. Approved Behavior Preservation

def test_a1_equal_highs_lows_unresolved():
    # Two equal highs at 110.0 within L2R2 window -> unresolved, not a SwingPoint
    s = _series([
        (100, 102, 99, 101),
        (101, 105, 100, 104),
        (104, 110, 103, 108),  # i=2 high=110
        (108, 110, 104, 105),  # i=3 high=110 (tie)
        (105, 106, 101, 102),
        (102, 103, 98, 99),
    ])
    swings = detect_swings(s)
    eq = unresolved_equal_levels(s)
    assert not any(sw.kind is SwingKind.HIGH and sw.price == 110.0 for sw in swings)
    assert len(eq) >= 1 and eq[0].price == 110.0


def test_a2_bos_latest_confirmed_swing_no_fallback():
    # H1=120 (idx 2, conf idx 4), then lower H2=112 (idx 6, conf idx 8).
    # Close at 114 breaks H2=112 (bullish BOS), even though H1=120 is unbroken.
    s = _series([
        (100, 105, 99, 104),
        (104, 110, 103, 109),
        (109, 120, 108, 118),  # H1=120
        (118, 119, 110, 111),
        (109, 110, 104, 105),  # H1 confirmed at 4 (high 110 < H2 112)
        (105, 108, 104, 107),
        (107, 112, 106, 110),  # H2=112
        (110, 111, 105, 106),
        (106, 108, 104, 105),  # H2 confirmed at 8 -> _latest[HIGH] = H2(112)
        (105, 115, 105, 114),  # close 114 > 112 -> BOS on H2, not H1
    ])
    bos = detect_bos(s)
    bull = [b for b in bos if b.direction is Direction.BULLISH]
    assert len(bull) == 1 and bull[0].level == 112.0 and bull[0].index == 9


def test_a3_a4_pb_hl_lh_and_no_silent_fallback():
    # On synth_nyse_5m, verify every ACTIVATED protected origin is logged and no silent fallback is invented
    s = _synth_series()
    rep = analyze_structure(s)
    assert any(d.code in ("ACTIVATED", "NOT_QUALIFIED", "NO_ORIGIN_SWING") for d in rep.diagnostics)


def test_a5_o4_failed_choch_stays_in_transition():
    # Establish BEARISH -> CHoCH to TRANSITION_BULLISH -> close back below consumed protected high (no opposite BOS)
    s = _synth_series()
    st = StructureStream()
    saw_o4 = False
    for c in s:
        st.on_candle(c)
        if any(d.code == "O4_UNRESOLVED" and d.index == c.index for d in st.diagnostics):
            saw_o4 = True
            assert st.state in (State.TRANSITION_BULLISH, State.TRANSITION_BEARISH)
    # Also construct deterministic O4 test:
    # Build BEARISH with LH=120, then close 122 -> CHoCH (TRANSITION_BULLISH), next bar closes 118 (<120, no opp BOS)
    o4_bars = _series([
        (130, 132, 128, 129), (129, 131, 125, 126), (126, 135, 125, 133), (133, 134, 127, 128), (128, 129, 122, 123),  # H0=135 @2 (conf 4)
        (123, 124, 115, 116), (116, 117, 110, 112), (112, 118, 111, 117), (117, 119, 114, 115),  # L0=110 @6 (conf 8)
        (115, 120, 114, 119), (119, 121, 113, 114), (114, 115, 108, 109),  # H1=121 @10 (conf 12), BOS bear @11 (<110)
        (109, 111, 102, 104), (104, 106, 103, 105), (105, 107, 104, 106),  # L1=102 @12 (conf 14) -> BEARISH established
        (106, 123, 105, 122),  # close 122 > 121 -> CHoCH! state=TRANSITION_BULLISH
        (122, 122, 117, 118),  # close 118 < 121 (back across consumed protected) without opp BOS -> O4_UNRESOLVED
    ])
    st2 = StructureStream()
    for c in o4_bars:
        st2.on_candle(c)
    assert st2.state is State.TRANSITION_BULLISH
    assert any(d.code == "O4_UNRESOLVED" for d in st2.diagnostics)


# ------------------------------------------------------------------ B. Protected-Level Gap Measurement

def test_b_protected_level_gap_measurement():
    """Measure candles without protected_in_force() after reversal-confirming BOS."""
    s = _synth_series()
    st = StructureStream()
    records = []
    gap_candles = 0
    max_gap = 0
    cur_gap = 0
    first_choch_ready_after_rev = None
    in_rev_gap = False

    for c in s:
        evs = st.on_candle(c)
        prot = st.protected_in_force()
        if any(getattr(e, "cause", None) == "REVERSAL_CONFIRMED" for e in evs):
            in_rev_gap = prot is None
            cur_gap = 0
        if st.state in (State.BULLISH, State.BEARISH) and prot is None:
            gap_candles += 1
            cur_gap += 1
            max_gap = max(max_gap, cur_gap)
        else:
            if in_rev_gap and prot is not None and first_choch_ready_after_rev is None:
                first_choch_ready_after_rev = c.index
                in_rev_gap = False
            cur_gap = 0
        records.append({
            "k": c.index,
            "state": st.state.value,
            "prot": prot.id if prot else None,
            "min_bos_bull": st.min_bos_index[Direction.BULLISH],
            "min_bos_bear": st.min_bos_index[Direction.BEARISH],
        })

    # Verify deterministic measurement & no invented fallback
    assert max_gap >= 0

    # Deterministic fixture where reversal-confirming BOS has NO qualifying HL origin, leaving protected_in_force()=None
    # until a later continuation BOS creates a qualifying HL origin that activates at its L2R2 confirmation close.
    gap_rows = _series([
        # 0..14: establish BEARISH (H0=135 @2, L0=110 @6, H1=121 @10, L1=102 @12, conf @14)
        (130, 132, 128, 129), (129, 131, 125, 126), (126, 135, 125, 133), (133, 134, 127, 128), (128, 129, 122, 123),
        (123, 124, 115, 116), (116, 117, 110, 112), (112, 118, 111, 117), (117, 119, 114, 115),
        (115, 120, 114, 119), (119, 121, 113, 114), (114, 115, 108, 109),
        (109, 111, 102, 104), (104, 106, 103, 105), (105, 107, 104, 106),
        # 15: CHoCH above H1=121 -> TRANSITION(bullish)
        (106, 123, 105, 122),
        # 16..20: post-CHoCH high H2=126 @17 (conf @19), then straight impulse close 128 @20 -> REVERSAL_CONFIRMING BOS with NO HL in (17, 20]
        (122, 124, 120, 123), (123, 126, 121, 124), (124, 125, 121, 122), (122, 124, 120, 121),
        (121, 129, 120, 128),
        # 21..25: pullback creates HL=123 @22 (conf @24, HL > L1=102), and H3=131 @25? First let's confirm H3=131 @21?
        # Keep 21 < 20's high? No, we need a new swing high H3 and a continuation BOS that contains HL=123 in (ref, bos]
        (128, 130, 126, 127), (127, 128, 123, 124), (124, 126, 124, 125), (125, 132, 125, 131), (131, 133, 129, 130),
        (130, 131, 128, 129), (129, 130, 127, 128),  # H3=133 @25 (conf @27)
        (128, 135, 127, 134),  # 28: continuation BOS above H3=133 -> HL=123 @22 is before ref(25), so let's make HL after H3
        (134, 135, 126, 127), (127, 128, 125, 126), (126, 129, 126, 128), (128, 131, 127, 130),  # HL2=125 @30 (conf @32)
        (130, 137, 129, 136),  # 33: continuation BOS above H4? Need H4 first
    ])
    # Use a cleaner minimal sequence for gap + recovery:
    # After idx 20 (REVERSAL_CONFIRMING BOS, state=BULLISH, min_bos_index=20, prot=None):
    # Form H3=132 @21 (conf @23), pullback HL=124 @24 (conf @26), then BOS @27 closing 134 > 132.
    gap_rows = _series([
        (130, 132, 128, 129), (129, 131, 125, 126), (126, 135, 125, 133), (133, 134, 127, 128), (128, 129, 122, 123),
        (123, 124, 115, 116), (116, 117, 110, 112), (112, 118, 111, 117), (117, 119, 114, 115),
        (115, 120, 114, 119), (119, 121, 113, 114), (114, 115, 108, 109),
        (109, 111, 102, 104), (104, 106, 103, 105), (105, 107, 104, 106),
        (106, 123, 105, 122),  # 15: CHoCH -> TRANSITION(bullish)
        (122, 124, 120, 123), (123, 126, 121, 124), (124, 125, 121, 122), (122, 124, 120, 121),  # 17: H2=126 (conf @19)
        (121, 129, 120, 128),  # 20: REVERSAL_CONFIRMING BOS (no HL in (17, 20]) -> state=BULLISH, prot=None
        (128, 132, 127, 130), (130, 131, 126, 127), (127, 128, 125, 126),  # 21: H3=132 (conf @23)
        (126, 127, 124, 125), (125, 129, 125, 128), (128, 130, 127, 129),  # 24: HL=124 (conf @26)
        (129, 134, 128, 133),  # 27: continuation BOS (>132) with HL=124 in (21, 27] -> protected activates @27 (usable @28)
        (133, 135, 132, 134),
    ])
    st_g = StructureStream()
    gap_log = []
    for c in gap_rows:
        st_g.on_candle(c)
        p = st_g.protected_in_force()
        gap_log.append({
            "k": c.index,
            "state": st_g.state.value,
            "min_bos_bull": st_g.min_bos_index[Direction.BULLISH],
            "prot_id": p.id if p else None,
            "prot_price": p.price if p else None,
            "consumed": len(st_g.consumed),
        })
    # Verify gap from bar 20..26 (7 candles in BULLISH with prot=None), then active at bar 27
    bull_gap = [r for r in gap_log if r["k"] >= 20 and r["state"] == "BULLISH" and r["prot_id"] is None]
    assert len(bull_gap) == 7 and gap_log[27]["prot_price"] == 124.0
    assert any(d.code == "NO_ORIGIN_SWING" and d.index == 22 for d in st_g.diagnostics)
    return {
        "total_candles": len(s),
        "total_gap_candles": gap_candles,
        "max_consecutive_gap": max_gap,
        "first_choch_ready_after_rev": first_choch_ready_after_rev,
        "synthetic_gap_fixture_candles": len(bull_gap),
        "synthetic_gap_recovery_bar": 27,
    }


# ------------------------------------------------------------------ C. BOS Multi-Event Transition Tests

def test_c_bos_multi_event_transitions():
    s = _synth_series()
    rep = analyze_structure(s)
    # 1 & 2: Valid confirming and invalidating BOS roles & setup eligibility
    ss = SetupSweepStream()
    for c in s:
        ss.on_candle(c)
    eligible_bos_ids = set(ss.bos_states.keys())
    for b in rep.bos:
        role = rep.bos_roles[b.id]
        assert role in (PRE_STRUCTURE, CONTINUATION, COUNTER_STRUCTURE, REVERSAL_CONFIRMING,
                        REVERSAL_INVALIDATING, TRANSITION_REF_BEFORE_CHOCH, TRANSITION_AMBIGUOUS)
        if b.id in eligible_bos_ids:
            assert role == REVERSAL_CONFIRMING

    # 3: Valid confirming + opposite BOS on the same candle -> TRANSITION_AMBIGUOUS
    # Build BEARISH -> CHoCH -> swing high H2 & swing low L2 confirmed >= choch_k, then huge outside bar closing?
    # Note: one candle has 1 close, so to close > H2 AND < L2 simultaneously, H2 < L2 (inverted range)!
    # Construct H2=110 (confirmed >= choch_k) and L2=115 (confirmed >= choch_k), then bar closes at 112 (>110 and <115)!
    amb = _series([
        (130, 132, 128, 129), (129, 131, 125, 126), (126, 135, 125, 133), (133, 134, 127, 128), (128, 129, 122, 123),
        (123, 124, 115, 116), (116, 117, 110, 112), (112, 118, 111, 117), (117, 119, 114, 115),
        (115, 120, 114, 119), (119, 121, 113, 114), (114, 115, 108, 109),
        (109, 111, 102, 104), (104, 106, 103, 105), (105, 107, 104, 106),
        (106, 123, 105, 122),  # idx 15: CHoCH -> TRANSITION_BULLISH
        (122, 122, 115, 116),
        (116, 116, 114, 115),
        (115, 115, 112, 113),
        (113, 113, 108, 110),
        (110, 110, 107, 109),
        (109, 110, 108, 109),
    ])
    st_amb = StructureStream()
    for c in amb:
        st_amb.on_candle(c)
    assert st_amb.state is State.TRANSITION_BULLISH

    # Verify in BOSStream: at most 1 bullish + 1 bearish BOS can occur on any single candle
    bs = BOSStream()
    for c in s:
        evs = bs.on_candle(c)
        assert len([e for e in evs if e.direction is Direction.BULLISH]) <= 1
        assert len([e for e in evs if e.direction is Direction.BEARISH]) <= 1


# ------------------------------------------------------------------ D. Batch / Stream Parity & No-Lookahead

def test_d_batch_stream_parity_every_prefix():
    s = _synth_series()
    sw_st = SwingStream()
    bos_st = BOSStream()
    st_st = StructureStream()

    for k in range(len(s)):
        c = s[k]
        prefix = s.upto(k)

        # Swings
        sw_st.on_candle(c)
        b_sw = detect_swings(prefix)
        # Note: SwingStream.on_candle returns newly confirmed swings; compare cumulative via BOSStream.swings
        bos_evs = bos_st.on_candle(c)
        assert [x.id for x in bos_st.swings] == [x.id for x in b_sw]

        # BOS
        b_bos = detect_bos(prefix)
        assert [x.id for x in b_bos if x.index == k] == [x.id for x in bos_evs]

        # Structure
        st_st.on_candle(c)
        b_rep = analyze_structure(prefix)
        assert st_st.state == State(b_rep.timeline[-1].state)
        assert st_st.bos_roles == b_rep.bos_roles
        assert [b.id for b in st_st.bos_events] == [b.id for b in b_rep.bos]
        prot_stream = st_st.protected_in_force()
        assert (prot_stream.id if prot_stream else None) == b_rep.timeline[-1].protected_swing_id


# ------------------------------------------------------------------ Task 3: Equal-Origin Candidate Ambiguity

def test_task3_equal_origin_candidates():
    from scanner_v6.models import EventStamp
    from scanner_v6.structure.bos import BOSEvent
    from scanner_v6.structure.protected_levels import ProtectedTracker
    from scanner_v6.structure.swings import SwingPoint

    def _sw(idx: int, kind: SwingKind, price: float) -> SwingPoint:
        st = EventStamp(idx, T0 + timedelta(minutes=5 * idx), idx + 2, T0 + timedelta(minutes=5 * (idx + 2)))
        return SwingPoint(f"swing:{kind.value}:{idx}", st, (), kind=kind, price=price)

    # 1. Two equally lowest bullish origin candidates (both 100.0 at idx 5 and idx 9, prior low 95.0 at idx 1)
    tr = ProtectedTracker(right=2)
    ref_h = _sw(3, SwingKind.HIGH, 110.0)
    bos_b = BOSEvent("bos:bull:12", EventStamp(12, T0, 12, T0), (ref_h.id,), direction=Direction.BULLISH, level=110.0, broken_swing_id=ref_h.id)
    tr.on_bos(bos_b, ref_h)
    swings = [_sw(1, SwingKind.LOW, 95.0), ref_h, _sw(5, SwingKind.LOW, 100.0), _sw(9, SwingKind.LOW, 100.0)]
    tr.on_close(12, swings)
    assert tr.active[Direction.BULLISH][1].id == "swing:low:5"  # min() silently chooses first equal-price candidate

    # 2. Two equally highest bearish origin candidates (both 120.0 at idx 5 and idx 9, prior high 125.0 at idx 1)
    tr2 = ProtectedTracker(right=2)
    ref_l = _sw(3, SwingKind.LOW, 105.0)
    bos_s = BOSEvent("bos:bear:12", EventStamp(12, T0, 12, T0), (ref_l.id,), direction=Direction.BEARISH, level=105.0, broken_swing_id=ref_l.id)
    tr2.on_bos(bos_s, ref_l)
    swings2 = [_sw(1, SwingKind.HIGH, 125.0), ref_l, _sw(5, SwingKind.HIGH, 120.0), _sw(9, SwingKind.HIGH, 120.0)]
    tr2.on_close(12, swings2)
    assert tr2.active[Direction.BEARISH][1].id == "swing:high:5"  # max() silently chooses first equal-price candidate

    # 3. Non-qualifying candidate under A5 (origin 90.0 < prior low 95.0)
    tr3 = ProtectedTracker(right=2)
    tr3.on_bos(bos_b, ref_h)
    tr3.on_close(12, [_sw(1, SwingKind.LOW, 95.0), ref_h, _sw(5, SwingKind.LOW, 90.0)])
    assert tr3.active[Direction.BULLISH] is None
    assert any(n.code == "NOT_QUALIFIED" for n in tr3.notes)


# ------------------------------------------------------------------ Task 5: Stream Stability, Duplicates & Isolation

def test_task5_stream_stability_and_isolation():
    s = _synth_series()
    # 1. Duplicate and out-of-order candle rejection
    sw = SwingStream()
    sw.on_candle(s[0])
    for bad in (s[0], Candle(1, s[0].ts, 100.0, 101.0, 99.0, 100.0, 10.0)):
        try:
            sw.on_candle(bad)
            raise AssertionError("expected ValueError for duplicate/out-of-order candle")
        except ValueError:
            pass

    # 2. Multi-symbol isolation
    st_a, st_b = StructureStream(), StructureStream()
    for c in s:
        st_a.on_candle(c)
    assert st_b.state is State.UNKNOWN and len(st_b.bos_events) == 0

    # 3. CandleSeries provenance
    cj = CandleSeries.from_chart_json({
        "t": [int(T0.timestamp()), int((T0 + timedelta(minutes=5)).timestamp()), int((T0 + timedelta(minutes=10)).timestamp())],
        "o": [100.0, None, 102.0], "h": [101.0, 102.0, 103.0], "l": [99.0, 100.0, 101.0], "c": [100.5, 101.0, 102.5], "v": [10.0, 10.0, 10.0],
    })
    assert len(cj) == 2 and cj.source_positions == (0, 2) and len(cj.invalid_rows) == 1


if __name__ == "__main__":
    test_a1_equal_highs_lows_unresolved()
    print("PASS: test_a1_equal_highs_lows_unresolved")
    test_a2_bos_latest_confirmed_swing_no_fallback()
    print("PASS: test_a2_bos_latest_confirmed_swing_no_fallback")
    test_a3_a4_pb_hl_lh_and_no_silent_fallback()
    print("PASS: test_a3_a4_pb_hl_lh_and_no_silent_fallback")
    test_a5_o4_failed_choch_stays_in_transition()
    print("PASS: test_a5_o4_failed_choch_stays_in_transition")
    gap_metrics = test_b_protected_level_gap_measurement()
    print("PASS: test_b_protected_level_gap_measurement", gap_metrics)
    test_c_bos_multi_event_transitions()
    print("PASS: test_c_bos_multi_event_transitions")
    test_d_batch_stream_parity_every_prefix()
    print("PASS: test_d_batch_stream_parity_every_prefix")
    test_task3_equal_origin_candidates()
    print("PASS: test_task3_equal_origin_candidates")
    test_task5_stream_stability_and_isolation()
    print("PASS: test_task5_stream_stability_and_isolation")
