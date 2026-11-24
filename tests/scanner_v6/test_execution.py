#!/usr/bin/env python3
"""Module E: confirmed-setup intake, PAPER next-open entry, sizing, structural SL, pool TP, FIXED_SL_TP exits, CK-13
reasons and priority, OQ-2 dispositions, OQ-6 daily loss, OQ-7 sessions, OQ-3 data interruption, CK-25 end of data,
lifecycle, determinism, prefix replay and no look-ahead (spec Sections 4-10, CK-10, CK-13, CK-14, CK-16, CK-19...CK-26,
OQ-1...OQ-7, MD-4, ME-1...ME-4).

Expectations are INDEPENDENT of scanner_v6.exit: prices are written out from the fixture design, and sizing / fees /
net R:R come from an exact-rational oracle in this file (fractions, own rounding, brute-force quantity search).

Fixture (BUY world; SELL = mirror x -> 200 - x, same indices): an independent copy of the Module D test BASE path
(CHoCH@33, REVERSAL_CONFIRMING BOS@39, SSL sweep group sweep:SSL:47; sweep candle 47 low 115.28 / high 116.03), then
48-49 Bullish Engulfing (high 116.35, low 115.93) and 50 confirming close 116.45: setup CONFIRMED at C = 50.
Pools known at the close of 50 (Module B, unchanged): ACTIVE BSL swing 42 @ 119.70 and swing 3 @ 121.10 (all other
highs TAKEN). Candle k opens at 2026-01-05 09:00Z + 5k min; C = 50 is 13:10Z, the entry candle C+1 = 51 is 13:15Z.
With buffer 2 ticks: SL = 115.28 - 0.02 = 115.26; planned_risk_distance = 116.45 - 115.26 = 1.19;
0.25 x 1.19 = 0.2975. TP = 119.70 - tp_offset_ticks x 0.01.

    python tests/scanner_v6/test_execution.py   (or: python -m pytest tests/scanner_v6)
"""
import os
import random
import sys
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import raises, run_main  # noqa: E402

from scanner_v6.data.candle_models import Candle, CandleSeries  # noqa: E402
from scanner_v6.data.market_config import ConfigError, MarketDataConfig  # noqa: E402
from scanner_v6.engine import no_lookahead_violations  # noqa: E402
from scanner_v6.exit import execution as E  # noqa: E402
from scanner_v6.exit.execution_config import ExecutionConfig, LinearFeeSchedule  # noqa: E402

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
TF = "5m"
C = 50


def r2(x):
    return round(x + 1e-9, 2)


# ---------------------------------------------------------------- BASE path (independent copy of the Module D builder)
def _leg(rows, cur, n, target):
    start = cur
    for j in range(1, n + 1):
        o = cur
        cl = r2(start + (target - start) * j / n)
        h, l = (cl + 0.10, o - 0.03) if cl >= o else (o + 0.03, cl - 0.10)
        rows.append((r2(o), r2(h), r2(l), r2(cl)))
        cur = cl
    return cur


def _base():
    rows, c = [], 120.00
    for n, t in ((4, 121.0), (6, 116.0), (4, 118.0), (5, 114.0), (4, 116.5), (5, 112.0), (6, 117.5), (3, 115.5),
                 (4, 119.0), (2, 119.6), (4, 116.0)):
        c = _leg(rows, c, n, t)
    P = min(x[2] for x in rows[-13:-6])
    rows.append((r2(c), r2(c + 0.03), r2(P - 0.12), r2(P + 0.20)))
    return rows


BASE = _base()
CONFIRM = [(116.20, 116.25, 115.95, 116.00), (115.98, 116.35, 115.93, 116.30), (116.20, 116.50, 116.15, 116.45)]
N = (116.45, 116.60, 116.40, 116.55)            # neutral entry candle: no SL / TP touch
Q = (116.55, 116.70, 116.50, 116.60)            # quiet candle
SWEEP_LOW, CONF_CLOSE, POOL42, POOL3 = Fraction("115.28"), Fraction("116.45"), Fraction("119.70"), Fraction("121.10")


def mirror(rows):
    return [(r2(200 - o), r2(200 - l), r2(200 - h), r2(200 - c)) for o, h, l, c in rows]


def series(rows, ins, gaps=()):
    """gaps: candle positions whose timestamp (and every later one) is shifted by +5 min (a missing interval)."""
    out, shift = [], 0
    for i, (o, h, l, c) in enumerate(rows):
        if i in gaps:
            shift += 5
        out.append((T0 + timedelta(minutes=5 * i + shift), o, h, l, c))
    return CandleSeries.from_rows(out, ins, TF)


CONT = {"kind": "continuous_24_7", "timezone": "UTC"}


def market(ins, session=CONT, tick=0.01):
    d = {"instrument_id": ins, "timeframe_seconds": 300}
    if tick is not None:
        d["tick_size"] = tick
    if session is not None:
        d["session"] = session
    return MarketDataConfig.from_fixture(d)


FEES = dict(rate="0.0001", per_unit="0", per_order="0", rounding_places=2, rounding_mode="ROUND_HALF_UP", source="TEST")
ZERO_FEES = dict(rate="0", per_unit="0", per_order="0", rounding_places=2, rounding_mode="ROUND_HALF_UP", source="TEST")
BASE_CFG = dict(starting_equity="100000", entry_ticks=1, stop_exit_ticks=1, target_exit_ticks=0, max_gap_ticks=50,
                sl_buffer_ticks=2, tp_offset_ticks=1, contract_multiplier="1", lot_size="1", quantity_step="1",
                min_quantity="1", fee_schedule=FEES, price_rounding_mode="ROUND_HALF_UP", initial_margin_rate="0.2",
                trading_day_start="00:00")


def cfg(**over):
    d = dict(BASE_CFG)
    for k, v in over.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    return ExecutionConfig.from_fixture(d)


def run(after, side="BUY", conf=None, session=CONT, tick=0.01, data_events=(), gaps=()):
    ins = "TEST-%s" % side
    rows = BASE + CONFIRM + list(after)
    if side == "SELL":
        rows = mirror(rows)
    return E.analyze_execution(series(rows, ins, gaps), ins, TF, market(ins, session, tick), conf or cfg(),
                               data_events=data_events)


def only(rep):
    assert len(rep.records) == 1, [(r.setup_id, r.status) for r in rep.records]
    return rep.records[0]


def path(r):
    return [(t.status, t.index) for t in r.history]


def px(side, v):
    """A BUY-world price as Decimal for `side` (SELL = 200 - v)."""
    v = Fraction(str(v))
    return Decimal(str(float(v if side == "BUY" else 200 - v))).quantize(Decimal("0.01"))


# ---------------------------------------------------------------- independent oracle (fractions)
def o_fee(f, price, q, m):
    raw = Fraction(f["rate"]) * price * q * m + Fraction(f["per_unit"]) * q + Fraction(f["per_order"])
    scaled = raw * 100                                       # ROUND_HALF_UP, 2 places, raw >= 0
    n = scaled.numerator // scaled.denominator
    if scaled - n >= Fraction(1, 2):
        n += 1
    return Fraction(n, 100)


def oracle(entry_open, conf):
    """Expected outcome of the BASE BUY setup for an entry candle open, from the ME-1 order and Section 7 formulas."""
    T = Fraction(1, 100)
    sl = SWEEP_LOW - conf["sl_buffer_ticks"] * T
    prd = CONF_CLOSE - sl
    maxgap = min(conf["max_gap_ticks"] * T, Fraction(1, 4) * prd)
    fill = entry_open + conf["entry_ticks"] * T
    pool = POOL42 if POOL42 > fill else (POOL3 if POOL3 > fill else None)
    if pool is None:
        return dict(code="NO_ELIGIBLE_OPPOSING_POOL")
    tp = pool - conf["tp_offset_ticks"] * T
    if entry_open <= sl:
        return dict(code="ENTRY_AT_OR_BEYOND_SL")
    if entry_open - CONF_CLOSE > maxgap:
        return dict(code="ENTRY_GAP_EXCEEDED")
    sfill = sl - conf["stop_exit_ticks"] * T
    m, f = Fraction(conf["contract_multiplier"]), conf["fee_schedule"]
    E0 = Fraction(conf["starting_equity"])
    B = E0 / 100
    step, qmin = Fraction(conf["quantity_step"]), Fraction(conf["min_quantity"])

    def loss(q):
        return q * (fill - sfill) * m + o_fee(f, fill, q, m) + o_fee(f, sfill, q, m)

    def rr(q):
        return (q * (tp - fill) * m - o_fee(f, fill, q, m) - o_fee(f, tp, q, m)) / loss(q)

    qr, q = None, qmin
    while q * (fill - sfill) * m <= B:                       # brute force upward
        if loss(q) <= B:
            qr = q
        q += step
    if rr(qr if qr is not None else qmin) < 1:
        return dict(code="NET_RR_BELOW_MINIMUM")
    if qr is None:
        return dict(code="MIN_QTY_EXCEEDS_RISK_BUDGET")
    rate = Fraction(conf["initial_margin_rate"])
    qf = qr
    while qf >= qmin and not (fill * qf * m * rate <= E0 and rr(qf) >= 1):
        qf -= step
    if qf < qmin:
        return dict(code="INSUFFICIENT_MARGIN")
    return dict(code="ENTERED", q=qf, fill=fill, sl=sl, tp=tp, sfill=sfill, loss=loss(qf), rr=rr(qf),
                fee=o_fee(f, fill, qf, m), qr=qr)


def F(d):
    return Fraction(str(d))


def close(dec_value, frac, tol=Fraction(1, 10 ** 20)):
    """A reported Decimal quotient (28 significant digits) against the exact oracle fraction."""
    return abs(F(dec_value) - frac) < tol


# ================================================================ tests
def test_buy_sell_next_open_entry_and_independent_values():
    for side in ("BUY", "SELL"):
        r = only(run([N, Q], side))
        assert r.status == E.ENTERED and r.result == E.ENTERED, r
        assert path(r) == [("CHOCH_DETECTED", 33), ("BOS_CONFIRMED", 39), ("SWEEP_DETECTED", 47),
                           ("PATTERN_DETECTED", 49), ("CONFIRMED", 50), ("ENTERED", 51)]
        assert r.history[-1].ts == T0 + timedelta(minutes=5 * 51)
        ex = oracle(Fraction("116.45"), BASE_CFG)
        assert r.entry_open == px(side, "116.45") and r.entry_fill == px(side, "116.46")
        assert r.sl == px(side, "115.26") and r.planned_stop_fill == px(side, "115.25") and r.tp == px(side, "119.69")
        assert r.tp_pool_id == "pool:swing:%s:42:fixed-window-strict:L2R2" % ("high" if side == "BUY" else "low")
        assert r.planned_risk_distance == Decimal("1.19") and r.max_adverse_gap == Decimal("0.2975")
        if side == "BUY":                                    # fees are notional-based: BUY values from the oracle
            assert F(r.quantity) == ex["q"] and F(r.loss_estimate) == ex["loss"] and close(r.net_rr, ex["rr"])
            assert F(r.entry_fee) == ex["fee"] and F(r.risk_budget) == 1000 and r.reason_code is None
            q1 = ex["q"] + 1                                     # one more unit would exceed the 1% budget
            assert q1 * Fraction("1.21") + o_fee(FEES, Fraction("116.46"), q1, 1) + o_fee(FEES, Fraction("115.25"), q1, 1) > 1000


def test_quantity_rounds_down_never_up_and_min_quantity():
    ex = oracle(Fraction("116.45"), dict(BASE_CFG, quantity_step="50", min_quantity="50"))
    r = only(run([N], conf=cfg(quantity_step="50", min_quantity="50")))
    assert F(r.quantity) == ex["q"] and F(r.quantity) % 50 == 0 and F(r.loss_estimate) <= 1000
    # largest multiple of 50 with Loss <= 1000: the next step up must exceed the budget (oracle independent)
    q = F(r.quantity)
    assert q * Fraction("1.21") + o_fee(FEES, Fraction("116.46"), q, 1) + o_fee(FEES, Fraction("115.25"), q, 1) <= 1000
    q2 = q + 50
    assert q2 * Fraction("1.21") + o_fee(FEES, Fraction("116.46"), q2, 1) + o_fee(FEES, Fraction("115.25"), q2, 1) > 1000
    for side in ("BUY", "SELL"):                             # minimum quantity above the budget (1000 x 1.21 > 1000)
        r = only(run([N], side, conf=cfg(min_quantity="1000")))
        assert (r.status, r.reason_code, r.disposition_reason) == (E.NO_TRADE, E.MIN_QTY_EXCEEDS_RISK_BUDGET, None)
        assert path(r)[-1] == ("NO_TRADE", 51) and r.quantity is None


def test_gap_limit_boundaries_ratio_and_ticks():
    # ratio limit 0.2975 (max_gap_ticks 50 = 0.50 is looser): gap 0.29 ok, 0.30 exceeded
    for side in ("BUY", "SELL"):
        ok = only(run([(116.74, 116.90, 116.70, 116.80)], side))
        assert ok.status == E.ENTERED and ok.adverse_gap == Decimal("0.29"), ok
        bad = only(run([(116.75, 116.90, 116.70, 116.80)], side))
        assert (bad.status, bad.reason_code) == (E.NO_TRADE, E.ENTRY_GAP_EXCEEDED) and bad.adverse_gap == Decimal("0.30")
        # tick limit stricter (10 ticks = 0.10): gap exactly 0.10 is not "exceeding"; 0.11 is
        ok = only(run([(116.55, 116.70, 116.50, 116.60)], side, conf=cfg(max_gap_ticks=10)))
        assert ok.status == E.ENTERED and ok.max_adverse_gap == Decimal("0.10")
        bad = only(run([(116.56, 116.70, 116.50, 116.60)], side, conf=cfg(max_gap_ticks=10)))
        assert bad.reason_code == E.ENTRY_GAP_EXCEEDED
        fav = only(run([(116.00, 116.20, 115.90, 116.10)], side))     # favourable gap never counts (adverse only)
        assert fav.status == E.ENTERED and fav.adverse_gap == Decimal("-0.45")


def test_entry_at_or_beyond_sl():
    for side in ("BUY", "SELL"):
        for o in (115.26, 115.10):                            # at SL and beyond
            r = only(run([(o, 115.40, o - 0.05, 115.30)], side))
            assert (r.status, r.reason_code) == (E.NO_TRADE, E.ENTRY_AT_OR_BEYOND_SL), (side, o, r)
        r = only(run([(115.27, 115.40, 115.27, 115.30)], side))         # one tick inside: allowed by #2 (then sized)
        assert r.reason_code != E.ENTRY_AT_OR_BEYOND_SL


def test_net_rr_boundary_exact():
    # zero fees: RR = (TP - 116.46) / (116.46 - 115.25) = (TP - 116.46) / 1.21; TP = 119.70 - n ticks
    for side in ("BUY", "SELL"):
        r = only(run([N], side, conf=cfg(fee_schedule=ZERO_FEES, tp_offset_ticks=203)))   # TP 117.67: RR = 1 exactly
        assert r.status == E.ENTERED and r.net_rr == 1 and r.tp == px(side, "117.67"), r
        r = only(run([N], side, conf=cfg(fee_schedule=ZERO_FEES, tp_offset_ticks=204)))   # TP 117.66: 1.20/1.21 < 1
        assert (r.status, r.reason_code) == (E.NO_TRADE, E.NET_RR_BELOW_MINIMUM)
        assert close(r.net_rr, Fraction("1.20") / Fraction("1.21"))
    # with fees the boundary moves: offset 203 now fails (fees reduce the reward and raise the loss)
    r = only(run([N], conf=cfg(tp_offset_ticks=203)))
    assert r.reason_code == E.NET_RR_BELOW_MINIMUM and oracle(Fraction("116.45"), dict(BASE_CFG, tp_offset_ticks=203))["code"] == "NET_RR_BELOW_MINIMUM"


def test_margin_reduction_and_insufficient_margin():
    # rate 2: margin(q) = 116.46 x q x 2 <= 100000 -> q <= 429; still within budget and RR -> reduced, entered
    for side in ("BUY", "SELL"):
        r = only(run([N], side, conf=cfg(initial_margin_rate="2", fee_schedule=ZERO_FEES)))
        fill = F(px(side, "116.46"))
        assert r.status == E.ENTERED and "QUANTITY_REDUCED_FOR_MARGIN" in r.diagnostics
        assert F(r.quantity) == int(100000 / (fill * 2)) and F(r.risk_quantity) == int(1000 / Fraction("1.21"))
        assert F(r.required_margin) <= 100000
        # minimum quantity 700 fits the risk budget (847 <= 1000) but its margin does not: BUY 116.46 x 700 x 2 =
        # 163044, SELL 83.54 x 700 x 2 = 116956, both > 100000 -> INSUFFICIENT_MARGIN
        r = only(run([N], side, conf=cfg(initial_margin_rate="2", fee_schedule=ZERO_FEES, min_quantity="700")))
        assert (r.status, r.reason_code) == (E.NO_TRADE, E.INSUFFICIENT_MARGIN)


def test_ck13_priority_order():
    gap_open = (116.75, 116.90, 116.70, 116.80)               # gap 0.30 > 0.2975
    cases = [
        # (entry candle, config overrides, expected): each pair of adjacent CK-13 conditions holds at once
        ([gap_open], dict(entry_ticks=None), E.EXECUTION_CONFIG_INCOMPLETE),              # #1 over #3
        ([(115.26, 115.40, 115.20, 115.30)], dict(fee_schedule=None), E.EXECUTION_CONFIG_INCOMPLETE),  # #1 over #2
        ([gap_open], dict(tp_offset_ticks=250), E.ENTRY_GAP_EXCEEDED),                     # #3 over #4
        ([N], dict(tp_offset_ticks=250, min_quantity="1000"), E.NET_RR_BELOW_MINIMUM),     # #4 over #5
        ([N], dict(min_quantity="1000", initial_margin_rate="5"), E.MIN_QTY_EXCEEDS_RISK_BUDGET),  # #5 over #6
        ([(115.26, 115.40, 115.20, 115.30)], dict(tp_offset_ticks=250, min_quantity="1000"), E.ENTRY_AT_OR_BEYOND_SL),
    ]
    for after, over, code in cases:
        for side in ("BUY", "SELL"):
            r = only(run(after, side, conf=cfg(**over)))
            assert (r.status, r.reason_code, r.disposition_reason) == (E.NO_TRADE, code, None), (over, side, r)
            assert len([t for t in r.history if t.status == E.NO_TRADE]) == 1       # exactly one final reason
    assert E.CK13_PRIORITY == ("EXECUTION_CONFIG_INCOMPLETE", "ENTRY_AT_OR_BEYOND_SL", "ENTRY_GAP_EXCEEDED",
                               "NET_RR_BELOW_MINIMUM", "MIN_QTY_EXCEEDS_RISK_BUDGET", "INSUFFICIENT_MARGIN")


def test_missing_configuration_never_defaulted():
    for key in ("starting_equity", "entry_ticks", "stop_exit_ticks", "target_exit_ticks", "max_gap_ticks",
                "sl_buffer_ticks", "tp_offset_ticks", "contract_multiplier", "lot_size", "quantity_step",
                "min_quantity", "fee_schedule", "price_rounding_mode", "initial_margin_rate", "trading_day_start"):
        r = only(run([N], conf=cfg(**{key: None})))
        assert (r.status, r.reason_code) == (E.NO_TRADE, E.EXECUTION_CONFIG_INCOMPLETE), key
        assert key in r.detail and path(r)[-1] == ("NO_TRADE", 50)                  # decided at the close of C
    r = only(run([N], conf=cfg(target_exit_ticks=1)))                                 # must be explicitly 0
    assert r.reason_code == E.EXECUTION_CONFIG_INCOMPLETE and "target_exit_ticks!=0" in r.detail
    r = only(run([N], session=None))
    assert r.reason_code == E.EXECUTION_CONFIG_INCOMPLETE and "session_calendar" in r.detail
    # zero values are explicit values, not defaults: entry_ticks 0 fills exactly at the open
    r = only(run([N], conf=cfg(entry_ticks=0)))
    assert r.status == E.ENTERED and r.entry_fill == Decimal("116.45")
    assert raises(ConfigError, cfg, entry_ticks=-1) and raises(ConfigError, cfg, quantity_step="3", lot_size="2")
    assert raises(ConfigError, cfg, unknown_key=1) and raises(ConfigError, cfg, price_rounding_mode="NEAREST")


def test_missing_tick_size_is_config_incomplete_or_unscorable_upstream():
    rep = run([N], tick=None)                                 # Module C / D score nothing without tick size (CK-1)
    assert rep.records == [] and all(s.status != "CONFIRMED" for s in rep.setups)
    st = E.ExecutionStream("X", TF, market("X", tick=None), cfg())
    assert "tick_size" in st.missing


def test_target_and_stop_exits_fixed_sl_tp():
    for side in ("BUY", "SELL"):
        mir = (lambda c: c) if side == "BUY" else (lambda c: mirror([c])[0])
        # target touch at 53: high 119.75 >= 119.69 -> fill exactly 119.69
        r = only(run([N, Q, (119.00, 119.75, 118.90, 119.50)], side))
        assert r.status == E.TARGET_HIT and r.exit_index == 53 and r.exit_fill == px(side, "119.69") and not r.exit_gap
        # target gap: open 120.00 beyond TP -> still filled at TP, no improvement
        r = only(run([N, Q, (120.00, 120.20, 119.90, 120.10)], side))
        assert r.status == E.TARGET_HIT and r.exit_fill == px(side, "119.69") and r.exit_gap
        # stop touch: low 115.20 <= 115.26 -> fill 115.25 (SL - 1 tick)
        r = only(run([N, Q, (116.00, 116.10, 115.20, 115.40)], side))
        assert r.status == E.STOPPED_OUT and r.exit_fill == px(side, "115.25") and not r.exit_gap
        # stop gap: open 115.00 <= SL -> fill open - 1 tick = 114.99; low 115.00 -> outside the range, not clamped
        r = only(run([N, Q, (115.00, 115.10, 115.00, 115.05)], side))
        assert r.status == E.STOPPED_OUT and r.exit_fill == px(side, "114.99") and r.exit_gap
        assert "FILL_OUTSIDE_CANDLE_RANGE" in r.diagnostics
        # same candle touches both: STOP_FIRST
        r = only(run([N, Q, (117.00, 119.80, 115.20, 118.00)], side))
        assert r.status == E.STOPPED_OUT and "SL_TP_SAME_CANDLE_STOP_FIRST" in r.diagnostics
        # entry candle itself, both touched after the fill: STOP_FIRST on candle 51
        r = only(run([(116.45, 119.80, 115.20, 117.00)], side))
        assert r.status == E.STOPPED_OUT and r.exit_index == 51 == r.entry_index
        r = only(run([(116.45, 119.80, 116.30, 119.00)], side))          # entry candle reaches only the TP
        assert r.status == E.TARGET_HIT and r.exit_index == 51
        assert mir is not None


def test_cash_mtm_and_no_double_counted_costs():
    for after, status in (([N, Q, (119.00, 119.75, 118.90, 119.50)], E.TARGET_HIT),
                          ([N, Q, (116.00, 116.10, 115.20, 115.40)], E.STOPPED_OUT)):
        ins = "TEST-BUY"
        st = E.ExecutionStream(ins, TF, market(ins), cfg())
        cs = series(BASE + CONFIRM + after, ins)
        for c in cs:
            st.on_candle(c)
            if c.index == 51:
                assert st.mtm_equity() == (E.UNSCORABLE, None)                    # OQ-13: open position
                assert st.account.cash == Decimal("100000") - st.record(st.account.position).entry_fee
        r = st.records[0]
        assert r.status == status and st.mtm_equity() == ("OK", st.account.cash)
        q, m = F(r.quantity), 1
        gross = q * (F(r.exit_fill) - Fraction("116.46")) * m
        efee, xfee = o_fee(FEES, Fraction("116.46"), q, m), o_fee(FEES, F(r.exit_fill), q, m)
        assert F(r.entry_fee) == efee and F(r.exit_fee) == xfee and F(r.gross_pnl) == gross
        assert F(r.realized_pnl) == gross - efee - xfee
        assert F(st.account.cash) - 100000 == F(r.realized_pnl)                    # each cost counted once
        if status == E.STOPPED_OUT:                                                # loss at the stop within 1%
            assert -F(r.realized_pnl) == F(r.loss_estimate) and -F(r.realized_pnl) <= 1000


def _stream_until(side, after, conf, inject, session=CONT, at=C):
    """Run the stream; `inject` changes the account state just before candle `at` (white-box: another trade)."""
    ins = "TEST-%s" % side
    rows = BASE + CONFIRM + list(after)
    if side == "SELL":
        rows = mirror(rows)
    st = E.ExecutionStream(ins, TF, market(ins, session), conf)
    for c in series(rows, ins):
        if c.index == at:
            inject(st)
        st.on_candle(c)
    return st


def test_position_limit_and_me1_order_with_account_gates():
    def open_pos(st):                                          # an open position from another (synthetic) setup
        other = E.TradeRecord("setup:other", ("bos:x", "sweep:x"), "BUY", "sweep:x", "pattern:x", "confirmation:x", 0, 0,
                              E.ENTERED, (E.D.Transition(E.ENTERED, 1, T0),), sl=Decimal("1"), tp=Decimal("1000"),
                              entry_index=1, entry_fill=Decimal("100"), quantity=Decimal("1"), entry_fee=Decimal("0"))
        st._pos[other.setup_id] = len(st.records)
        st.records.append(other)
        st.account.position = other.setup_id
    for side in ("BUY", "SELL"):
        st = _stream_until(side, [], cfg(), open_pos)          # decided at the close of C (phase 1)
        r = st.records[1]
        assert (r.status, r.disposition_reason, r.reason_code) == (E.NO_TRADE, E.POSITION_LIMIT_REACHED, None)
        assert path(r)[-1] == ("NO_TRADE", 50)
        st = _stream_until(side, [], cfg(min_quantity="1000"), open_pos)          # position limit before CK-13 #5
        assert st.records[1].disposition_reason == E.POSITION_LIMIT_REACHED and st.records[1].reason_code is None
        st = _stream_until(side, [], cfg(entry_ticks=None), open_pos)             # ME-1: config incomplete first
        assert st.records[1].reason_code == E.EXECUTION_CONFIG_INCOMPLETE and st.records[1].disposition_reason is None
        assert st.records[0].status == E.ENTERED                                   # the open position is untouched


def _inject_trade(st, entry_ts, exit_end, pnl, fee=Decimal("10"), sid=None):
    """A closed trade from another (synthetic) setup: cash effects at entry / exit and its holding interval."""
    st.account.intervals.append([entry_ts, exit_end, sid])
    st.account.cash_events += [(entry_ts, True, -fee), (exit_end, False, pnl)]
    st.account.cash += -fee + pnl


def test_daily_loss_limit_two_percent_and_latch():
    day = datetime(2026, 1, 5, tzinfo=timezone.utc)
    for side in ("BUY", "SELL"):
        # exactly 2%: a trade today lost 2000 (10 fee + 1990) of SOD 100000 -> DAILY_LOSS_LIMIT_REACHED
        st = _stream_until(side, [N], cfg(), lambda s: _inject_trade(s, day + timedelta(hours=9, minutes=5),
                                                                     day + timedelta(hours=9, minutes=20),
                                                                     Decimal("-1990")))
        r = st.records[0]
        assert (r.status, r.disposition_reason) == (E.NO_TRADE, E.DAILY_LOSS_LIMIT_REACHED) and r.reason_code is None
        assert st.account.latched_days == {"2026-01-05": 50}
        # just below 2% (1999.99): with OQ-13 the day is measurable -> entry allowed
        st = _stream_until(side, [N], cfg(), lambda s: _inject_trade(s, day + timedelta(hours=9, minutes=5),
                                                                     day + timedelta(hours=9, minutes=20),
                                                                     Decimal("-1989.99")))
        r = st.records[0]
        assert r.status == E.ENTERED and r.equity_at_decision == Decimal("98000.01") and not st.account.latched_days
        # yesterday's loss is inside the start-of-day equity: today's loss is 0 -> entry allowed
        st = _stream_until(side, [N], cfg(), lambda s: _inject_trade(s, day - timedelta(hours=3),
                                                                     day - timedelta(hours=2), Decimal("-5000")), at=0)
        assert st.records[0].status == E.ENTERED and st.records[0].equity_at_decision == Decimal("94990")
        # the day boundary falls inside the candle in which a position was exited (23:58 -> 00:03): intrabar-ambiguous
        st = _stream_until(side, [N], cfg(), lambda s: _inject_trade(s, day - timedelta(hours=1),
                                                                     day + timedelta(minutes=3), Decimal("-100"),
                                                                     sid="setup:other"), at=0)
        r = st.records[0]
        assert r.status == E.CONFIRMED and r.result == E.UNSCORABLE and r.blocked_by == ("OQ-13",)
        assert "intrabar" in r.detail and st.pending == [] and st.account.position is None

    # latch: once reached, the rest of the day stays rejected even if equity is back
    def latched(s):
        s.account.latched_days["2026-01-05"] = 7
    st = _stream_until("BUY", [N], cfg(), latched)
    assert st.records[0].disposition_reason == E.DAILY_LOSS_LIMIT_REACHED and st.account.cash == Decimal("100000")


def test_session_rules_overnight_and_final_candle():
    t = lambda k: (T0 + timedelta(minutes=5 * k)).timestamp()
    final = {"kind": "exchange_sessions", "timezone": "Asia/Kolkata",
             "sessions": [[t(0), t(51)], [t(51) + 86400, t(120) + 86400]]}           # C = 50 is the session's last
    inside = {"kind": "exchange_sessions", "timezone": "Asia/Kolkata", "sessions": [[t(0), t(80)]]}
    for side in ("BUY", "SELL"):
        r = only(run([N], side, session=final))
        assert (r.status, r.disposition_reason, r.reason_code) == (E.EXPIRED, E.SESSION_CLOSED, None)
        assert path(r)[-1] == ("EXPIRED", 50) and r.entry_fill is None                # never entered next session
        assert only(run([N], side, session=inside)).status == E.ENTERED
    r = only(run([N], conf=cfg(trading_day_start=None)))                              # ME-2: 24/7 needs a day start
    assert r.reason_code == E.EXECUTION_CONFIG_INCOMPLETE and "trading_day_start" in r.detail
    early = {"kind": "exchange_sessions", "timezone": "UTC", "sessions": [[t(60), t(90)]]}   # calendar starts later
    r = only(run([N], session=early))
    assert r.reason_code == E.EXECUTION_CONFIG_INCOMPLETE and "coverage" in r.detail


# ---------------------------------------------------------------- stream input validation (F-E1 / F-D2, 17.V)
def _forged(c, **kw):
    """A Candle object whose fields were changed after construction (bypassing Module A's checks)."""
    import dataclasses
    x = object.__new__(Candle)
    for f in dataclasses.fields(Candle):
        object.__setattr__(x, f.name, kw.get(f.name, getattr(c, f.name)))
    return x


def _fp(st):
    import pickle
    return pickle.dumps(st)                                  # byte-for-byte fingerprint (Module E + its Module D)


def _invalid_versions(sr, k):
    """Invalid stand-ins for candle k, keeping its prices (so a valid version WOULD fill / exit)."""
    c = sr[k]
    return {
        "backward timestamp": Candle(k, sr[k - 2].ts, c.open, c.high, c.low, c.close, c.volume),
        "equal timestamp": Candle(k, sr[k - 1].ts, c.open, c.high, c.low, c.close, c.volume),
        "index skip": Candle(k + 1, c.ts, c.open, c.high, c.low, c.close, c.volume),
        "index repeat": sr[k - 1],
        "high below low": _forged(c, high=c.low - 1.0),
        "NaN close": _forged(c, close=float("nan")),
        "string open": _forged(c, open=str(c.open)),
        "not a Candle": (k, c.ts, c.open, c.high, c.low, c.close),
    }


def test_invalid_entry_candle_cannot_expire_or_fill_a_pending_setup():
    """F-E1: an invalid candle C+1 raises before phase 2: no EXPIRED / NO_TRADE / ENTERED, pending, records, candles,
    account and data state byte-identical; the valid retry then enters exactly as the batch run does."""
    for side in ("BUY", "SELL"):
        ins = "TEST-%s" % side
        rows = BASE + CONFIRM + [N, Q]
        if side == "SELL":
            rows = mirror(rows)
        sr = list(series(rows, ins))
        st = E.ExecutionStream(ins, TF, market(ins), cfg())
        for c in sr[:51]:
            st.on_candle(c)
        sid = st.pending[0]
        assert st.record(sid).status == E.CONFIRMED
        for name, bad in _invalid_versions(sr, 51).items():
            before = _fp(st)
            assert raises(ValueError, st.on_candle, bad), name
            assert _fp(st) == before, "%s: state changed by a rejected candle" % name
            assert st.pending == [sid] and st.record(sid).status == E.CONFIRMED and st.account.position is None
        for c in sr[51:]:                                                   # valid retry
            st.on_candle(c)
        batch = E.analyze_execution(series(rows, ins), ins, TF, market(ins), cfg())
        assert st.records == batch.records and st.snapshots == batch.snapshots
        assert st.records[0].status == E.ENTERED and st.records[0].entry_index == 51


def test_invalid_candle_cannot_execute_or_record_an_exit():
    """F-E1: with a position open, an invalid candle whose prices go through the stop records no exit (no STOPPED_OUT,
    no cash change); the valid candle then stops the trade exactly as in batch."""
    stop = (115.00, 115.10, 114.90, 115.05)                                # gaps through the BUY stop 115.26
    for side in ("BUY", "SELL"):
        ins = "TEST-%s" % side
        rows = BASE + CONFIRM + [N, Q, stop]
        if side == "SELL":
            rows = mirror(rows)
        sr = list(series(rows, ins))
        st = E.ExecutionStream(ins, TF, market(ins), cfg())
        for c in sr[:53]:
            st.on_candle(c)
        pos = st.account.position
        assert pos is not None and st.record(pos).status == E.ENTERED
        for name, bad in _invalid_versions(sr, 53).items():
            before = _fp(st)
            assert raises(ValueError, st.on_candle, bad), name
            assert _fp(st) == before, "%s: state changed by a rejected candle" % name
            assert st.record(pos).status == E.ENTERED and st.record(pos).exit_fill is None
        st.on_candle(sr[53])
        batch = E.analyze_execution(series(rows, ins), ins, TF, market(ins), cfg())
        assert st.records == batch.records and st.snapshots == batch.snapshots
        assert st.record(pos).status == E.STOPPED_OUT and st.record(pos).exit_index == 53


def test_invalid_data_events_do_not_touch_execution_state():
    """F-D2 through Module E: a data event inside a candle (stream) is rejected before ME-4 can expire the pending
    setup; a candle opening before a recorded event is rejected without transitions; batch rejects the same events
    before any candle is processed."""
    ins = "TEST-BUY"
    rows = BASE + CONFIRM + [N, Q]
    sr = list(series(rows, ins))
    st = E.ExecutionStream(ins, TF, market(ins), cfg())
    for c in sr[:51]:
        st.on_candle(c)
    sid = st.pending[0]
    t51 = sr[51].ts                                                         # = close of 50 (contiguous)
    before = _fp(st)
    assert raises(ValueError, st.mark_data_interrupted, t51 - timedelta(minutes=4))   # inside candle 50
    assert _fp(st) == before and st.pending == [sid] and st.record(sid).status == E.CONFIRMED
    # recorded at the boundary (valid): ME-4 expires the pending setup, as approved
    st.mark_data_interrupted(t51)
    st.mark_data_resumed(t51 + timedelta(minutes=1))                        # after 51's open: only caught at 51
    before = _fp(st)
    assert raises(ValueError, st.on_candle, sr[51]) and _fp(st) == before
    assert st.record(sid).status == E.EXPIRED                               # from the valid interruption only
    for evs in ([(51, "DATA_INTERRUPTED", t51 - timedelta(minutes=4)), (51, "DATA_RESUMED", t51)],
                [(51, "DATA_INTERRUPTED", t51), (51, "DATA_RESUMED", t51 + timedelta(minutes=1))]):
        assert raises(ValueError, E.analyze_execution, series(rows, ins), ins, TF, market(ins), cfg(),
                      data_events=evs)

def test_next_candle_unavailable_and_data_interruption():
    for side in ("BUY", "SELL"):
        r = only(run([N, Q], side, gaps=(51,)))                                      # 13:15 missing, next is 13:20
        assert (r.status, r.disposition_reason) == (E.EXPIRED, E.NEXT_CANDLE_UNAVAILABLE) and path(r)[-1] == ("EXPIRED", 51)
        # ME-4, contiguous C / C+1: the only valid event instant is the boundary 13:15 (F-D2); on-time C+1 too
        tb = T0 + timedelta(minutes=5 * 51)
        r = only(run([N, Q], side, data_events=[(51, "DATA_INTERRUPTED", tb), (51, "DATA_RESUMED", tb)]))
        assert (r.status, r.disposition_reason) == (E.EXPIRED, E.NEXT_CANDLE_UNAVAILABLE)
        assert path(r)[-1] == ("EXPIRED", 50) and r.history[-1].ts == tb and r.history[-1].data_state == "DATA_INTERRUPTED"
        assert r.entry_fill is None
        # ME-4 across a real gap (13:15 missing, 51 opens 13:20): events inside the gap [13:15, 13:20]
        ti, tr = T0 + timedelta(minutes=5 * 50 + 6), T0 + timedelta(minutes=5 * 50 + 8)
        r = only(run([N, Q], side, gaps=(51,), data_events=[(51, "DATA_INTERRUPTED", ti), (51, "DATA_RESUMED", tr)]))
        assert (r.status, r.disposition_reason) == (E.EXPIRED, E.NEXT_CANDLE_UNAVAILABLE)
        assert path(r)[-1] == ("EXPIRED", 50) and r.history[-1].ts == ti and r.entry_fill is None
        # the same 13:16 / 13:18 events on contiguous candles lie inside candle 51 -> rejected, nothing built
        assert raises(ValueError, run, [N, Q], side, data_events=[(51, "DATA_INTERRUPTED", ti),
                                                                  (51, "DATA_RESUMED", tr)])
    # end of data right after C: no next candle yet -> stays CONFIRMED, listed as awaiting (no fabricated fill)
    rep = run([])
    r = only(rep)
    assert r.status == E.CONFIRMED and r.result is None and rep.end_of_data.awaiting_next_candle == (r.setup_id,)


def test_open_position_across_interruption_and_end_of_data():
    for side in ("BUY", "SELL"):
        ti = T0 + timedelta(minutes=5 * 53 + 1)                # 52 closes 13:25; 53 opens 13:30 (gap) -> in window
        tr = T0 + timedelta(minutes=5 * 53 + 5)                # exactly 53's open (inclusive bound)
        # interrupted between 52 and 53; 53 opens through the stop: filled at the OBSERVED open - 1 tick
        rep = run([N, Q, (115.00, 115.10, 114.90, 115.05)], side, gaps=(53,),
                  data_events=[(53, "DATA_INTERRUPTED", ti), (53, "DATA_RESUMED", tr)])
        r = only(rep)
        assert r.status == E.STOPPED_OUT and r.exit_index == 53 and r.exit_fill == px(side, "114.99")
        assert r.data_gaps == (("DATA_INTERRUPTED", ti), ("DATA_RESUMED", tr))
        assert r.history[-1].data_state == "DATA_RESUMED" and r.history[-2].status == "ENTERED"
        # data ends with the position open: OPEN_UNRESOLVED, not force-closed, not in closed results
        rep = run([N, Q], side)
        r = only(rep)
        eod = rep.end_of_data
        assert r.status == E.ENTERED and r.exit_fill is None
        assert [x.status for x in eod.open_unresolved] == ["OPEN_UNRESOLVED"]
        assert eod.open_unresolved[0].history[-1].index == 52 and eod.last_close == px(side, "116.60")
        assert eod.closed_trades == 0 and eod.realized_pnl == 0 and eod.cash == Decimal(100000) - r.entry_fee


def test_no_trade_without_pool_and_disposition_fields():
    # entry fill above every ACTIVE BSL (> 121.10): no target -> NO_TRADE NO_ELIGIBLE_OPPOSING_POOL (OQ-2)
    for side in ("BUY", "SELL"):
        conf = cfg(max_gap_ticks=1000)
        r = only(run([(121.20, 121.30, 121.10, 121.25)], side, conf=conf))
        assert r.disposition_reason == E.NO_ELIGIBLE_OPPOSING_POOL and r.reason_code is None, r
        # ME-1: NO_ELIGIBLE_OPPOSING_POOL precedes CK-13 #3 (the same open is also a gap far above 0.2975)
        r = only(run([(121.20, 121.30, 121.10, 121.25)], side))
        assert r.disposition_reason == E.NO_ELIGIBLE_OPPOSING_POOL and r.reason_code is None
        # fill between the two pools: the farther pool (121.10) is the nearest ABOVE the actual entry fill
        r = only(run([(119.75, 119.90, 119.70, 119.80)], side, conf=conf))
        assert r.tp_pool_id.endswith(":3:fixed-window-strict:L2R2") and r.tp == px(side, "121.09")


def test_duplicate_intake_and_terminal_lifecycle():
    ins = "TEST-BUY"
    st = E.ExecutionStream(ins, TF, market(ins), cfg())
    for c in series(BASE + CONFIRM + [N], ins):
        st.on_candle(c)
    d_rec = st.d.setups[0]
    before = list(st.records)
    assert st.intake(d_rec, 50) is None and st.intake_diagnostics[-1].code == E.INTAKE_DUPLICATE_SETUP
    assert st.records == before
    from dataclasses import replace
    assert st.intake(replace(d_rec, status="PATTERN_DETECTED"), 51) is None
    assert st.intake_diagnostics[-1].code == E.INTAKE_NOT_CONFIRMED
    r = st.records[0]
    assert r.status == E.ENTERED
    for bad in (E.NO_TRADE, E.EXPIRED, E.ENTERED, E.CONFIRMED):
        assert raises(E.LifecycleError, E._advance, r, bad, 52, T0, None, None, "NORMAL")
    done = E._advance(r, E.STOPPED_OUT, 52, T0, None, None, "NORMAL")
    for s in (E.TARGET_HIT, E.STOPPED_OUT, E.ENTERED, E.NO_TRADE):
        assert raises(E.LifecycleError, E._advance, done, s, 53, T0, None, None, "NORMAL")
    assert raises(E.LifecycleError, E._advance, r, E.STOPPED_OUT, 40, T0, None, None, "NORMAL")   # backwards
    confirmed = st.records[0].__class__(**{**r.__dict__, "status": E.CONFIRMED, "history": r.history[:-1]})
    assert raises(E.LifecycleError, E._advance, confirmed, E.TARGET_HIT, 51, T0, None, None, "NORMAL")


def test_no_fabricated_fill_or_exit():
    for after in ([], [N], [N, Q], [N, Q, Q, Q]):
        rep = run(after)
        r = only(rep)
        n = len(BASE + CONFIRM + after)
        for t in r.history:
            assert 0 <= t.index < n
        if r.entry_index is not None:
            assert r.entry_index == 51 and r.entry_open == Decimal("116.45")
        if r.exit_index is not None:
            assert r.exit_index < n
        assert r.status in (E.CONFIRMED, E.ENTERED)                  # quiet candles never produce an exit


def test_determinism_parity_prefix_replay_and_no_lookahead():
    after = [N, Q, Q, (119.00, 119.75, 118.90, 119.50), Q]
    for side in ("BUY", "SELL"):
        ins = "TEST-%s" % side
        rows = BASE + CONFIRM + after
        if side == "SELL":
            rows = mirror(rows)
        cs, mk, conf = series(rows, ins), market(ins), cfg()
        a, b = E.analyze_execution(cs, ins, TF, mk, conf), E.analyze_execution(cs, ins, TF, mk, conf)
        assert repr(a.records) == repr(b.records) and a.snapshots == b.snapshots and a.outputs == b.outputs
        st = E.ExecutionStream(ins, TF, mk, conf)
        outs = [(c.index, st.on_candle(c)) for c in cs]
        assert outs == a.outputs and st.records == a.records and st.snapshots == a.snapshots
        for k in range(len(cs)):                                       # prefix replay at every candle
            p = E.analyze_execution(cs.upto(k), ins, TF, mk, conf)
            assert p.snapshots[-1] == a.snapshots[k], k
        assert no_lookahead_violations(lambda s: E.detect_execution(s, ins, TF, mk, conf), cs) == []
        for cut in (C, C + 1, C + 2):                                  # the future never changes the past
            alt = CandleSeries.from_rows([(x.ts, x.open, x.high + (2.0 if x.index > cut else 0),
                                           x.low - (2.0 if x.index > cut else 0), x.close) for x in cs], ins, TF)
            pa = E.analyze_execution(alt, ins, TF, mk, conf)
            assert pa.snapshots[:cut + 1] == a.snapshots[:cut + 1], cut


def test_buy_sell_symmetry():
    conf = cfg(fee_schedule=dict(ZERO_FEES, per_order="1.25", per_unit="0.01"))   # price-independent fees
    for after in ([N, Q, (119.00, 119.75, 118.90, 119.50)], [N, Q, (116.00, 116.10, 115.20, 115.40)],
                  [(116.75, 116.90, 116.70, 116.80)], [N, Q]):
        b, s = only(run(after, "BUY", conf=conf)), only(run(after, "SELL", conf=conf))
        assert path(b) == path(s) and b.status == s.status and b.reason_code == s.reason_code
        assert (b.side, s.side) == ("BUY", "SELL")
        assert b.quantity == s.quantity and b.net_rr == s.net_rr and b.loss_estimate == s.loss_estimate
        assert b.realized_pnl == s.realized_pnl and b.entry_fee == s.entry_fee
        for f in ("entry_fill", "sl", "tp", "exit_fill"):
            if getattr(b, f) is not None:
                assert getattr(b, f) + getattr(s, f) == 200, f
        assert b.setup_id.replace("SSL", "X").replace("BUY", "S") == s.setup_id.replace("BSL", "X").replace("SELL", "S")


def test_randomized_against_independent_oracle():
    rnd = random.Random(20261124)
    n_entered = 0
    for _ in range(80):
        over = dict(entry_ticks=rnd.randint(0, 3), stop_exit_ticks=rnd.randint(0, 3), sl_buffer_ticks=rnd.randint(0, 5),
                    tp_offset_ticks=rnd.choice([1, 2, 100, 180, 203, 230]), max_gap_ticks=rnd.choice([5, 20, 50]),
                    quantity_step=rnd.choice(["1", "5", "25"]), initial_margin_rate=rnd.choice(["0.2", "1.5", "4"]),
                    fee_schedule=dict(FEES, rate=rnd.choice(["0", "0.0001", "0.0005"]),
                                      per_order=rnd.choice(["0", "2.5", "40"]), per_unit=rnd.choice(["0", "0.02"])))
        over["min_quantity"] = str(int(over["quantity_step"]) * rnd.choice([1, 4, 40]))
        o = round(rnd.uniform(115.20, 116.80), 2)
        sl = 115.28 - 0.01 * over["sl_buffer_ticks"]
        low = round(min(o, 116.4) - 0.05, 2)
        if o > sl + 0.005:
            low = max(low, round(sl + 0.01, 2))                      # keep the entry candle off the stop
        entry = (o, round(max(o, 116.5) + 0.1, 2), min(low, o), round(o + 0.02, 2))
        conf_d = dict(BASE_CFG, **over)
        ex = oracle(Fraction(str(o)), conf_d)
        r = only(run([entry], conf=cfg(**over)))
        code = r.reason_code or r.disposition_reason or ("ENTERED" if r.entry_index is not None and r.quantity else r.status)
        assert code == ex["code"], (over, o, code, ex)
        if ex["code"] == "ENTERED":
            n_entered += 1
            assert F(r.quantity) == ex["q"] and close(r.net_rr, ex["rr"]) and F(r.loss_estimate) == ex["loss"]
            assert F(r.entry_fill) == ex["fill"] and F(r.tp) == ex["tp"] and F(r.sl) == ex["sl"]
    assert n_entered >= 10


def test_boundaries_found_by_mutation_check():
    # Loss(q) == budget exactly is allowed (Loss <= B): zero fees, dist 116.46 - 115.25 = 1.21, equity 12100 -> B 121,
    # q = 100 gives Loss 121.00 exactly
    for side in ("BUY", "SELL"):
        r = only(run([N], side, conf=cfg(fee_schedule=ZERO_FEES, starting_equity="12100")))
        assert r.status == E.ENTERED and r.quantity == 100 and r.loss_estimate == r.risk_budget == Decimal("121.00")
        # a pool exactly AT the entry fill is not above it: open 119.69 + 1 tick = 119.70 = pool 42 -> pool 3 instead
        r = only(run([(119.69, 119.90, 119.60, 119.80)], side, conf=cfg(max_gap_ticks=1000)))
        assert r.entry_fill == px(side, "119.70") and r.tp_pool_id.endswith(":3:fixed-window-strict:L2R2")
        # CK-14 revalidation: a 50 per-order fee makes net R:R < 1 below q = 100 ((q x 3.23 - 100) / (q x 1.21 + 100)
        # >= 1 <=> q >= 99.01); margin rate 17 caps BUY q at 50 (116.46 x 50 x 17 = 98991) -> INSUFFICIENT_MARGIN,
        # never an entry at a quantity that fails the 1:1 check
        conf = cfg(fee_schedule=dict(ZERO_FEES, per_order="50"), initial_margin_rate="17")
    r = only(run([N], "BUY", conf=conf))
    assert (r.status, r.reason_code) == (E.NO_TRADE, E.INSUFFICIENT_MARGIN) and F(r.risk_quantity) == 743
    # ME-2 day boundary before trading_day_start: 13:15Z with a 14:00 start belongs to the day that began on
    # 2026-01-04 14:00Z; a 2% loss earlier on 2026-01-05 (09:05-09:20) is in that same trading day
    day_start = datetime(2026, 1, 4, 14, 0, tzinfo=timezone.utc)
    st = _stream_until("BUY", [N], cfg(trading_day_start="14:00"),
                       lambda s: _inject_trade(s, day_start + timedelta(hours=19, minutes=5),
                                               day_start + timedelta(hours=19, minutes=20), Decimal("-1990")))
    assert st.records[0].disposition_reason == E.DAILY_LOSS_LIMIT_REACHED and st.account.latched_days == {"2026-01-04": 50}


# ---------------------------------------------------------------- OQ-13 (OWNER APPROVED 24 Nov 2026)
def legs(start_close, spec):
    """Rows after the neutral entry candles: ("leg", n, target) uses the same leg shape as BASE; ("c", row) is literal."""
    rows, cur = [], start_close
    for item in spec:
        if item[0] == "leg":
            cur = _leg(rows, cur, item[1], item[2])
        else:
            rows.append(item[1])
            cur = item[1][3]
    return rows


# (a) two CLOSED trades on one day, organic (Modules A-D unchanged): BUY enters 51, stopped at 58 (low 115.00); bearish
#     CHoCH@58, REVERSAL_CONFIRMING bearish BOS@64, BSL sweep@68 (pool swing:high:61 @ 116.00), Bearish Engulfing 69-70
#     (high 115.99, low 115.70), confirmation close 115.65 @71 -> SELL entry 72 open 115.65, fill 115.64;
#     SL 116.05 + 0.02 = 116.07; TP pool swing:low:64 @ 114.50 -> TP 114.51; target reached on 76 (low 114.30).
TWO_CLOSED = [N, Q] + legs(116.60, [("leg", 3, 117.0), ("leg", 3, 115.1), ("leg", 3, 115.9), ("leg", 3, 114.6),
                                    ("leg", 3, 115.3), ("c", (115.30, 116.05, 115.25, 115.80)),
                                    ("c", (115.80, 115.98, 115.78, 115.95)), ("c", (115.97, 115.99, 115.70, 115.75)),
                                    ("c", (115.75, 115.78, 115.60, 115.65)), ("c", (115.65, 115.70, 115.55, 115.60)),
                                    ("c", (115.60, 115.65, 115.50, 115.55)), ("leg", 3, 114.40)])
# (b) the SELL setup confirms at 71 while the BUY position is still OPEN (every low >= 115.27 > SL 115.26)
TWO_OPEN = [N, Q] + legs(116.60, [("leg", 3, 117.0), ("leg", 2, 115.8), ("c", (115.80, 115.84, 115.30, 115.35)),
                                  ("leg", 3, 116.1), ("leg", 2, 115.5), ("c", (115.50, 115.55, 115.27, 115.28)),
                                  ("c", (115.28, 115.50, 115.27, 115.45)), ("c", (115.45, 115.70, 115.42, 115.65)),
                                  ("c", (115.65, 115.90, 115.62, 115.85)), ("c", (115.85, 116.25, 115.80, 116.00)),
                                  ("c", (116.00, 116.10, 115.98, 116.08)), ("c", (116.10, 116.12, 115.90, 115.95)),
                                  ("c", (115.95, 115.97, 115.80, 115.85)), ("c", (115.85, 115.90, 115.78, 115.82))])
MTM_CFG = dict(mtm_exit_slippage_ticks=2)


def test_oq13_mtm_long_and_short_open_position_independent():
    fees = dict(FEES, per_order="1.5")
    for side in ("BUY", "SELL"):
        rep = run([N, Q, (116.60, 116.80, 116.10, 116.20)], side, conf=cfg(fee_schedule=fees, **MTM_CFG))
        r = only(rep)
        assert r.status == E.ENTERED
        q, ef, efee = F(r.quantity), F(r.entry_fill), F(r.entry_fee)
        assert efee == o_fee(fees, ef, q, 1)
        logs = {k: (st, eq) for k, st, eq, *_ in _mtm_log(side, [N, Q, (116.60, 116.80, 116.10, 116.20)],
                                                           cfg(fee_schedule=fees, **MTM_CFG)).mtm_log}
        for k, close_buy in ((51, "116.55"), (52, "116.60"), (53, "116.20")):
            mark = Fraction(close_buy) if side == "BUY" else 200 - Fraction(close_buy)
            est = mark - Fraction(2, 100) if side == "BUY" else mark + Fraction(2, 100)   # adverse slippage, 2 ticks
            unreal = (est - ef) * q if side == "BUY" else (ef - est) * q
            xfee = o_fee(fees, est, q, 1)                                           # closing fee, once
            expected = Fraction(100000) - efee + unreal - xfee                        # entry fee only via cash
            st, eq = logs[k]
            assert st == "OK" and F(eq) == expected, (side, k, F(eq), expected)


def _args(side, after, conf):
    ins = "TEST-%s" % side
    rows = BASE + CONFIRM + list(after)
    if side == "SELL":
        rows = mirror(rows)
    return series(rows, ins), ins, TF, market(ins), conf


def _mtm_log(side, after, conf):
    cs, ins, tf, mk, conf = _args(side, after, conf)
    st = E.ExecutionStream(ins, tf, mk, conf)
    for c in cs:
        st.on_candle(c)
    return st


def test_oq13_slippage_direction_fee_once_and_flat_equals_cash():
    for side in ("BUY", "SELL"):
        st = _mtm_log(side, [N, Q, Q, (119.00, 119.75, 118.90, 119.50)], cfg(**MTM_CFG))
        r = st.records[0]
        log = {k: (s, eq) for k, s, eq, *_ in st.mtm_log}
        st_, (m, est, unreal, xfee), _ = st.estimate_exit(r, px(side, "116.60"))
        assert (est < m) if side == "BUY" else (est > m)                        # adverse for LONG and SHORT
        assert abs(F(est) - F(m)) == Fraction(2, 100)
        # MTM - cash = unrealized - estimated exit fee: the entry fee is in cash only, nothing else is deducted
        cash_open = Fraction(100000) - F(r.entry_fee)
        assert F(log[52][1]) - cash_open == F(unreal) - F(xfee)
        # flat after the target: MTM equals cash, and cash - start equals realized P&L (each cost counted once)
        assert r.status == E.TARGET_HIT and log[54] == ("OK", st.account.cash)
        assert F(st.account.cash) - 100000 == F(r.realized_pnl)


def test_oq13_day_start_snapshot_with_open_position():
    # 24/7 day starting 13:25Z: the boundary falls while the BUY entered at 13:15 is open. The mark is the latest
    # COMPLETED close at or before 13:25: candle 52 (13:20-13:25, close 116.60), never candle 53.
    for side in ("BUY", "SELL"):
        st = _mtm_log(side, [N, Q, (116.60, 116.70, 116.30, 116.35), Q],
                      cfg(trading_day_start="13:25", **MTM_CFG))
        r = st.records[0]
        q, ef = F(r.quantity), F(r.entry_fill)
        mark = Fraction("116.60") if side == "BUY" else Fraction("83.40")
        est = mark - Fraction(2, 100) if side == "BUY" else mark + Fraction(2, 100)
        unreal = (est - ef) * q if side == "BUY" else (ef - est) * q
        expected = Fraction(100000) - F(r.entry_fee) + unreal - o_fee(FEES, est, q, 1)
        status, sod, _ = st.account.sod["2026-01-05"]
        assert status == "OK" and F(sod) == expected, (side, F(sod), expected)
        assert st.account.sod["2026-01-04"][1] == Decimal("100000")          # the earlier day began flat
        # boundary 13:27 falls INSIDE candle 53 (13:25-13:30): that candle is not completed before the boundary, so
        # the mark is still candle 52's close (116.60), not candle 53's (116.35)
        st = _mtm_log(side, [N, Q, (116.60, 116.70, 116.30, 116.35), Q], cfg(trading_day_start="13:27", **MTM_CFG))
        status, sod, _ = st.account.sod["2026-01-05"]
        assert status == "OK" and F(sod) == expected, (side, F(sod), expected)


def test_oq13_missing_configuration_is_unscorable_and_suspends_entries():
    for side in ("BUY", "SELL"):
        st = _mtm_log(side, [N, Q], cfg())                                    # no mtm_exit_slippage_ticks
        assert st.mtm_equity() == (E.UNSCORABLE, None) and st.records[0].status == E.ENTERED
        assert st.mtm_log[-1][1] == E.UNSCORABLE and "mtm_exit_slippage_ticks" in st.account.unscorable_days["2026-01-05"][1]
        assert st.estimate_exit(st.records[0], None)[0] == E.UNSCORABLE            # missing mark
        # organic two-trade day: trade 1 was open (unmeasurable) earlier today -> the SELL setup at 71 is suspended
        rows = BASE + CONFIRM + TWO_CLOSED
        if side == "SELL":
            rows = mirror(rows)
        ins = "TEST-%s" % side
        rep = E.analyze_execution(series(rows, ins), ins, TF, market(ins), cfg())
        t1, t2 = rep.records
        assert t1.status == E.STOPPED_OUT and t2.status == E.CONFIRMED and t2.result == E.UNSCORABLE
        assert t2.blocked_by == ("OQ-13",) and t2.entry_fill is None and t2.reason_code is None


def test_oq13_intraday_mtm_latch_without_forced_close():
    day = datetime(2026, 1, 5, tzinfo=timezone.utc)
    for side in ("BUY", "SELL"):
        # 1500 realized loss earlier today; after entry, candle 52 closes at 115.40 (low 115.30 > SL 115.26): the
        # unrealized loss at that mark takes the day past 2% -> latched at 52; the position keeps its SL / TP and
        # reaches the target at 54 (no forced close)
        st = _stream_until(side, [N, (116.45, 116.50, 115.30, 115.40), Q, (119.00, 119.75, 118.90, 119.50)],
                           cfg(**MTM_CFG), lambda s: _inject_trade(s, day + timedelta(hours=1), day + timedelta(hours=2),
                                                                   Decimal("-1490")), at=0)
        r = st.records[0]
        assert st.account.latched_days == {"2026-01-05": 52}, st.account.latched_days
        assert r.status == E.TARGET_HIT and r.exit_index == 54
        k52 = [x for x in st.mtm_log if x[0] == 52][0]
        assert k52[5] == "REACHED" and k52[4] >= Decimal("2000")             # SOD 100000 at 00:00 (flat)
        assert F(st.account.cash) > 98000                                     # flat measure now below 2%: still latched


def test_organic_two_trades_same_day():
    for side in ("BUY", "SELL"):
        rows = BASE + CONFIRM + TWO_CLOSED
        if side == "SELL":
            rows = mirror(rows)
        ins = "TEST-%s" % side
        rep = E.analyze_execution(series(rows, ins), ins, TF, market(ins), cfg(**MTM_CFG))
        assert len(rep.records) == 2
        t1, t2 = rep.records
        other = "SELL" if side == "BUY" else "BUY"
        assert (t1.side, t1.status, t1.exit_index, t1.exit_fill) == (side, E.STOPPED_OUT, 58, px(side, "115.25"))
        assert path(t2)[:5] == [("CHOCH_DETECTED", 58), ("BOS_CONFIRMED", 64), ("SWEEP_DETECTED", 68),
                                ("PATTERN_DETECTED", 70), ("CONFIRMED", 71)]
        assert (t2.side, t2.status, t2.entry_index, t2.exit_index) == (other, E.TARGET_HIT, 72, 76)
        assert t2.entry_fill == px(side, "115.64") and t2.sl == px(side, "116.07") and t2.tp == px(side, "114.51")
        assert t2.tp_pool_id.endswith(":64:fixed-window-strict:L2R2")
        # trade 2 is sized on the equity left by trade 1 (independent: start - fees + gross)
        q1 = F(t1.quantity)
        gross1 = (F(t1.exit_fill) - F(t1.entry_fill)) * q1 if side == "BUY" else (F(t1.entry_fill) - F(t1.exit_fill)) * q1
        cash1 = Fraction(100000) - o_fee(FEES, F(t1.entry_fill), q1, 1) + gross1 - o_fee(FEES, F(t1.exit_fill), q1, 1)
        assert F(t2.equity_at_decision) == cash1 and F(t2.risk_budget) == cash1 / 100
        assert rep.end_of_data.closed_trades == 2 and F(rep.end_of_data.realized_pnl) == F(t1.realized_pnl) + F(t2.realized_pnl)
        assert F(rep.end_of_data.cash) - 100000 == F(rep.end_of_data.realized_pnl)
        st = E.ExecutionStream(ins, TF, market(ins), cfg(**MTM_CFG))
        cs = series(rows, ins)
        for c in cs:
            st.on_candle(c)
        assert not st.account.latched_days and not st.account.unscorable_days
        for k in (58, 64, 71, 72, 76):                                       # prefix replay through both trades
            assert E.analyze_execution(cs.upto(k), ins, TF, market(ins), cfg(**MTM_CFG)).snapshots[-1] == st.snapshots[k]


def test_organic_position_limit_with_open_position():
    for side in ("BUY", "SELL"):
        rows = BASE + CONFIRM + TWO_OPEN
        if side == "SELL":
            rows = mirror(rows)
        ins = "TEST-%s" % side
        rep = E.analyze_execution(series(rows, ins), ins, TF, market(ins), cfg(**MTM_CFG))
        t1, t2 = rep.records
        assert t1.status == E.ENTERED and t1.exit_index is None                  # still open (every low >= 115.27)
        assert (t2.status, t2.disposition_reason, t2.reason_code) == (E.NO_TRADE, E.POSITION_LIMIT_REACHED, None)
        assert path(t2)[-1] == ("NO_TRADE", 71)
        assert [x.setup_id for x in rep.end_of_data.open_unresolved] == [t1.setup_id]


def test_two_setups_pending_same_open_whitebox():
    """Modules A-D cannot produce two CONFIRMED setups on one candle: one current BOS, one pending candidate per BOS,
    and a new BOS needs an opposite CHoCH / BOS that first invalidates the pending candidate (17.S / 17.U). This
    white-box test duplicates the pending record to exercise the phase-2 re-check: the first enters, the second gets
    POSITION_LIMIT_REACHED at the same open."""
    from dataclasses import replace as _r
    ins = "TEST-BUY"
    st = E.ExecutionStream(ins, TF, market(ins), cfg(**MTM_CFG))
    cs = series(BASE + CONFIRM + [N], ins)
    for c in cs:
        if c.index == 51:
            twin = _r(st.records[0], setup_id="setup:twin")
            st._pos[twin.setup_id] = len(st.records)
            st.records.append(twin)
            st.pending.append(twin.setup_id)
        st.on_candle(c)
    a, b = st.records
    assert a.status == E.ENTERED and (b.status, b.disposition_reason) == (E.NO_TRADE, E.POSITION_LIMIT_REACHED)
    assert path(b)[-1] == ("NO_TRADE", 51)


def test_paper_only_no_order_path():
    import scanner_v6
    from scanner_v6.exit import execution, execution_config, sizing, stop_loss, targets, trade_management
    assert scanner_v6.PAPER_ONLY is True and scanner_v6.PLACES_ORDERS is False
    for mod in (execution, execution_config, sizing, stop_loss, targets, trade_management):
        src = open(mod.__file__).read()
        for bad in ("import requests", "import socket", "urllib", "http.client", "kite", "alpaca", "broker.", "paper.py",
                    "scanner_v4", "subprocess", "place_order", "os.environ"):
            assert bad not in src, (mod.__name__, bad)


if __name__ == "__main__":
    run_main([v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)])
