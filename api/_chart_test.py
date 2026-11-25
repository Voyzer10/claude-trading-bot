"""
api/_chart_test.py - Chart Testing endpoint: analyze extracted chart candles with any scanner version (v6, v5, v4, v3, v2, rules)
and return structured markings (CHoCH, BOS, liquidity pools, sweeps, FVG/OB zones, signals, entry/SL/TP, and checklist)
so the dashboard can draw them directly onto the uploaded chart image.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

router = APIRouter()

STRATEGY_META = {
    "v6": {
        "name": "V6 SMC Scanner",
        "summary": "CHoCH -> Reversal BOS -> Liquidity Sweep -> Candlestick Pattern -> 3-Candle Confirmation -> Structural SL & Opposing Liquidity TP",
    },
    "v5": {
        "name": "Scanner v5 (0.146 Level)",
        "summary": "Confirmed swing leg (L -> H) retracing to 0.146 level without closing beyond it, stop beyond extreme, target leg / 2R",
    },
    "v4": {
        "name": "Scanner v4 (11 Nov Workflow)",
        "summary": "BOS -> Sweep of BOS origin -> Buying/Selling signal candle -> Trigger close -> Entry, plus secondary OB/FVG retest",
    },
    "v3": {
        "name": "Scanner v3 (Sweep Reversal)",
        "summary": "BOS -> Close beyond swept swing -> Doji/Hammer signal -> Trigger close + FVG/OB retest",
    },
    "v2": {
        "name": "Scanner v2 (A-B-C-D)",
        "summary": "BOS (A) -> Red close below swing (B) -> Doji (C) -> Close above doji high (D)",
    },
    "rules": {
        "name": "Core Rules (Breakout / ORB)",
        "summary": "4h/Range breakout & breakdown levels with swing structure and RSI/momentum context",
    },
}


def _r(x: float) -> float:
    ax = abs(x)
    if ax >= 100:
        return round(x, 2)
    if ax >= 1:
        return round(x, 4)
    return float("%.6g" % x)


def _norm_candles(raw: List[Any]) -> List[tuple]:
    rows = []
    for idx, c in enumerate(raw or []):
        if not isinstance(c, (list, tuple)) or len(c) < 5:
            continue
        t = int(c[0]) if c[0] is not None else idx * 300
        o, h, l, cl = float(c[1]), float(c[2]), float(c[3]), float(c[4])
        if h < max(o, cl):
            h = max(o, cl)
        if l > min(o, cl):
            l = min(o, cl)
        v = float(c[5]) if len(c) > 5 and c[5] is not None else 1000.0
        rows.append((t, o, h, l, cl, v))
    return rows


def _filter_dir(trades: List[Dict[str, Any]], direction: str) -> List[Dict[str, Any]]:
    if direction == "long":
        return [t for t in trades if t.get("side") == "BUY"]
    if direction == "short":
        return [t for t in trades if t.get("side") == "SELL"]
    return trades


def _analyze_v6(rows: List[tuple], opts: Dict[str, Any]) -> Dict[str, Any]:
    from datetime import timedelta
    from scanner_v6.data.candle_models import Candle, CandleSeries
    from scanner_v6.data.market_config import ConfigOrigin, MarketDataConfig
    from scanner_v6.entry.confirmation import CONFIRMED, ConfirmationStream
    from scanner_v6.exit.stop_loss import BUY, structural_sl, to_grid
    from scanner_v6.exit.targets import PoolView, select_target_pool, target_price
    from scanner_v6.liquidity.sweep import LiquidityEvent
    from scanner_v6.structure.choch import CHoCHBreak, analyze_structure

    sl_buf = int(opts.get("sl_buffer_ticks", 2))
    tp_off = int(opts.get("tp_offset_ticks", 1))
    min_rr = float(opts.get("min_rr", 1.0))
    direction = str(opts.get("direction", "both")).lower()

    span = max(p - n for _, _, p, n, _, _ in rows) if rows else 1.0
    tick_val = max(span / 1000.0, 1e-6)
    T = Decimal(repr(_r(tick_val)))
    tf = timedelta(seconds=max(1, rows[1][0] - rows[0][0])) if len(rows) > 1 else timedelta(minutes=5)

    mkt = MarketDataConfig(origin=ConfigOrigin.INSTRUMENT_CONFIG, instrument_id="chart_test",
                           timeframe=tf, tick_size=float(T), session=None)
    st = ConfirmationStream("chart_test", "%ds" % int(tf.total_seconds()), mkt)

    all_sweeps: List[LiquidityEvent] = []
    all_patterns: List[Any] = []
    _orig_ss = st.setup_stream.on_candle
    _orig_ps = st.patterns_stream.on_candle

    def _wrap_ss(c):
        sev, lev, cands = _orig_ss(c)
        for ev in lev:
            if isinstance(ev, LiquidityEvent) and ev.event_type == "SWEEP":
                all_sweeps.append(ev)
        return sev, lev, cands

    def _wrap_ps(c):
        pats = _orig_ps(c)
        all_patterns.extend(pats)
        return pats

    st.setup_stream.on_candle = _wrap_ss  # type: ignore[assignment]
    st.patterns_stream.on_candle = _wrap_ps  # type: ignore[assignment]

    candles = []
    for k, r in enumerate(rows):
        c = Candle(k, r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
        st.on_candle(c)
        candles.append(c)

    swings, lines, zones, markers, trades = [], [], [], [], []
    n = len(candles)

    # Structure: Swings, CHoCH & BOS indexed by id for exact per-setup marking
    srep = analyze_structure(CandleSeries(candles))
    swing_by_id = {sw.id: sw for sw in srep.swings}
    choch_by_id = {ev.id: ev for ev in srep.events if isinstance(ev, CHoCHBreak)}
    bos_by_id = {ev.id: ev for ev in srep.bos}
    pat_by_id = {p.pattern_id: p for p in getattr(st, "pattern_states", []) or []}

    # Liquidity pools (used for V6 target selection)
    lq = st.setup_stream.liquidity
    pools = [
        PoolView(p.id, "BSL" if p.side.value == "above" else "SSL", Decimal(repr(p.price)),
                 p.stamp.confirmed_index, lq.state[p.id])
        for p in (getattr(lq, "pools", []) or [])
    ]

    def _origin_idx(ev, fallback_idx: int) -> int:
        sid = getattr(ev, "broken_swing_id", None) or (ev.related[0] if getattr(ev, "related", None) else None)
        sw = swing_by_id.get(sid) if sid else None
        return sw.index if sw is not None else max(0, fallback_idx - 8)

    def _add_setup_marks(rec, mark_confirm: bool = False, conf_i: int = -1):
        side = "BUY" if rec.setup_side == BUY else "SELL"
        ch_ev = choch_by_id.get(rec.choch_id) if rec.choch_id else None
        if ch_ev is not None:
            o_idx = _origin_idx(ch_ev, ch_ev.index)
            lines.append({"kind": "CHoCH", "label": "CHOCH",
                          "start": o_idx, "end": ch_ev.index, "price": _r(ch_ev.level), "side": side})
            if o_idx in range(n):
                swings.append({"index": o_idx, "price": _r(ch_ev.level),
                               "kind": "SH" if ch_ev.direction.value == "bullish" else "SL"})
        b_ev = bos_by_id.get(rec.bos_id)
        if b_ev is not None:
            o_idx = _origin_idx(b_ev, b_ev.index)
            lines.append({"kind": "BOS", "label": "BOS",
                          "start": o_idx, "end": b_ev.index, "price": _r(b_ev.level), "side": side})
            if o_idx in range(n):
                swings.append({"index": o_idx, "price": _r(b_ev.level),
                               "kind": "SH" if b_ev.direction.value == "bullish" else "SL"})
        sw_i = rec.sweep_index
        sw = candles[sw_i]
        markers.append({"index": sw_i, "price": _r(sw.low if side == "BUY" else sw.high),
                        "kind": "SWEEP", "label": "LIQ SWEEP", "side": side})

        pid = rec.confirmed_pattern_id or (rec.tracked[-1] if rec.tracked else None)
        pat = pat_by_id.get(pid) if pid else None
        if pat is not None and 0 <= pat.end_candle < n:
            pname = pat.pattern_id.split(":")[0].replace("_", " ").upper()
            markers.append({"index": pat.end_candle,
                            "price": _r(candles[pat.end_candle].low if side == "BUY" else candles[pat.end_candle].high),
                            "kind": "PATTERN", "label": pname, "side": side})
        if mark_confirm and 0 <= conf_i < n:
            markers.append({"index": conf_i, "price": _r(candles[conf_i].close),
                            "kind": "CONFIRM", "label": "CONFIRM", "side": side})

    # Setups & Trades: mark full setup (CHoCH, BOS, Sweep, Candlestick, Confirmation, Position Box)
    all_setups = list(getattr(st, "setups", []) or [])
    sweep_count = len(all_setups)
    pattern_count = sum(1 for r in all_setups if r.confirmed_pattern_id or r.tracked)

    for rec in all_setups:
        side = "BUY" if rec.setup_side == BUY else "SELL"
        if direction != "both" and ((direction == "long" and side != "BUY") or (direction == "short" and side != "SELL")):
            continue
        if rec.status == CONFIRMED and rec.history:
            conf_i = rec.history[-1].index
            sw = candles[rec.sweep_index]
            sl = structural_sl(rec.setup_side, Decimal(repr(sw.low)), Decimal(repr(sw.high)), sl_buf, T, "ROUND_HALF_UP")
            entry = to_grid(Decimal(repr(candles[conf_i].close)), T, "ROUND_HALF_UP")
            if (rec.setup_side == BUY and entry <= sl) or (rec.setup_side != BUY and entry >= sl):
                continue
            pool = select_target_pool(rec.setup_side, entry, pools)
            if pool is not None:
                tp = target_price(rec.setup_side, pool.price, tp_off, T, "ROUND_HALF_UP")
                tp_note = ""
            else:
                risk_d = abs(entry - sl)
                tp = entry + (risk_d * Decimal("2")) if rec.setup_side == BUY else entry - (risk_d * Decimal("2"))
                tp_note = " · 2R"
            risk = abs(float(entry - sl))
            rew = abs(float(tp - entry))
            rr = round(rew / risk, 2) if risk > 0 else 0.0
            if rr >= min_rr:
                _add_setup_marks(rec, mark_confirm=True, conf_i=conf_i)
                trades.append({
                    "side": side, "status": "CONFIRMED", "entry_index": conf_i,
                    "entry": _r(float(entry)), "sl": _r(float(sl)), "tp": _r(float(tp)),
                    "rr": rr, "label": f"V6 {'LONG' if side == 'BUY' else 'SHORT'} (R:R {rr}{tp_note})",
                })

    # If no full confirmed trade met filters, show the latest setup's marks (or latest CHoCH, BOS, Sweep, Pattern)
    if not trades:
        if all_setups:
            _add_setup_marks(all_setups[-1], mark_confirm=False)
        else:
            if choch_by_id:
                last_ch = list(choch_by_id.values())[-1]
                o_idx = _origin_idx(last_ch, last_ch.index)
                lines.append({"kind": "CHoCH", "label": "CHOCH",
                              "start": o_idx, "end": last_ch.index, "price": _r(last_ch.level),
                              "side": "BUY" if last_ch.direction.value == "bullish" else "SELL"})
                if o_idx in range(n):
                    swings.append({"index": o_idx, "price": _r(last_ch.level),
                                   "kind": "SH" if last_ch.direction.value == "bullish" else "SL"})
            if bos_by_id:
                last_b = list(bos_by_id.values())[-1]
                o_idx = _origin_idx(last_b, last_b.index)
                lines.append({"kind": "BOS", "label": "BOS",
                              "start": o_idx, "end": last_b.index, "price": _r(last_b.level),
                              "side": "BUY" if last_b.direction.value == "bullish" else "SELL"})
                if o_idx in range(n):
                    swings.append({"index": o_idx, "price": _r(last_b.level),
                                   "kind": "SH" if last_b.direction.value == "bullish" else "SL"})
            if all_sweeps:
                sw_ev = all_sweeps[-1]
                sw_side = "BUY" if sw_ev.side == "SSL" else "SELL"
                lines.append({"kind": sw_ev.side, "label": f"SWEPT {sw_ev.side}",
                              "start": max(0, sw_ev.index - 10), "end": sw_ev.index, "price": _r(sw_ev.level),
                              "side": sw_side})
                markers.append({"index": sw_ev.index, "price": _r(sw_ev.extreme),
                                "kind": "SWEEP", "label": "LIQ SWEEP", "side": sw_side})
            if all_patterns:
                pat_ev = all_patterns[-1]
                pat_side = "BUY" if pat_ev.direction == "BULLISH" else "SELL"
                lbl = (pat_ev.pattern_label or pat_ev.pattern_type).replace("_", " ").upper()
                markers.append({"index": pat_ev.end_candle,
                                "price": _r(pat_ev.pattern_low if pat_side == "BUY" else pat_ev.pattern_high),
                                "kind": "PATTERN", "label": lbl, "side": pat_side})

    checklist = [
        {"step": "1. CHoCH", "passed": len(choch_by_id) > 0,
         "detail": f"{len(choch_by_id)} CHoCH break(s) detected"},
        {"step": "2. BOS", "passed": len(bos_by_id) > 0,
         "detail": f"{len(bos_by_id)} BOS break(s) detected"},
        {"step": "3. Liquidity Sweep", "passed": sweep_count > 0 or len(all_sweeps) > 0,
         "detail": f"{sweep_count} setup sweep(s), {len(all_sweeps)} raw sweep(s) on {len(pools)} pool(s)"},
        {"step": "4. Candlestick Pattern", "passed": pattern_count > 0 or len(all_patterns) > 0,
         "detail": f"{pattern_count} setup pattern(s), {len(all_patterns)} total pattern(s)"},
        {"step": "5. Confirmation & Position Box", "passed": len(trades) > 0,
         "detail": f"{len(trades)} confirmed setup(s) meeting min R:R {min_rr}"},
    ]
    return {"swings": swings, "lines": lines, "zones": zones, "markers": markers, "trades": trades, "checklist": checklist}


def _analyze_smc_ctx(rows: List[tuple], version: str, opts: Dict[str, Any]) -> Dict[str, Any]:
    import smc_playbook as PB

    direction = str(opts.get("direction", "both")).lower()
    min_rr = float(opts.get("min_rr", 1.0))
    c_level = float(opts.get("c_level", 0.146))
    ctx = PB.Context(rows, k=2)
    n = len(rows)

    swings, lines, zones, markers, trades = [], [], [], [], []
    for i, p in ctx.sh_known[-1]:
        swings.append({"index": i, "price": _r(p), "kind": "SH"})
    for i, p in ctx.sl_known[-1]:
        swings.append({"index": i, "price": _r(p), "kind": "SL"})

    if version == "v5":
        import scanner_v5 as V5
        p = dict(V5.DEFAULTS, c=c_level, min_rr=min_rr)
        day_of = [0] * n
        for side_flag, mirror_rows in ((False, rows), (True, V5.mirror(rows))):
            if direction == "long" and side_flag:
                continue
            if direction == "short" and not side_flag:
                continue
            s_ctx = ctx if not side_flag else PB.Context(mirror_rows, k=2)
            leg = V5._legs_swing(s_ctx, n - 1)
            if leg:
                lo_i, lo, hi_i, hi = leg
                rng = hi - lo
                lvl = lo + c_level * rng
                real_lvl = _r(-lvl if side_flag else lvl)
                lines.append({"kind": "FIB", "label": f"{c_level} Level ({'Short' if side_flag else 'Long'})",
                              "start": min(lo_i, hi_i), "end": n - 1, "price": real_lvl,
                              "side": "SELL" if side_flag else "BUY"})
            for tr in V5.longs(mirror_rows, day_of, p, intraday=False, ctx=s_ctx):
                rt = V5._real(tr, side_flag)
                rr_val = V5.rr(rt)
                if rr_val >= min_rr:
                    side = "SELL" if side_flag else "BUY"
                    markers.append({"index": rt["i"], "price": _r(rt["entry"]), "kind": "ENTRY", "label": f"v5 {side}", "side": side})
                    trades.append({"side": side, "status": "CONFIRMED", "entry_index": rt["i"],
                                   "entry": _r(rt["entry"]), "sl": _r(rt["stop"]), "tp": _r(rt["target"]),
                                   "rr": round(rr_val, 2), "label": f"v5 {side} (R:R {round(rr_val, 2)})"})
        checklist = [
            {"step": "1. Swing Leg (L -> H)", "passed": len(swings) >= 2, "detail": f"{len(swings)} swing points detected"},
            {"step": f"2. {c_level} Retracement Level", "passed": any(l["kind"] == "FIB" for l in lines),
             "detail": "Computed from latest confirmed swing leg"},
            {"step": "3. Touch & Close Confirmation", "passed": len(trades) > 0,
             "detail": f"{len(trades)} v5 entry signal(s) found"},
        ]
        return {"swings": swings, "lines": lines, "zones": zones, "markers": markers, "trades": trades, "checklist": checklist}

    if version == "v4":
        import scanner_v4 as V4
        day_of = [0] * n
        for tr in V4.sequence(rows, day_of, intraday=False):
            side = "SELL" if tr.get("short") else "BUY"
            if (direction == "long" and side != "BUY") or (direction == "short" and side != "SELL"):
                continue
            rr_val = V4.rr(tr)
            if rr_val >= min_rr:
                idx = tr.get("i", n - 1)
                markers.append({"index": idx, "price": _r(tr["entry"]), "kind": "ENTRY",
                                "label": f"v4 {tr.get('kind', 'primary')} {side}", "side": side})
                trades.append({"side": side, "status": "CONFIRMED", "entry_index": idx,
                               "entry": _r(tr["entry"]), "sl": _r(tr["stop"]), "tp": _r(tr["target"]),
                               "rr": round(rr_val, 2), "label": f"v4 {side} (R:R {round(rr_val, 2)})"})
        checklist = [
            {"step": "1. Swing Structure", "passed": len(swings) >= 2, "detail": f"{len(swings)} swing highs/lows"},
            {"step": "2. BOS -> Sweep -> Signal -> Trigger", "passed": len(trades) > 0,
             "detail": f"{len(trades)} v4 setup(s) triggered"},
        ]
        return {"swings": swings, "lines": lines, "zones": zones, "markers": markers, "trades": trades, "checklist": checklist}

    if version == "v3":
        import sweep_reversal as V3
        day_of = [0] * n
        for side_flag, mirror_rows in ((False, rows), (True, V3.mirror(rows))):
            side = "SELL" if side_flag else "BUY"
            if (direction == "long" and side != "BUY") or (direction == "short" and side != "SELL"):
                continue
            for sig in V3.signals(mirror_rows, day_of):
                st = V3.stop_for(sig)
                tp = V3.target_for(sig, "2R", st)
                rr_val = V3.rr(sig, st, tp)
                if rr_val >= min_rr:
                    idx = sig["i"]
                    entry = -sig["entry"] if side_flag else sig["entry"]
                    sl = -st if side_flag else st
                    target = -tp if side_flag else tp
                    markers.append({"index": idx, "price": _r(entry), "kind": "SIGNAL", "label": f"v3 {side}", "side": side})
                    trades.append({"side": side, "status": "CONFIRMED", "entry_index": idx,
                                   "entry": _r(entry), "sl": _r(sl), "tp": _r(target),
                                   "rr": round(rr_val, 2), "label": f"v3 {side} (R:R {round(rr_val, 2)})"})
        checklist = [
            {"step": "1. BOS + Swept Swing", "passed": len(swings) >= 2, "detail": f"{len(swings)} swing points"},
            {"step": "2. Sweep Reversal Signal", "passed": len(trades) > 0, "detail": f"{len(trades)} v3 signal(s)"},
        ]
        return {"swings": swings, "lines": lines, "zones": zones, "markers": markers, "trades": trades, "checklist": checklist}

    if version == "v2":
        import abcd as V2
        day_of = [0] * n
        for side_flag, mirror_rows in ((False, rows), (True, V2.mirror(rows))):
            side = "SELL" if side_flag else "BUY"
            if (direction == "long" and side != "BUY") or (direction == "short" and side != "SELL"):
                continue
            s_ctx = ctx if not side_flag else PB.Context(mirror_rows, k=2)
            for sig in V2.signals(mirror_rows, day_of, short=side_flag, ctx=s_ctx):
                st = V2.stop_for(sig, "c", 0.1)
                tp = V2.target_for(s_ctx, sig, "2R", st)
                entry = -sig["entry"] if side_flag else sig["entry"]
                sl = -st if side_flag else st
                target = -tp if side_flag else tp
                risk = abs(entry - sl)
                rr_val = abs(target - entry) / risk if risk > 0 else 0.0
                if rr_val >= min_rr:
                    idx = sig["i"]
                    markers.append({"index": idx, "price": _r(entry), "kind": "SIGNAL", "label": f"A-B-C-D {side}", "side": side})
                    trades.append({"side": side, "status": "CONFIRMED", "entry_index": idx,
                                   "entry": _r(entry), "sl": _r(sl), "tp": _r(target),
                                   "rr": round(rr_val, 2), "label": f"v2 A-B-C-D {side}"})
        checklist = [
            {"step": "1. A-B-C-D Structure", "passed": len(swings) >= 2, "detail": f"{len(swings)} swing points"},
            {"step": "2. Doji + Trigger Close", "passed": len(trades) > 0, "detail": f"{len(trades)} A-B-C-D signal(s)"},
        ]
        return {"swings": swings, "lines": lines, "zones": zones, "markers": markers, "trades": trades, "checklist": checklist}

    # "rules": range breakout / ORB
    lookback = min(16, max(4, n // 3))
    r_hi = max(r[2] for r in rows[:lookback])
    r_lo = min(r[3] for r in rows[:lookback])
    lines.append({"kind": "RANGE", "label": f"Range High {_r(r_hi)}", "start": 0, "end": n - 1, "price": _r(r_hi), "side": "BUY"})
    lines.append({"kind": "RANGE", "label": f"Range Low {_r(r_lo)}", "start": 0, "end": n - 1, "price": _r(r_lo), "side": "SELL"})
    for idx in range(lookback, n):
        cl = rows[idx][4]
        if cl > r_hi and direction != "short":
            risk = max(cl - r_lo, (r_hi - r_lo) * 0.5)
            tp = cl + risk * 2.0
            trades.append({"side": "BUY", "status": "CONFIRMED", "entry_index": idx,
                           "entry": _r(cl), "sl": _r(cl - risk), "tp": _r(tp), "rr": 2.0, "label": "Breakout LONG"})
            markers.append({"index": idx, "price": _r(cl), "kind": "ENTRY", "label": "Breakout", "side": "BUY"})
            break
        if cl < r_lo and direction != "long":
            risk = max(r_hi - cl, (r_hi - r_lo) * 0.5)
            tp = cl - risk * 2.0
            trades.append({"side": "SELL", "status": "CONFIRMED", "entry_index": idx,
                           "entry": _r(cl), "sl": _r(cl + risk), "tp": _r(tp), "rr": 2.0, "label": "Breakdown SHORT"})
            markers.append({"index": idx, "price": _r(cl), "kind": "ENTRY", "label": "Breakdown", "side": "SELL"})
            break
    checklist = [
        {"step": "1. Opening / Consolidation Range", "passed": True, "detail": f"{_r(r_lo)} – {_r(r_hi)} ({lookback} bars)"},
        {"step": "2. Breakout / Breakdown Close", "passed": len(trades) > 0, "detail": f"{len(trades)} breakout(s) detected"},
    ]
    return {"swings": swings, "lines": lines, "zones": zones, "markers": markers, "trades": trades, "checklist": checklist}


@router.post("/api/py/chart-test/analyze")
async def analyze_chart(request: Request):
    body = await request.json()
    version = str(body.get("scanner_version") or "v6").lower()
    if version not in STRATEGY_META:
        raise HTTPException(400, f"unknown scanner_version {version!r}")
    rows = _norm_candles(body.get("candles") or [])
    if len(rows) < 8:
        raise HTTPException(400, f"need at least 8 extracted candles from the chart image (got {len(rows)})")
    opts = body.get("options") or {}

    try:
        res = _analyze_v6(rows, opts) if version == "v6" else _analyze_smc_ctx(rows, version, opts)
    except Exception as exc:
        raise HTTPException(500, f"scanner {version} failed: {exc}") from exc

    trades = res.get("trades") or []
    bias = trades[-1]["side"] if trades else (res["lines"][-1].get("side", "NEUTRAL") if res.get("lines") else "NEUTRAL")
    best_rr = max((t.get("rr", 0.0) for t in trades), default=0.0)
    return {
        "scanner_version": version,
        "strategy_name": STRATEGY_META[version]["name"],
        "strategy_summary": STRATEGY_META[version]["summary"],
        "candle_count": len(rows),
        "summary": {"bias": bias, "setups_found": len(trades), "best_rr": best_rr},
        **res,
    }
