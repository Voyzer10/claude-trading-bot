#!/usr/bin/env python3
"""
research_fno_sv4.py - Scanner v4 on F&O stocks, traded by BUYING the at-the-money option (a call for a long setup,
a put for a short one). Walk-forward 70/30, R after costs, on the INDIA paper account's real limits.

    python research.py fno-sv4

How the option is priced (expired contracts have no price history on Yahoo or Kite, so this is a MODEL):
  * the setup comes from the stock's own 5-minute candles (scanner_v4.sequence, intraday, exactly as live);
  * the option: nearest monthly expiry at least 3 days away, the strike nearest the price, Black-Scholes with the
    stock's own recent volatility (20 days of 5-minute moves, x1.15 for the usual implied-over-realised premium);
  * entry premium at the entry, the premium STOP = the option's value with the stock at its stop (same moment),
    exit premium = the option's value at the exit price AND the exit time (so theta decay is paid);
  * costs: half a percent of the premium of spread / slippage each way (min 5 paise), plus paper.py's F&O charges
    (brokerage, STT, exchange, stamp, GST);
  * sizing like paper.py: lots so the loss at the premium stop stays within max_loss_per_trade_fno (Rs 1,500) and
    the premium within max_position_pct_fno (40%) of Rs 50,000; at most max_trades_per_day (5) a day. A setup
    where even ONE lot risks more than that is counted as "does not fit the account" and not traded.
  * lot size: the exchange sets roughly Rs 5-7 lakh of stock per lot; here ceil(500000 / price) is used.

The same trades in the cash stock (what nse-sv4 measures) are shown next to it, so the option effect is visible.
"""
import itertools
import math
from datetime import datetime, timedelta, timezone

import fno as F
import scanner_v4 as V4

UTC = timezone.utc
IV_OVER_RV = 1.15
SPREAD = 0.005
MIN_DAYS = 3


def realised_vol(rows, i, n=375, per_day=75):
    """Annualised volatility from the 5-minute closes before candle i (per_day candles a day, 252 days)."""
    a = max(1, i - n)
    rets = [math.log(rows[k][4] / rows[k - 1][4]) for k in range(a, i) if rows[k - 1][4] > 0 and rows[k][4] > 0]
    if len(rets) < 50:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1))
    return min(0.8, max(0.1, sd * math.sqrt(per_day * 252) * IV_OVER_RV))


def strike_step(px):
    for lim, st in ((250, 2.5), (500, 5), (1000, 10), (2500, 20), (5000, 50)):
        if px < lim:
            return st
    return 100


def monthly_expiry(d):
    """The stock-option expiry used: last Tuesday of the month, rolled to next month inside MIN_DAYS."""
    y, m = d.year, d.month
    for _ in range(3):
        e = F.last_weekday_of_month(y, m, F.EXPIRY_WEEKDAY)
        if (e - d).days >= MIN_DAYS:
            return e
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return e


def weekly_expiry_us(d):
    """US F&O (QQQ / SPY): the Friday expiry at least us_options.MIN_DAYS calendar days away."""
    import us_options as UO
    e = d + timedelta(days=(4 - d.weekday()) % 7)
    while (e - d).days < UO.MIN_DAYS:
        e += timedelta(days=7)
    return e


def _us_years(exp, t):
    import us_options as UO
    return UO.years_to(exp, t)


# what differs between the markets: India (NFO: monthly stock / index options, Rs, paper.py F&O charges) and the
# US (owner, 13 Nov 2026: QQQ / SPY ATM weekly options, $, the USFNO account's fee_pct per side, 100 a contract)
SPEC_IN = {"account": "FNO", "expiry": monthly_expiry, "years": F.years_to, "step": strike_step, "per_day": 75,
           "rate": F.RATE, "spread": SPREAD, "tick": 0.05, "min_premium": 0.5, "cur": "Rs", "window": ((9, 30), (14, 30)),
           "tz_name": "IST", "fees": None}
SPEC_US = {"account": "USFNO", "expiry": weekly_expiry_us, "years": _us_years, "step": lambda px: 1.0, "per_day": 78,
           "rate": 0.045, "spread": 0.0, "tick": 0.01, "min_premium": 0.2, "cur": "$", "window": ((9, 45), (15, 30)),
           "tz_name": "New York", "fees": "fee_pct"}


def option_trade(t, rows, tz_local, cfg, acc, lot_size=None, spec=None):
    """One Scanner v4 trade as an ATM option bought: dict with r (option R after costs), money, lots... or a reason
    string when it can not be traded."""
    spec = spec or SPEC_IN
    i, k = t["i"], t["exit_i"]
    s0, s_stop, s1 = t["entry"], t["stop"], t["exit"]
    vol = realised_vol(rows, i, n=5 * spec["per_day"], per_day=spec["per_day"])
    if vol is None:
        return "not enough history"
    t0, t1 = rows[i][0] + timedelta(minutes=5), rows[k][0] + timedelta(minutes=5)
    exp = spec["expiry"](t0.astimezone(tz_local).date())
    kind = "CE" if t["side"] == "long" else "PE"
    step = spec["step"](s0)
    strike = round(s0 / step) * step
    y0, y1 = spec["years"](exp, t0), spec["years"](exp, t1)
    r = spec["rate"]
    p0 = F.bs(s0, strike, y0, vol, kind, r)[0]
    p_stop = F.bs(s_stop, strike, y0, vol, kind, r)[0]
    p1 = F.bs(s1, strike, y1, vol, kind, r)[0]
    tick, sp = spec["tick"], spec["spread"]
    if p0 <= spec["min_premium"] or p0 - p_stop <= tick:
        return "premium too small"
    buy = p0 + (max(tick, p0 * sp) if sp else 0)
    sell = max(tick, p1 - (max(tick, p1 * sp) if sp else 0))
    stop_fill = p_stop - (max(tick, p_stop * sp) if sp else 0)
    risk_unit = buy - stop_fill
    if spec["fees"] == "fee_pct":   # the account's fee_pct a side, as paper.py charges it (fees + spread)
        risk_unit += (buy + stop_fill) * float(acc.get("fee_pct") or 0) / 100
    lot = lot_size or max(1, math.ceil(500000 / s0))
    lots = int(min(acc["max_loss_per_trade_fno"] / (risk_unit * lot),
                   acc["capital"] * acc["max_position_pct_fno"] / 100 / (buy * lot)))
    if lots < 1:
        return "does not fit the account"
    import paper as P
    name = "%s-%s-%s-%s" % ("STK", exp.strftime("%Y%m%d"), int(strike) if strike == int(strike) else strike, kind)
    qty = lots * lot
    if spec["fees"] == "fee_pct":
        fees = qty * (buy + sell) * float(acc.get("fee_pct") or 0) / 100
    else:
        fees = P.charges(cfg, "NFO", name, "buy", qty * buy) + P.charges(cfg, "NFO", name, "sell", qty * sell)
    money = qty * (sell - buy) - fees
    sg = 1 if t["side"] == "long" else -1
    return {"r": money / (qty * risk_unit), "money": money, "lots": lots, "lot": lot, "premium": round(buy, 2),
            "risk": qty * risk_unit, "stock_r": (s1 - s0) * sg / ((s0 - s_stop) * sg), "vol": vol,
            "held_min": (t1 - t0).total_seconds() / 60}


def events(data, tz_local, cfg, acc, entry_ok, lot_size=None, spec=None):
    evs, skipped = [], {}
    trail = V4.tm_settings(acc)   # the FNO account's Settings > Trade Manager
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if len(rows) < 250:
            continue
        for rr in (0.0, 1.0, 2.0):
            try:
                seq = V4.sequence(rows, lambda x: x.astimezone(tz_local).date(), intraday=True, min_rr=rr,
                                  max_hold=None, **trail)
            except Exception:
                continue
            for t in seq:
                if t.get("exit") is None or t.get("exit_i") is None or not entry_ok(rows[t["i"]][0]):
                    continue
                o = option_trade(t, rows, tz_local, cfg, acc, lot_size, spec)
                if isinstance(o, str):
                    if rr == 0.0:
                        skipped[o] = skipped.get(o, 0) + 1
                    continue
                o.update(sym=sym, day=rows[t["i"]][0].astimezone(tz_local).date().isoformat(), i=t["i"],
                         side=t["side"], kind=t["kind"], min_rr=rr, exit_reason=t["exit_reason"])
                evs.append(o)
    evs.sort(key=lambda e: (e["day"], e["i"], e["sym"]))
    return evs, skipped


def pick(evs, f, max_per_day):
    """The trades one account would take: filters, then the first max_per_day of each day."""
    out, per = [], {}
    for e in evs:
        if e["min_rr"] != f["min_rr"] or (f["side"] != "both" and e["side"] != f["side"]) or \
                (f["trades"] != "both" and e["kind"] != f["trades"]):
            continue
        if per.get(e["day"], 0) >= max_per_day:
            continue
        per[e["day"]] = per.get(e["day"], 0) + 1
        out.append(e)
    return out


def score(evs, f, split, stats, max_per_day, field="r"):
    ins, oos = {}, {}
    for e in pick(evs, f, max_per_day):
        (ins if e["day"] < split else oos).setdefault(e["day"], []).append(e[field])
    return {"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos)}


def money_line(evs, f, split, max_per_day, capital, cur="Rs"):
    tr = pick(evs, f, max_per_day)
    o = [e for e in tr if e["day"] >= split]
    days = sorted({e["day"] for e in o})
    tot = sum(e["money"] for e in o)
    if not days:
        return "no out-of-sample trades"
    per_month = tot / len(days) * 21
    return "out-of-sample: %s %+.0f over %d trading days (%s %+.0f a day, about %s %+.0f / %+.1f%% a month on %s %d)" % (
        cur, tot, len(days), cur, tot / len(days), cur, per_month, 100 * per_month / capital, cur, capital)


def row(r, label=""):
    f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]

    def s(x):
        if not x.get("trades"):
            return "no trades"
        return "%4d tr (%.1f/day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    return "%sside=%s trades=%s min_rr=%g\n     in-sample   %s\n     OUT-sample  %s" % (
        label, f["side"], f["trades"], f["min_rr"], s(i), s(o))


def main(a, syms, src, fetch_all, stats, out_dir, tz_local, suffix=".NS", lot_size=None, mode="fno-sv4", spec=None):
    """mode "fno-sv4": Nifty 50 stocks; "bnf-sv4" / "nifty-sv4": the Bank Nifty / Nifty 50 index (exchange lot; owner
    12 Nov 2026: F&O only on these two, sized from the FNO account, Rs 1,00,000); "usopt-sv4": QQQ and SPY ATM weekly
    options (owner, 13 Nov 2026), sized from the USFNO account ($50,000), spec=SPEC_US."""
    import os
    import paper as P
    spec = spec or SPEC_IN
    cfg = P.DEFAULT_CONFIG
    acc = dict(cfg["accounts"][spec["account"]])
    try:   # the account's saved limits and Trade Manager, as paper.py would use them
        acc.update(P.load_config()["accounts"].get(spec["account"], {}))
    except Exception:
        pass
    cur, (w0, w1) = spec["cur"], spec["window"]
    print("Fetching 60 days of 5-minute bars for %d F&O underlyings (%s)..." % (len(syms), src), flush=True)
    data, _ = fetch_all(syms, suffix, "5m", a.workers)

    def entry_ok(t):
        lt = t.astimezone(tz_local)
        return w0 <= (lt.hour, lt.minute) <= w1
    evs, skipped = events(data, tz_local, cfg, acc, entry_ok, lot_size, spec)
    if not evs:
        print("No Scanner v4 option trades: no data came back (check the internet / Yahoo).")
        return 1
    mpd = int(acc.get("max_trades_per_day") or 5)
    days = sorted({e["day"] for e in evs})
    split = days[int(len(days) * 0.7)]
    live = {"side": "both", "trades": "both", "min_rr": 0.0}
    base = pick(evs, live, 10 ** 6)
    lines = ["research.py %s  %s" % (mode, datetime.now(tz_local).strftime("%Y-%m-%d %H:%M %Z")),
             "Scanner v4 setups on %d F&O underlyings (%s), traded by BUYING the ATM option (call for long, put for short), "
             "intraday, entries %d:%02d-%d:%02d %s, flat by the close. Option prices are a Black-Scholes MODEL (the "
             "underlying's own volatility x%.2f, theta paid), costs: %s. Sizing: %s %d max loss, %d%% of %s %d premium "
             "cap, %d trades a day." % (
                 len(data), src, w0[0], w0[1], w1[0], w1[1], spec["tz_name"], IV_OVER_RV,
                 ("%.1f%% of the premium a side (the USFNO account's fee_pct: contract fees + spread)" % float(acc.get("fee_pct") or 0))
                 if spec["fees"] == "fee_pct" else "spread %.1f%% a side + paper.py F&O charges" % (spec["spread"] * 100),
                 cur, acc["max_loss_per_trade_fno"], acc["max_position_pct_fno"], cur, acc["capital"], mpd),
             "%d days (%s..%s), out-of-sample = days from %s. Live-reading setups: %d tradable; not tradable: %s." % (
                 len(days), days[0], days[-1], split, len(base), skipped or "none"),
             "Typical trade: premium %s %.2f, %.1f lots, risk %s %.0f, held %.0f min." % (
                 cur, sorted(e["premium"] for e in base)[len(base) // 2], sum(e["lots"] for e in base) / len(base),
                 cur, sum(e["risk"] for e in base) / len(base), sum(e["held_min"] for e in base) / len(base)), "",
             row(score(evs, live, split, stats, mpd), "LIVE as OPTIONS (what would be paper traded):  "),
             row(score(evs, live, split, stats, mpd, "stock_r"), "the same trades in the UNDERLYING (no costs):  "),
             "  money: " + money_line(evs, live, split, mpd, acc["capital"], cur), ""]
    for f in (dict(live, side="long"), dict(live, side="short"), dict(live, trades="primary"),
              dict(live, trades="secondary"), dict(live, min_rr=1.0), dict(live, min_rr=2.0)):
        lines.append(row(score(evs, f, split, stats, mpd), "  "))
    grid = {"side": ["long", "short", "both"], "trades": ["primary", "secondary", "both"], "min_rr": [0.0, 1.0, 2.0]}
    res = [score(evs, dict(zip(grid, c)), split, stats, mpd) for c in itertools.product(*grid.values())]
    res = [r for r in res if r["in_sample"].get("trades", 0) >= 20 and r["out_of_sample"].get("trades", 0) >= 10]
    good = [r for r in res if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0]
    lv = score(evs, live, split, stats, mpd)["out_of_sample"]
    verdict = ("PASS: the live setting is positive out of sample (%+.2fR a trade over %d trades). Small sample: "
               "paper trade it and keep checking." % (lv["avg_r"], lv["trades"])) if lv.get("trades", 0) >= 20 and \
        lv["avg_r"] > 0 else "FAIL: no edge out of sample for the live setting (%s). Do not trade these options." % (
            "%+.2fR a trade over %d trades" % (lv["avg_r"], lv["trades"]) if lv.get("trades") else "no trades")
    lines += ["", "%d of %d combinations (with enough trades) positive both in- and out-of-sample." % (len(good), len(res)),
              "VERDICT: " + verdict]
    text = "\n".join(lines)
    print(text)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s_%s.txt" % (mode, datetime.now(tz_local).strftime("%Y%m%d_%H%M")))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\nSaved: %s" % path)
    return 0
