#!/usr/bin/env python3
"""
research_scanner_v6.py - walk-forward 70/30 backtest of Scanner v6 (scanner_v6: CHoCH -> BOS -> Liquidity Sweep ->
Candlestick Pattern -> 3-Candle Confirmation -> Structural SL & Opposing Liquidity TP), R after costs.

    python research.py crypto-sv6       # crypto, 15-minute candles
    python research.py crypto-sv6-5m    # crypto, 5-minute candles
    python research.py us-sv6           # US stocks, 5m, intraday
    python research.py nse-sv6          # NSE stocks, 5m, intraday (India charges)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import scanner_v6_bridge as V6B
from scanner_v6.data.candle_models import Candle
from scanner_v6.data.market_config import ConfigOrigin, MarketDataConfig
from scanner_v6.entry.confirmation import CONFIRMED, ConfirmationStream
from scanner_v6.exit.stop_loss import BUY, structural_sl, to_grid
from scanner_v6.exit.targets import PoolView, select_target_pool, target_price

UTC = timezone.utc
ROUNDING = "ROUND_HALF_UP"


def _walk(rows, day_of, i, entry, stop, target, side, max_hold, intraday, be_at_r=None):
    """Simulate exit from candle i+1 onwards (stop first on same bar, optional BE move, intraday EOD flatten)."""
    sh = side == "short"
    n = len(rows)
    entry_day = day_of(rows[i][0])
    last_j = min(n - 1, i + max_hold)
    cur_stop = stop
    risk = abs(entry - stop)
    moved_be = False
    for j in range(i + 1, last_j + 1):
        dt, _o, h, l, c, _v = rows[j]
        if intraday and day_of(dt) != entry_day:
            prev_c = rows[j - 1][4]
            return prev_c, "eod", moved_be
        if (h >= cur_stop) if sh else (l <= cur_stop):
            return cur_stop, ("breakeven" if moved_be else "stop"), moved_be
        if (l <= target) if sh else (h >= target):
            return target, "target", moved_be
        if be_at_r and not moved_be and risk > 0:
            fav = (entry - l) if sh else (h - entry)
            if fav >= be_at_r * risk:
                cur_stop = entry
                moved_be = True
    return rows[last_j][4], "max_hold", moved_be


def _sim_symbol(sym, rows, day_of, cost_fn, market, step_sec, intraday=False, max_hold=48, entry_ok=None,
                sl_buffer_ticks=2, tp_offset_ticks=1, be_at_r=None, diag=None):
    if len(rows) < 60:
        return []
    T = V6B.tick_for(market, rows)
    tf = timedelta(seconds=step_sec)
    mkt = MarketDataConfig(origin=ConfigOrigin.INSTRUMENT_CONFIG, instrument_id=sym, timeframe=tf,
                           tick_size=float(T), session=None)
    st = ConfirmationStream(sym, "%ds" % step_sec, mkt)
    candles = []
    seen_confirmed = set()
    trades = []

    for k, r in enumerate(rows):
        c = Candle(k, r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
        st.on_candle(c)
        candles.append(c)
        for rec in st.setups:
            if rec.status != CONFIRMED or rec.key in seen_confirmed or not rec.history:
                continue
            conf_i = rec.history[-1].index
            if conf_i != k or k >= len(rows) - 1:
                continue
            seen_confirmed.add(rec.key)
            if entry_ok and not entry_ok(rows[k][0]):
                continue
            sw = candles[rec.sweep_index]
            sl = structural_sl(rec.setup_side, Decimal(repr(sw.low)), Decimal(repr(sw.high)),
                               int(sl_buffer_ticks), T, ROUNDING)
            entry = to_grid(Decimal(repr(c.close)), T, ROUNDING)
            if (rec.setup_side == BUY and entry <= sl) or (rec.setup_side != BUY and entry >= sl):
                if diag is not None:
                    diag["entry_gap_rejects"] += 1
                continue
            lq = st.setup_stream.liquidity
            pools = [PoolView(p.id, "BSL" if p.side.value == "above" else "SSL", Decimal(repr(p.price)),
                              p.stamp.confirmed_index, lq.state[p.id]) for p in lq.pools]
            pool = select_target_pool(rec.setup_side, entry, pools)
            if pool is None:
                if diag is not None:
                    diag["target_rejects"] += 1
                continue
            tp = target_price(rec.setup_side, pool.price, int(tp_offset_ticks), T, ROUNDING)
            e_f, s_f, t_f = float(entry), float(sl), float(tp)
            risk = abs(e_f - s_f)
            if risk <= 0:
                continue
            rr = abs(t_f - e_f) / risk
            side = "long" if rec.setup_side == BUY else "short"
            exit_px, reason, _ = _walk(rows, day_of, k, e_f, s_f, t_f, side, max_hold, intraday, be_at_r=be_at_r)
            cost = cost_fn(sym, e_f, s_f, exit_px, side)
            if cost is None:
                continue
            sg = 1 if side == "long" else -1
            r_gross = (exit_px - e_f) * sg / risk
            r_net = r_gross - cost
            trades.append({
                "sym": sym, "day": day_of(rows[k][0]).isoformat(), "i": k, "side": side,
                "rr": rr, "r_gross": r_gross, "cost_r": cost, "r": r_net, "exit_reason": reason,
            })
    return trades


def events_v6(data, day_of, cost_fn, market, step_sec, intraday=False, max_hold=48, entry_ok=None,
              be_at_r=None, diag=None):
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if len(rows) < 120:
            continue
        try:
            evs.extend(_sim_symbol(sym, rows, day_of, cost_fn, market, step_sec,
                                   intraday=intraday, max_hold=max_hold, entry_ok=entry_ok,
                                   be_at_r=be_at_r, diag=diag))
        except Exception:
            continue
    evs.sort(key=lambda e: (e["day"], e["sym"], e["i"]))
    return evs


def _s(x):
    if not x.get("trades"):
        return "no trades"
    return "%4d tr (%.1f/day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
        x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
        x["worst_day_r"], x["max_drawdown_r"])


def _score(events, side, min_rr, split, stats):
    ins, oos = {}, {}
    for ev in events:
        if (side == "both" or ev["side"] == side) and ev["rr"] >= min_rr:
            (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["r"])
    return {"in_sample": stats(ins), "out_of_sample": stats(oos)}


def _profit_factor(rs):
    pos = sum(x for x in rs if x > 0)
    neg = -sum(x for x in rs if x < 0)
    return round(pos / neg, 2) if neg > 0 else (float("inf") if pos > 0 else 0.0)


def report(events, mode, what, costs, stats, tz_local, diag=None, events_be=None):
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)] if len(days) > 3 else (days[-1] if days else "")
    gross_r = sum(e.get("r_gross", e["r"]) for e in events)
    net_r = sum(e["r"] for e in events)
    fees_r = sum(e.get("cost_r", 0.0) for e in events)
    pf = _profit_factor([e["r"] for e in events])
    lines = [
        "=== SCANNER v6 BACKTEST (%s, walk-forward 70/30, R after costs) ===" % mode,
        "Data: %s  (%s .. %s, %d trading days)" % (what, days[0] if days else "-", days[-1] if days else "-", len(days)),
        "In-sample < %s; out-of-sample >= %s. Costs: %s." % (split, split, costs),
        "Rules: CHoCH -> BOS -> Liquidity Sweep -> Candlestick Pattern -> 3-Candle Confirm -> Structural SL & Pool TP.",
        "Gross: %+.2fR | Fees: %.2fR | Net: %+.2fR | Profit Factor: %s" % (gross_r, fees_r, net_r, pf),
        *(["Rejections: entry_gap=%d | no_opposing_pool=%d" % (diag.get("entry_gap_rejects", 0), diag.get("target_rejects", 0))] if diag else []),
        "",
    ]
    for side in ("both", "long", "short"):
        for min_rr in (1.0, 1.5, 2.0):
            r = _score(events, side, min_rr, split, stats)
            lines.append("side=%-5s min_rr=%.1f  | IS: %s | OOS: %s" % (
                side, min_rr, _s(r["in_sample"]), _s(r["out_of_sample"])))

    if events_be is not None:
        be_oos = _score(events_be, "both", 1.0, split, stats)["out_of_sample"]
        lines.append("Exit policy compare (OOS): FIXED_SL_TP=%s | BREAKEVEN(1R)=%s" % (
            _s(_score(events, "both", 1.0, split, stats)["out_of_sample"]), _s(be_oos)))

    lv = _score(events, "both", 1.0, split, stats)["out_of_sample"]
    lines.append("")
    if lv.get("trades", 0) >= 15 and lv["avg_r"] > 0:
        lines.append("VERDICT: PASS: Scanner v6 (both, min R:R 1.0) is positive out of sample (%+.2fR over %d trades)." % (
            lv["avg_r"], lv["trades"]))
    else:
        lines.append("VERDICT: FAIL: no edge out of sample (%s)." % (
            "%+.2fR over %d trades" % (lv["avg_r"], lv["trades"]) if lv.get("trades") else "no trades"))
    return "\n".join(lines)


def main(a, syms, src, fetch_all, stats, out_dir, tz_local, market="crypto", step=15):
    import paper as P
    entry_ok, intraday, max_hold = None, False, 48
    if market == "crypto":
        iv = "%dm" % step
        print("Fetching 60 days of %s bars for %d coins (%s)..." % (iv, len(syms), src), flush=True)
        data, _ = fetch_all(syms, "-USD", iv, a.workers)
        fee = float(P.load_config()["accounts"]["CRYPTO"]["fee_pct"]) / 100

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)
        day_of, max_hold = (lambda t: t.date()), 12 * 60 // step
        mode = "crypto-sv6" + ("" if step == 15 else "-%dm" % step)
        what, costs = "%d coins, %s candles, 12h max hold" % (len(data), iv), "%.3f%% fee a side" % (fee * 100)
        mkt_code, step_sec = "CRYPTO", step * 60
    elif market == "nse":
        print("Fetching 60 days of 5-minute bars for %d NSE symbols (%s)..." % (len(syms), src), flush=True)
        data, _ = fetch_all(syms, ".NS", "5m", a.workers)
        cfg = P.DEFAULT_CONFIG
        acc = cfg["accounts"]["INDIA"]

        def cost_fn(sym, entry, stop, exit_px, side):
            risk = abs(entry - stop)
            qty = int(min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / entry))
            if qty < 1:
                return None
            o, c = ("buy", "sell") if side == "long" else ("sell", "buy")
            return (P.charges(cfg, "NSE", sym, o, qty * entry) + P.charges(cfg, "NSE", sym, c, qty * exit_px)) / (qty * risk)

        def entry_ok(t):
            lt = t.astimezone(tz_local)
            return (9, 30) <= (lt.hour, lt.minute) <= (14, 30)
        day_of, intraday, max_hold = (lambda t: t.astimezone(tz_local).date()), True, 75
        mode, what = "nse-sv6", "%d NSE stocks, 5m candles, intraday" % len(data)
        costs = "paper.py India charges (STT, brokerage, ...)"
        mkt_code, step_sec = "NSE", 300
    else:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        print("Fetching 60 days of 5-minute bars for %d US symbols (%s)..." % (len(syms), src), flush=True)
        data, _ = fetch_all(syms, "", "5m", a.workers)
        fee = float(P.load_config()["accounts"]["US"].get("fee_pct", 0)) / 100 + 0.0002

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)

        def entry_ok(t):
            lt = t.astimezone(et)
            return (9, 45) <= (lt.hour, lt.minute) <= (15, 30)
        day_of, intraday, max_hold = (lambda t: t.astimezone(et).date()), True, 78
        mode, what = "us-sv6", "%d US stocks/ETFs, 5m candles, intraday" % len(data)
        costs = "%.3f%% a side (fee + assumed spread/slippage)" % (fee * 100)
        mkt_code, step_sec = "US", 300

    diag = {"entry_gap_rejects": 0, "target_rejects": 0}
    events = events_v6(data, day_of, cost_fn, mkt_code, step_sec,
                       intraday=intraday, max_hold=max_hold, entry_ok=entry_ok, be_at_r=None, diag=diag)
    if not events:
        print("No Scanner v6 trades found.")
        return 1
    events_be = events_v6(data, day_of, cost_fn, mkt_code, step_sec,
                          intraday=intraday, max_hold=max_hold, entry_ok=entry_ok, be_at_r=1.0)
    text = report(events, mode, what, costs, stats, tz_local, diag=diag, events_be=events_be)
    print(text)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s_%s.txt" % (mode, datetime.now(tz_local).strftime("%Y%m%d_%H%M")))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\nSaved: %s" % path)
    return 0
