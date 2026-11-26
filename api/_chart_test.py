"""
api/_chart_test.py - Chart Testing endpoint: analyze extracted chart candles with any scanner version (v6, v5, v4, v3, v2, rules)
and return structured markings (CHoCH, BOS, liquidity pools, sweeps, FVG/OB zones, signals, entry/SL/TP, and checklist)
so the dashboard can draw them directly onto the uploaded chart image.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from typing import Any, Dict, List, Optional

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


def _fmt_pat_name(raw_name: str) -> str:
    txt = str(raw_name or "PATTERN").strip()
    if ":" in txt:
        txt = txt.split(":")[-1]
    return txt.replace("_", " ").title()


def _label_swings(srep_swings: List[Any]) -> List[Dict[str, Any]]:
    from scanner_v6.models import SwingKind

    out: List[Dict[str, Any]] = []
    seen = set()
    prev_high = None
    prev_low = None
    for sw in sorted(srep_swings, key=lambda s: (s.index, s.kind.value)):
        if sw.kind is SwingKind.HIGH:
            tag = "SH" if prev_high is None else ("HH" if sw.price > prev_high else "LH")
            prev_high = sw.price
        else:
            tag = "SL" if prev_low is None else ("LL" if sw.price < prev_low else "HL")
            prev_low = sw.price
        key = (sw.index, tag)
        if key not in seen:
            seen.add(key)
            out.append({"index": sw.index, "price": _r(sw.price), "kind": tag})
    return out


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

    lines: List[Dict[str, Any]] = []
    zones: List[Dict[str, Any]] = []
    markers: List[Dict[str, Any]] = []
    trades: List[Dict[str, Any]] = []
    n = len(candles)

    # Structure: Swings (LL/LH/HL/HH), CHoCH & BOS indexed by id for exact per-setup marking
    srep = analyze_structure(CandleSeries(candles))
    swings = _label_swings(srep.swings)
    swing_by_id = {sw.id: sw for sw in srep.swings}
    choch_by_id = {ev.id: ev for ev in srep.events if isinstance(ev, CHoCHBreak)}
    bos_by_id = {ev.id: ev for ev in srep.bos}
    pat_by_id = {p.pattern_id: p for p in getattr(st, "pattern_states", []) or []}
    pat_label_by_span = {
        (p.start_candle, p.end_candle, p.direction): (p.pattern_label or _fmt_pat_name(p.pattern_type))
        for p in all_patterns
    }

    # Liquidity pools & sweep group lookup (used for V6 sweep line origin + target selection)
    lq = st.setup_stream.liquidity
    raw_pools = list(getattr(lq, "pools", []) or [])
    pool_by_id = {p.id: p for p in raw_pools}
    sweep_by_group: Dict[str, List[LiquidityEvent]] = {}
    for ev in all_sweeps:
        if ev.group_id:
            sweep_by_group.setdefault(ev.group_id, []).append(ev)

    pools = [
        PoolView(p.id, "BSL" if p.side.value == "above" else "SSL", Decimal(repr(p.price)),
                 p.stamp.confirmed_index, lq.state[p.id])
        for p in raw_pools
    ]

    def _origin_idx(ev, fallback_idx: int) -> int:
        sid = getattr(ev, "broken_swing_id", None) or (ev.related[0] if getattr(ev, "related", None) else None)
        sw = swing_by_id.get(sid) if sid else None
        return sw.index if sw is not None else max(0, fallback_idx - 8)

    def _sweep_detail(rec, side: str) -> Dict[str, Any]:
        sw_i = rec.sweep_index
        sw_c = candles[sw_i]
        evs = sweep_by_group.get(rec.group_id, [])
        if not evs:
            expected = "SSL" if side == "BUY" else "BSL"
            evs = [ev for ev in all_sweeps if ev.index == sw_i and ev.side == expected]
        if evs:
            ev = evs[-1]
            pool = pool_by_id.get(ev.pool_id)
            origin_i = pool.stamp.index if pool is not None else -1
            if pool is not None and 0 <= origin_i < sw_i:
                return {
                    "verified": True,
                    "index": sw_i,
                    "origin_index": origin_i,
                    "level": _r(float(ev.level)),
                    "extreme": _r(float(ev.extreme)),
                }
        return {
            "verified": False,
            "index": sw_i,
            "origin_index": max(0, sw_i - 8),
            "level": _r(min(sw_c.open, sw_c.close) if side == "BUY" else max(sw_c.open, sw_c.close)),
            "extreme": _r(sw_c.low if side == "BUY" else sw_c.high),
        }

    def _add_setup_marks(rec, mark_confirm: bool = False, confirm_steps: Optional[List[int]] = None, pat_name_out: Optional[List[str]] = None) -> Dict[str, Any]:
        side = "BUY" if rec.setup_side == BUY else "SELL"
        meta: Dict[str, Any] = {"choch": None, "bos": None, "sweep": None, "pattern": None, "confirm_steps": []}

        ch_ev = choch_by_id.get(rec.choch_id) if rec.choch_id else None
        if ch_ev is not None:
            o_idx = _origin_idx(ch_ev, ch_ev.index)
            dir_sub = "Bearish -> Bullish" if ch_ev.direction.value == "bullish" else "Bullish -> Bearish"
            lines.append({"kind": "CHoCH", "label": "CHoCH", "sublabel": dir_sub,
                          "start": o_idx, "end": ch_ev.index, "price": _r(ch_ev.level), "side": side})
            meta["choch"] = {"start": o_idx, "end": ch_ev.index, "price": _r(ch_ev.level), "sublabel": dir_sub}

        b_ev = bos_by_id.get(rec.bos_id)
        if b_ev is not None:
            o_idx = _origin_idx(b_ev, b_ev.index)
            dir_sub = "Bullish Structure" if b_ev.direction.value == "bullish" else "Bearish Structure"
            lines.append({"kind": "BOS", "label": "BOS", "sublabel": dir_sub,
                          "start": o_idx, "end": b_ev.index, "price": _r(b_ev.level), "side": side})
            meta["bos"] = {"start": o_idx, "end": b_ev.index, "price": _r(b_ev.level), "sublabel": dir_sub}

        sw_info = _sweep_detail(rec, side)
        if sw_info["verified"]:
            sw_sub = "Took Out Lows" if side == "BUY" else "Took Out Highs"
            lines.append({"kind": "SWEEP", "label": "Liquidity Sweep", "sublabel": sw_sub,
                          "start": sw_info["origin_index"], "end": sw_info["index"],
                          "price": sw_info["level"], "side": side})
            markers.append({"index": sw_info["index"], "price": sw_info["extreme"],
                            "kind": "SWEEP", "label": "Liquidity Sweep", "sublabel": sw_sub,
                            "side": side, "pool_level": sw_info["level"]})
        meta["sweep"] = sw_info

        pid = rec.confirmed_pattern_id or (rec.tracked[-1] if rec.tracked else None)
        pat = pat_by_id.get(pid) if pid else None
        if pat is not None and 0 <= pat.end_candle < n:
            pdir = "BULLISH" if side == "BUY" else "BEARISH"
            pname = pat_label_by_span.get((pat.start_candle, pat.end_candle, pdir)) or _fmt_pat_name(pat.pattern_id)
            if pname.lower() == "engulfing":
                pname = f"{'Bullish' if side == 'BUY' else 'Bearish'} {pname}"
            if pat_name_out is not None:
                pat_name_out.append(pname)
            zones.append({"kind": "PATTERN", "label": pname, "sublabel": "Pattern",
                          "start": pat.start_candle, "end": pat.end_candle,
                          "high": _r(pat.pattern_high), "low": _r(pat.pattern_low), "side": side})
            markers.append({"index": pat.end_candle,
                            "price": _r(pat.pattern_low if side == "BUY" else pat.pattern_high),
                            "kind": "PATTERN", "label": pname, "sublabel": "Pattern", "side": side})
            meta["pattern"] = {"start": pat.start_candle, "end": pat.end_candle, "label": pname,
                               "high": _r(pat.pattern_high), "low": _r(pat.pattern_low)}

        step_indices = list(confirm_steps or [])
        if mark_confirm and len(step_indices) >= 3:
            conf_i = step_indices[-1]
            for s_num, c_idx in enumerate(step_indices, start=1):
                c_bar = candles[c_idx]
                markers.append({"index": c_idx,
                                "price": _r(c_bar.low if side == "BUY" else c_bar.high),
                                "kind": "CONFIRM_STEP", "label": str(s_num), "side": side})
            conf_sub = "3 Closes Above BOS" if (side == "BUY" and b_ev is not None) else (
                "3 Closes Below BOS" if (side == "SELL" and b_ev is not None) else "3 Closes in Direction"
            )
            markers.append({"index": conf_i, "price": _r(candles[conf_i].high if side == "BUY" else candles[conf_i].low),
                            "kind": "CONFIRM", "label": "3-Candle Confirm", "sublabel": conf_sub,
                            "side": side, "start": step_indices[0], "end": conf_i})
            meta["confirm_steps"] = step_indices
        return meta

    max_chart_high = max((c.high for c in candles), default=0.0)
    min_chart_low = min((c.low for c in candles), default=0.0)

    def _collect_three_confirm_candles(pat_end: int, mod_d_conf_i: int, side: str, pat_obj: Any) -> List[int]:
        """Require 3 distinct completed candles after the pattern closing in trade direction."""
        if pat_obj is None or pat_end < 0:
            return []
        cand_indices = [idx for idx in range(pat_end + 1, min(n, pat_end + 4))]
        if len(cand_indices) < 3:
            return []
        valid: List[int] = []
        for idx in cand_indices:
            bar = candles[idx]
            if side == "BUY":
                if bar.close > bar.open and bar.close >= pat_obj.pattern_low:
                    valid.append(idx)
                else:
                    return []
            else:
                if bar.close < bar.open and bar.close <= pat_obj.pattern_high:
                    valid.append(idx)
                else:
                    return []
        # Confirming candle (or window) must satisfy Module D's close beyond pattern extreme
        if side == "BUY" and not any(candles[i].close > pat_obj.pattern_high for i in valid):
            return []
        if side == "SELL" and not any(candles[i].close < pat_obj.pattern_low for i in valid):
            return []
        return valid if len(set(valid)) >= 3 else []

    def _validate_setup(rec) -> Dict[str, Any]:
        side = "BUY" if rec.setup_side == BUY else "SELL"
        ch_ev = choch_by_id.get(rec.choch_id) if rec.choch_id else None
        b_ev = bos_by_id.get(rec.bos_id) if rec.bos_id else None
        sw_info = _sweep_detail(rec, side)
        pid = rec.confirmed_pattern_id or (rec.tracked[-1] if rec.tracked else None)
        pat = pat_by_id.get(pid) if pid else None

        choch_ok = ch_ev is not None
        bos_ok = b_ev is not None
        liq_ok = bool(sw_info["verified"])
        pat_ok = pat is not None and 0 <= pat.end_candle < n

        reasons: List[str] = []
        if not choch_ok:
            reasons.append("CHoCH break missing for setup")
        if not bos_ok:
            reasons.append("BOS break missing for setup")
        if not liq_ok:
            reasons.append("Verified liquidity sweep of prior pool missing")
        if not pat_ok:
            reasons.append("Matching post-sweep candlestick pattern missing")

        confirm_steps: List[int] = []
        if rec.status == CONFIRMED and rec.history and pat is not None:
            confirm_steps = _collect_three_confirm_candles(pat.end_candle, rec.history[-1].index, side, pat)
        conf_count = len(confirm_steps)
        conf_ok = rec.status == CONFIRMED and conf_count >= 3
        if not conf_ok:
            if rec.status == CONFIRMED:
                reasons.append(f"3-candle confirmation incomplete ({conf_count}/3 completed candles)")
            else:
                reasons.append("Setup not confirmed by 3 completed candles")

        tp_ok = False
        exec_ok = False
        trade_obj: Optional[Dict[str, Any]] = None

        if conf_ok:
            conf_i = confirm_steps[-1]
            entry_idx = conf_i + 1
            if entry_idx >= n:
                reasons.append("Entry C+1 candle unavailable (confirmation on final bar)")
            else:
                sw = candles[rec.sweep_index]
                sl = structural_sl(rec.setup_side, Decimal(repr(sw.low)), Decimal(repr(sw.high)), sl_buf, T, "ROUND_HALF_UP")
                entry = to_grid(Decimal(repr(candles[entry_idx].open)), T, "ROUND_HALF_UP")
                if (rec.setup_side == BUY and entry <= sl) or (rec.setup_side != BUY and entry >= sl):
                    reasons.append("Entry open not beyond structural SL")
                else:
                    avail_pools = [
                        p for p in pools
                        if p.confirmed_index <= conf_i
                        and p.pool_id in pool_by_id
                        and 0 <= pool_by_id[p.pool_id].stamp.index < entry_idx
                        and min_chart_low <= float(p.price) <= max_chart_high
                    ]
                    pool = select_target_pool(rec.setup_side, entry, avail_pools)
                    if pool is None:
                        reasons.append("NO_ELIGIBLE_OPPOSING_POOL (no actual prior opposing liquidity pool exists)")
                    else:
                        tp = target_price(rec.setup_side, pool.price, tp_off, T, "ROUND_HALF_UP")
                        tp_f = float(tp)
                        if tp_f > max_chart_high or tp_f < min_chart_low:
                            reasons.append("Target outside extracted chart price bounds")
                        else:
                            tp_ok = True
                            risk = abs(float(entry - sl))
                            rew = abs(float(tp - entry))
                            rr = round(rew / risk, 2) if risk > 0 else 0.0
                            if rr < min_rr:
                                reasons.append(f"R:R {rr} below minimum {min_rr}")
                            elif choch_ok and bos_ok and liq_ok and pat_ok and conf_ok:
                                exec_ok = True
                                sl_f, en_f = float(sl), float(entry)
                                p_obj = pool_by_id[pool.pool_id]
                                tp_pool_idx = p_obj.stamp.index
                                outcome = "OPEN"
                                exit_idx = n - 1
                                exit_price = candles[-1].close
                                for k_fwd in range(entry_idx, n):
                                    bar = candles[k_fwd]
                                    if side == "BUY":
                                        if bar.low <= sl_f:
                                            outcome, exit_idx, exit_price = "STOPPED OUT", k_fwd, sl_f
                                            break
                                        if bar.high >= tp_f:
                                            outcome, exit_idx, exit_price = "TARGET HIT", k_fwd, tp_f
                                            break
                                    else:
                                        if bar.high >= sl_f:
                                            outcome, exit_idx, exit_price = "STOPPED OUT", k_fwd, sl_f
                                            break
                                        if bar.low <= tp_f:
                                            outcome, exit_idx, exit_price = "TARGET HIT", k_fwd, tp_f
                                            break
                                if outcome == "TARGET HIT":
                                    realized_r = rr
                                elif outcome == "STOPPED OUT":
                                    realized_r = -1.0
                                else:
                                    unreal = ((exit_price - en_f) if side == "BUY" else (en_f - exit_price)) / risk if risk > 0 else 0.0
                                    realized_r = round(unreal, 2)
                                pdir = "BULLISH" if side == "BUY" else "BEARISH"
                                pname = pat_label_by_span.get((pat.start_candle, pat.end_candle, pdir)) or _fmt_pat_name(pat.pattern_id)
                                if pname.lower() == "engulfing":
                                    pname = f"{'Bullish' if side == 'BUY' else 'Bearish'} {pname}"
                                trade_obj = {
                                    "side": side,
                                    "status": "CONFIRMED",
                                    "entry_index": entry_idx,
                                    "confirm_index": conf_i,
                                    "sweep_index": rec.sweep_index,
                                    "entry": _r(en_f),
                                    "sl": _r(sl_f),
                                    "tp": _r(tp_f),
                                    "rr": rr,
                                    "risk_pts": _r(risk),
                                    "reward_pts": _r(rew),
                                    "entry_mode": "C+1 Open",
                                    "tp_pool_index": tp_pool_idx,
                                    "tp_pool_price": _r(float(pool.price)),
                                    "tp_label": "Previous Swing High (Liquidity Pool - TP)" if side == "BUY" else "Previous Swing Low (Liquidity Pool - TP)",
                                    "outcome": outcome,
                                    "exit_index": exit_idx,
                                    "exit_price": _r(exit_price),
                                    "realized_r": realized_r,
                                    "pattern_name": pname,
                                    "label": f"V6 {'LONG' if side == 'BUY' else 'SHORT'} (R:R {rr})",
                                }

        setup_valid = bool(choch_ok and bos_ok and liq_ok and pat_ok and conf_ok and tp_ok and exec_ok and trade_obj is not None)
        val = {
            "side": side,
            "structure_passed": bool(choch_ok and bos_ok),
            "choch_passed": choch_ok,
            "bos_passed": bos_ok,
            "liquidity_passed": liq_ok,
            "pattern_passed": pat_ok,
            "confirmation_passed": conf_ok,
            "confirmation_count": conf_count,
            "target_pool_passed": tp_ok,
            "execution_passed": exec_ok,
            "setup_valid": setup_valid,
            "confirm_steps": confirm_steps,
            "rejection_reasons": reasons,
        }
        return {"validation": val, "trade": trade_obj}

    # Evaluate setups strictly using canonical validation (one source of truth for UI flow, checklist, summary & trades)
    all_setups = list(getattr(st, "setups", []) or [])
    raw_sweep_count = len(all_sweeps)
    global_pattern_count = len(all_patterns)
    primary_meta: Optional[Dict[str, Any]] = None
    primary_trade: Optional[Dict[str, Any]] = None
    canonical_validation: Optional[Dict[str, Any]] = None

    evaluated_setups: List[tuple] = []
    for rec in all_setups:
        side = "BUY" if rec.setup_side == BUY else "SELL"
        if direction != "both" and ((direction == "long" and side != "BUY") or (direction == "short" and side != "SELL")):
            continue
        ev_res = _validate_setup(rec)
        evaluated_setups.append((rec, ev_res))
        if ev_res["validation"]["setup_valid"]:
            pat_names: List[str] = []
            meta = _add_setup_marks(rec, mark_confirm=True, confirm_steps=ev_res["validation"]["confirm_steps"], pat_name_out=pat_names)
            trades.append(ev_res["trade"])
            primary_meta = meta
            primary_trade = ev_res["trade"]
            canonical_validation = ev_res["validation"]

    setup_sweep_count = sum(1 for _, ev in evaluated_setups if ev["validation"]["liquidity_passed"])
    setup_pattern_count = sum(1 for _, ev in evaluated_setups if ev["validation"]["pattern_passed"])

    # If no full confirmed trade passed ALL strict gates, show the latest evaluated setup (with its canonical validation) or structural context
    if not trades:
        if evaluated_setups:
            last_rec, last_ev = evaluated_setups[-1]
            canonical_validation = last_ev["validation"]
            primary_meta = _add_setup_marks(last_rec, mark_confirm=False)
        else:
            has_ch = len(choch_by_id) > 0
            has_b = len(bos_by_id) > 0
            # Never mark setup-stage liquidity/pattern as PASS when 0 qualifying setup events exist
            canonical_validation = {
                "side": "NEUTRAL",
                "structure_passed": has_ch and has_b,
                "choch_passed": has_ch,
                "bos_passed": has_b,
                "liquidity_passed": False,
                "pattern_passed": False,
                "confirmation_passed": False,
                "confirmation_count": 0,
                "target_pool_passed": False,
                "execution_passed": False,
                "setup_valid": False,
                "confirm_steps": [],
                "rejection_reasons": ["No complete V6 setup candidate passed all gates"],
            }
            if choch_by_id:
                last_ch = list(choch_by_id.values())[-1]
                o_idx = _origin_idx(last_ch, last_ch.index)
                ch_side = "BUY" if last_ch.direction.value == "bullish" else "SELL"
                ch_sub = "Bearish -> Bullish" if last_ch.direction.value == "bullish" else "Bullish -> Bearish"
                lines.append({"kind": "CHoCH", "label": "CHoCH", "sublabel": ch_sub,
                              "start": o_idx, "end": last_ch.index, "price": _r(last_ch.level), "side": ch_side})
            if bos_by_id:
                last_b = list(bos_by_id.values())[-1]
                o_idx = _origin_idx(last_b, last_b.index)
                b_side = "BUY" if last_b.direction.value == "bullish" else "SELL"
                b_sub = "Bullish Structure" if last_b.direction.value == "bullish" else "Bearish Structure"
                lines.append({"kind": "BOS", "label": "BOS", "sublabel": b_sub,
                              "start": o_idx, "end": last_b.index, "price": _r(last_b.level), "side": b_side})
            if all_sweeps:
                sw_ev = all_sweeps[-1]
                sw_side = "BUY" if sw_ev.side == "SSL" else "SELL"
                sw_sub = "Took Out Lows" if sw_side == "BUY" else "Took Out Highs"
                p_obj = pool_by_id.get(sw_ev.pool_id)
                lines.append({"kind": "SWEEP", "label": "Liquidity Sweep", "sublabel": sw_sub,
                              "start": p_obj.stamp.index if p_obj is not None else max(0, sw_ev.index - 10),
                              "end": sw_ev.index, "price": _r(sw_ev.level), "side": sw_side})
                markers.append({"index": sw_ev.index, "price": _r(sw_ev.extreme),
                                "kind": "SWEEP", "label": "Liquidity Sweep", "sublabel": sw_sub,
                                "side": sw_side, "pool_level": _r(sw_ev.level)})
            if all_patterns:
                pat_ev = all_patterns[-1]
                pat_side = "BUY" if pat_ev.direction == "BULLISH" else "SELL"
                lbl = _fmt_pat_name(pat_ev.pattern_label or pat_ev.pattern_type)
                zones.append({"kind": "PATTERN", "label": lbl, "sublabel": "Pattern",
                              "start": pat_ev.start_candle, "end": pat_ev.end_candle,
                              "high": _r(pat_ev.pattern_high), "low": _r(pat_ev.pattern_low), "side": pat_side})
                markers.append({"index": pat_ev.end_candle,
                                "price": _r(pat_ev.pattern_low if pat_side == "BUY" else pat_ev.pattern_high),
                                "kind": "PATTERN", "label": lbl, "sublabel": "Pattern", "side": pat_side})

    assert canonical_validation is not None
    v = dict(
        canonical_validation,
        raw_sweep_count=raw_sweep_count,
        setup_sweep_count=setup_sweep_count,
        global_pattern_count=global_pattern_count,
        setup_pattern_count=setup_pattern_count,
    )

    # Build Key Candles OHLC, Structure & Logic Summary, and V6 Concepts breakdown from the canonical validation
    key_candles: List[Dict[str, Any]] = []
    if primary_meta and primary_trade and v["setup_valid"]:
        row_no = 1
        seen_c = set()

        def _push_kc(c_idx: int, note: str, hl: str):
            nonlocal row_no
            if 0 <= c_idx < n and c_idx not in seen_c:
                seen_c.add(c_idx)
                bar = candles[c_idx]
                key_candles.append({
                    "num": row_no, "index": c_idx,
                    "open": _r(bar.open), "high": _r(bar.high),
                    "low": _r(bar.low), "close": _r(bar.close),
                    "note": note, "highlight": hl,
                })
                row_no += 1

        if primary_meta.get("sweep") and primary_meta["sweep"].get("verified"):
            sw_m = primary_meta["sweep"]
            _push_kc(sw_m["index"], f"Liquidity Sweep ({'Lows Taken' if primary_trade['side'] == 'BUY' else 'Highs Taken'})", "bad")
        if primary_meta.get("pattern"):
            pt_m = primary_meta["pattern"]
            _push_kc(pt_m["end"], f"{pt_m['label']} (Pattern)", "warn")
        steps = primary_meta.get("confirm_steps") or []
        total_s = len(steps)
        for s_i, c_idx in enumerate(steps, start=1):
            _push_kc(c_idx, f"Confirm Candle ({s_i}/{total_s})", "info")
        _push_kc(primary_trade["entry_index"], f"ENTRY ({primary_trade['entry_mode']})", "entry")
        if primary_trade["outcome"] in ("TARGET HIT", "STOPPED OUT"):
            _push_kc(
                primary_trade["exit_index"],
                "TARGET HIT (Liquidity Pool)" if primary_trade["outcome"] == "TARGET HIT" else "STOPPED OUT (Structural SL)",
                "good" if primary_trade["outcome"] == "TARGET HIT" else "bad",
            )
    else:
        for ev_num, mk in enumerate([m for m in markers if m.get("kind") != "CONFIRM_STEP"][-5:], start=1):
            idx = int(mk["index"])
            if 0 <= idx < n:
                bar = candles[idx]
                key_candles.append({
                    "num": ev_num, "index": idx,
                    "open": _r(bar.open), "high": _r(bar.high),
                    "low": _r(bar.low), "close": _r(bar.close),
                    "note": f"{mk['label']} ({mk.get('sublabel') or mk['kind']})",
                    "highlight": "info",
                })

    pat_label_summary = (
        primary_trade.get("pattern_name") if primary_trade and primary_trade.get("pattern_name")
        else (primary_meta["pattern"]["label"] if primary_meta and primary_meta.get("pattern") else "Pattern")
    )
    logic_summary: List[Dict[str, Any]] = []
    if primary_trade and v["setup_valid"]:
        side_word = "Bullish" if primary_trade["side"] == "BUY" else "Bearish"
        init_trend = "Downtrend (LL, LH)" if primary_trade["side"] == "BUY" else "Uptrend (HH, HL)"
        ch_price = primary_meta["choch"]["price"] if primary_meta and primary_meta.get("choch") else "-"
        bs_price = primary_meta["bos"]["price"] if primary_meta and primary_meta.get("bos") else "-"
        sw_price = primary_meta["sweep"]["level"] if primary_meta and primary_meta.get("sweep") else "-"
        steps = primary_meta.get("confirm_steps") if primary_meta else []
        res_sign = "+" if primary_trade["realized_r"] >= 0 else ""
        logic_summary = [
            {"step": 1, "title": "Trend", "detail": f"Prior {init_trend} transitioning toward {side_word.lower()} orderflow."},
            {"step": 2, "title": "CHoCH", "detail": f"First structure shift detected at {ch_price}."},
            {"step": 3, "title": "BOS", "detail": f"Continuation break at {bs_price} confirming {side_word.lower()} structure."},
            {"step": 4, "title": "Liquidity Sweep", "detail": f"Swept {'prior lows' if primary_trade['side'] == 'BUY' else 'prior highs'} around {sw_price}."},
            {"step": 5, "title": "Pattern", "detail": f"{pat_label_summary} formed right after the sweep."},
            {"step": 6, "title": "3-Candle Confirm", "detail": f"{len(steps)} distinct completed confirmation candles closed in trade direction (#{steps[0] + 1}..#{steps[-1] + 1})."},
            {"step": 7, "title": "Entry", "detail": f"{primary_trade['entry_mode']} at {primary_trade['entry']} (bar #{primary_trade['entry_index'] + 1})."},
            {"step": 8, "title": "Stop Loss", "detail": f"Structural {'below swept low' if primary_trade['side'] == 'BUY' else 'above swept high'} at {primary_trade['sl']} (Risk {primary_trade['risk_pts']})."},
            {"step": 9, "title": "Take Profit", "detail": f"Prior opposing liquidity pool at {primary_trade['tp']} (bar #{primary_trade['tp_pool_index'] + 1}, R:R {primary_trade['rr']})."},
            {"step": 10, "title": "Result", "detail": f"{primary_trade['outcome']} ({res_sign}{primary_trade['realized_r']}R)."},
        ]
    else:
        rej_text = "; ".join(v["rejection_reasons"]) if v["rejection_reasons"] else "Setup gates incomplete"
        logic_summary = [
            {"step": 1, "title": "Structure", "detail": f"CHoCH={'PASS' if v['choch_passed'] else 'FAIL'}, BOS={'PASS' if v['bos_passed'] else 'FAIL'} ({len(choch_by_id)} CHoCH, {len(bos_by_id)} BOS across {n} bars)."},
            {"step": 2, "title": "Liquidity Sweep", "detail": f"Setup={'PASS' if v['liquidity_passed'] else 'NONE'} ({setup_sweep_count} qualified, {raw_sweep_count} raw across {len(pools)} pool(s))."},
            {"step": 3, "title": "Pattern & Confirmation", "detail": f"Setup Pattern={'PASS' if v['pattern_passed'] else 'NONE'} ({setup_pattern_count} qualified, {global_pattern_count} global), 3-Candle Confirm={v['confirmation_count']}/3 ({'PASS' if v['confirmation_passed'] else 'FAIL'})."},
            {"step": 4, "title": "Execution & Target Gate", "detail": f"Target Pool={'PASS' if v['target_pool_passed'] else 'FAIL'}, Entry={'PASS' if v['execution_passed'] else 'FAIL'} — {rej_text}."},
        ]

    # ALL UI views (concepts, v6_flow, checklist) derive strictly from the single canonical `validation` object
    has_choch = bool(v["choch_passed"])
    has_bos = bool(v["bos_passed"])
    has_struct = bool(v["structure_passed"])
    has_sweep = bool(v["liquidity_passed"])
    has_pat = bool(v["pattern_passed"])
    has_conf = bool(v["confirmation_passed"])
    has_tp = bool(v["target_pool_passed"])
    has_trade = bool(v["setup_valid"])

    concepts = [
        {"name": "CHoCH", "detail": "Change of Character", "passed": has_choch},
        {"name": "BOS", "detail": "Break of Structure", "passed": has_bos},
        {"name": "Liquidity Sweep", "detail": f"{setup_sweep_count} setup-qualified ({raw_sweep_count} raw)", "passed": has_sweep},
        {"name": "Candlestick Pattern", "detail": pat_label_summary if has_pat else f"0 setup-qualified ({global_pattern_count} global)", "passed": has_pat},
        {"name": "3-Candle Confirm", "detail": f"{v['confirmation_count']}/3 completed candles", "passed": has_conf},
        {"name": "Structural SL", "detail": "Protected beyond sweep wick", "passed": has_trade},
        {"name": "Pool TP", "detail": "Actual prior opposing liquidity pool", "passed": has_tp},
    ]

    v6_flow = {
        "flow_text": "CHoCH -> BOS -> Liquidity Sweep -> Pattern -> 3-Candle Confirm -> Entry (C+1) -> SL (Structural) -> TP (Liquidity Pool)",
        "modules": [
            {"key": "A", "label": "Market Structure: CHoCH & BOS", "passed": has_struct},
            {"key": "B", "label": f"Liquidity: Sweep ({'Lows' if v['side'] == 'BUY' else ('Highs' if v['side'] == 'SELL' else f'0 setup / {raw_sweep_count} raw')})", "passed": has_sweep},
            {"key": "C", "label": f"Candlestick Pattern: {pat_label_summary if has_pat else f'0 setup / {global_pattern_count} global'}", "passed": has_pat},
            {"key": "D", "label": f"3-Candle Confirmation ({v['confirmation_count']}/3)", "passed": has_conf},
            {"key": "E", "label": "Execution: C+1 Entry, Structural SL, Pool TP", "passed": has_trade},
        ],
    }

    checklist = [
        {"step": "1. CHoCH", "passed": has_choch,
         "detail": f"{'PASS' if has_choch else 'FAIL'} ({len(choch_by_id)} CHoCH break(s))"},
        {"step": "2. BOS", "passed": has_bos,
         "detail": f"{'PASS' if has_bos else 'FAIL'} ({len(bos_by_id)} BOS break(s))"},
        {"step": "3. Liquidity Sweep", "passed": has_sweep,
         "detail": f"{'PASS' if has_sweep else 'NONE'} ({setup_sweep_count} setup-qualified, {raw_sweep_count} raw)"},
        {"step": "4. Candlestick Pattern", "passed": has_pat,
         "detail": f"{'PASS' if has_pat else 'NONE'} ({setup_pattern_count} setup-qualified, {global_pattern_count} global)"},
        {"step": "5. 3-Candle Confirm & Execution", "passed": has_trade,
         "detail": f"{len(trades)} confirmed setup(s) ({v['confirmation_count']}/3 confirm, min R:R {min_rr})"
         if has_trade else f"REJECTED: {'; '.join(v['rejection_reasons']) or 'incomplete'}"},
    ]
    return {
        "swings": swings,
        "lines": lines,
        "zones": zones,
        "markers": markers,
        "trades": trades,
        "validation": v,
        "checklist": checklist,
        "v6_flow": v6_flow,
        "key_candles": key_candles,
        "logic_summary": logic_summary,
        "concepts": concepts,
    }


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

    calibration = body.get("calibration")
    if isinstance(calibration, dict) and not calibration.get("available", False):
        reason = str(calibration.get("reason") or "Need at least 2 reliable price-axis tick labels for calibration.")
        return {
            "scanner_version": version,
            "strategy_name": STRATEGY_META[version]["name"],
            "strategy_summary": STRATEGY_META[version]["summary"],
            "candle_count": int(body.get("candle_count") or len(body.get("candles") or [])),
            "calibration_available": False,
            "calibration_reason": reason,
            "summary": {"bias": "UNAVAILABLE", "setups_found": 0, "best_rr": 0.0},
            "swings": [],
            "lines": [],
            "zones": [],
            "markers": [],
            "trades": [],
            "checklist": [
                {"step": "0. Price Axis Calibration", "passed": False, "detail": reason},
                {"step": "Trade Generation", "passed": False, "detail": "Refused: reliable price-axis calibration unavailable"},
            ],
        }

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
        "calibration_available": True,
        "summary": {"bias": bias, "setups_found": len(trades), "best_rr": best_rr},
        **res,
    }
