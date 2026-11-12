#!/usr/bin/env python3
"""Scanner v4 (scanner_v4.py) against the owner's rules of 11 Nov 2026 (Final Trading Workflow + his answers).
Offline.

    python tests/test_scanner_v4.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scanner_v4 as V4  # noqa: E402
import smc_playbook as PB  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def build(tail, bos_vol=300):
    """Zigzag base (swing highs 100.6, lows 99.8), a decisive BOS candle closing 101.3 above 100.6 on 3x volume, a
    run to 103 (liquidity), a drop to 100.6, then `tail` (o, h, l, c). The BOS move started from the 99.8 low."""
    t, rows = [datetime(2026, 11, 3, tzinfo=timezone.utc)], []

    def add(o, h, l, c, v=100):
        rows.append((t[0], o, h, l, c, v))
        t[0] += timedelta(minutes=5)
    for k in range(40):
        b = 100 + (0.4 if (k // 3) % 2 else 0.0)
        add(b, b + 0.2, b - 0.2, b + 0.05)
    add(100.4, 101.4, 100.3, 101.3, bos_vol)        # BOS: closes above the 100.6 swing high
    for c in [(101.3, 101.6, 101.0, 101.5), (101.5, 101.6, 100.9, 101.0),
              (101.0, 103.0, 100.95, 102.9),         # the move's high 103 = liquidity for the target
              (102.9, 102.95, 100.6, 100.6)]:        # a drop (no close below 99.8 yet)
        add(*c)
    for c in tail:
        add(*c)
    return rows


SWEEP = (100.6, 100.7, 99.5, 99.6)        # CLOSES below the 99.8 low: the sweep
WICK = (100.6, 100.7, 99.5, 99.9)         # only a wick below 99.8, close above: not a sweep
INV = (99.62, 100.0, 99.58, 99.70)        # inverted hammer after the sweep (high 100.0)
HAMMER = (99.65, 99.9, 99.3, 99.85)       # hammer at the low: not a BUY signal
TRIG = (99.7, 100.2, 99.65, 100.1)        # closes above the signal high 100.0 -> BUY at the next open
UP1 = (100.1, 100.5, 100.0, 100.4)
TP = (100.4, 103.1, 100.3, 103.0)         # target 103 hit
DAY = lambda x: x.date()  # noqa: E731


def seq(rows, **kw):
    return V4.sequence(rows, DAY, **kw)


def longs(rows, **kw):
    return [t for t in seq(rows, **kw) if t["side"] == "long"]


if __name__ == "__main__":
    full = build([SWEEP, INV, TRIG, UP1, TP])
    s = longs(full)
    p1 = s[0] if s else {}
    check("1. primary BUY: BOS -> close below the old low -> inverted hammer -> next candle closes above its high",
          len(s) == 1 and p1["kind"] == "primary" and p1["signal_pattern"] == "inverted hammer"
          and p1["level"] == 99.8 and p1["level_name"] == "bos_origin", s)
    check("   entry at the next candle's open (100.1); stop below the sweep low 99.5 (0.1 ATR); target the 103 liquidity",
          p1.get("entry") == UP1[0] and p1.get("signal_close") == TRIG[3] and 99.3 < p1.get("stop", 0) < 99.5
          and p1.get("target") == 103.0 and p1.get("exit_reason") == "target", p1)
    check("2. a wick below the old low (close back above) is not a sweep: no trade",
          not longs(build([WICK, INV, TRIG, UP1, TP])))
    check("3. a hammer at the low is not a BUY signal", not longs(build([SWEEP, HAMMER, TRIG, UP1, TP])))
    # the owner's buying / selling candles (12 Nov 2026)
    kinds = {"classic": (99.7, 100.0, 99.6, 99.72), "gravestone": (99.62, 100.0, 99.6, 99.63),
             "long-legged": (99.8, 100.0, 99.6, 99.81), "dragonfly": (99.98, 100.0, 99.6, 99.99)}
    names = {k: V4.signal_kind((None,) + v) for k, v in kinds.items()}
    check("   signal candles: classic, gravestone and long-legged dojis are named; a dragonfly is not a BUY candle",
          names == {"classic": "doji", "gravestone": "gravestone doji", "long-legged": "long-legged doji",
                    "dragonfly": None}, names)
    got = {k: [t["signal_pattern"] for t in longs(build([SWEEP, v, TRIG, UP1, TP]))] for k, v in kinds.items()}
    check("   at the low: classic, gravestone and long-legged dojis give the BUY; a dragonfly doji does not",
          got == {"classic": ["doji"], "gravestone": ["gravestone doji"], "long-legged": ["long-legged doji"],
                  "dragonfly": []}, got)
    sells = {k: [t["signal_pattern"] for t in V4.sequence(V4.mirror(build([SWEEP, v, TRIG, UP1, TP])), DAY)
                 if t["side"] == "short"] for k, v in kinds.items()}
    check("   at the top (mirror): a dragonfly doji gives the SELL; a gravestone (mirror of the dragonfly) does not",
          sells == {"classic": ["doji"], "gravestone": ["dragonfly doji"], "long-legged": ["long-legged doji"],
                    "dragonfly": []}, sells)
    x1, x2 = (99.7, 99.95, 99.6, 99.9), (99.9, 99.98, 99.8, 99.95)
    check("4. the break-and-close on the 3rd candle after the signal: no trade",
          not longs(build([SWEEP, INV, x1, x2, TRIG, UP1, TP])))
    inv2, trig2 = (99.92, 100.25, 99.88, 99.96), (99.96, 100.5, 99.9, 100.35)
    s4 = longs(build([SWEEP, INV, x1, x2, inv2, trig2, UP1, TP]))
    check("   but a later doji / inverted hammer gives a new chance (same sweep): BUY above its high",
          len(s4) == 1 and s4[0]["trigger_px"] == 100.25, s4)
    deep = build([(100.6, 100.7, 99.0, 99.1), (99.12, 99.5, 99.05, 99.18), (99.2, 99.7, 99.15, 99.6), UP1, TP])
    s5 = longs(deep)
    check("5. the trigger close may stay below the swept low (99.6 < 99.8): still a BUY",
          len(s5) == 1 and s5[0]["signal_close"] == 99.6, s5)
    s6 = longs(build([(100.6, 100.7, 99.7, 99.75), (99.5, 99.85, 99.4, 99.55), (99.55, 100.0, 99.5, 99.95), UP1, TP]))
    check("6. the signal's low (99.4) under the sweep candle's low (99.7): stop below the signal low",
          len(s6) == 1 and 99.2 < s6[0]["stop"] < 99.4, s6)
    s7 = longs(build([SWEEP, (99.6, 99.65, 99.2, 99.3), (99.3, 99.35, 98.9, 99.0), (98.95, 99.3, 98.9, 99.0),
                      (99.0, 99.5, 98.95, 99.4), UP1, TP]))
    check("7. no cancel: closes lower only deepen the sweep; the trade comes with the stop under the lowest low (98.9)",
          len(s7) == 1 and 98.7 < s7[0]["stop"] < 98.9, s7)
    check("8. weak BOS (volume 1.0x < 1.2x): no setup", not longs(build([SWEEP, INV, TRIG, UP1, TP], bos_vol=100)))
    check("   ... the same chart with the weak-BOS rule off trades (the rule is what skipped it)",
          longs(build([SWEEP, INV, TRIG, UP1, TP], bos_vol=100), bos_body_atr=0, bos_vol_x=0))
    check("9. no minimum R:R by default; min_rr=5 (backtest setting) skips this 4R trade",
          longs(full) and not longs(full, min_rr=5))

    # 9b. intraday day rule (owner, 12 Nov 2026): yesterday's UNSWEPT BOS setups live one more day; swept-untraded and
    #     older ones end; crypto (not intraday) keeps every setup
    def next_days(rows, days):
        out, t0 = list(rows), rows[-1][0]
        for d, cands in enumerate(days, 1):
            t = datetime(t0.year, t0.month, t0.day, tzinfo=timezone.utc) + timedelta(days=d, hours=4)
            for o, h, l, c in cands:
                out.append((t, o, h, l, c, 100))
                t += timedelta(minutes=5)
        return out
    quiet = [(100.6, 100.8, 100.5, 100.7)] * 3          # no close below 99.8: the setup stays unswept
    d2 = next_days(build([]), [[SWEEP, INV, TRIG, UP1, TP]])
    check("9b. intraday: yesterday's unswept BOS setup trades today (sweep, signal, break-close on the next day)",
          [t["kind"] for t in longs(d2, intraday=True)] == ["primary"], longs(d2, intraday=True))
    d3 = next_days(build([]), [quiet, [SWEEP, INV, TRIG, UP1, TP]])
    check("    but only for one day: unswept for two days, it is gone on the third (intraday)",
          not longs(d3, intraday=True), longs(d3, intraday=True))
    check("    crypto (not intraday) keeps every setup: the same chart trades on the third day",
          [t["kind"] for t in longs(d3)] == ["primary"], longs(d3))
    swept = next_days(build([SWEEP]), [[INV, TRIG, UP1, TP]])
    check("    swept yesterday but not traded: gone today (intraday)", not longs(swept, intraday=True),
          longs(swept, intraday=True))

    # 10. the v4 trailing stop: +1R -> the entry, +2R -> +1R
    risk = p1["entry"] - p1["stop"] if p1 else 0.7
    up_1r = (100.1, 100.1 + 1.2 * risk, 100.05, 100.6)
    s10 = longs(build([SWEEP, INV, TRIG, up_1r, (100.6, 100.65, 99.2, 99.3)]))
    check("10. +1.2R then down: out at the entry (breakeven stop), not the full stop",
          s10 and s10[0]["exit"] == s10[0]["entry"] and s10[0]["exit_reason"] == "breakeven stop", s10)
    up_2r = (100.1, 100.1 + 2.3 * risk, 100.05, 101.2)
    s10b = longs(build([SWEEP, INV, TRIG, up_2r, (101.2, 101.25, 99.2, 99.3)]))
    check("    +2.3R then down: out at +1R (trailing stop)",
          s10b and abs(s10b[0]["exit"] - (s10b[0]["entry"] + risk)) < 1e-9 and s10b[0]["exit_reason"] == "trailing stop",
          s10b)
    check("    with trailing off (backtest setting) the same chart takes the full stop",
          longs(build([SWEEP, INV, TRIG, up_2r, (101.2, 101.25, 99.2, 99.3)]), trail=False)[0]["exit_reason"] == "stop")

    # 11. the secondary: only after the primary closed, a reversal candle tapping the move's OB / FVG
    pull = [(103.0, 103.05, 101.5, 101.6), (101.6, 101.65, 100.9, 101.0)]
    tap_rev = (100.6, 101.0, 100.25, 100.65)           # taps the zones, a doji: the reversal candle
    nxt = (100.66, 101.0, 100.6, 100.9)
    sec_rows = build([SWEEP, INV, TRIG, UP1, TP] + pull + [tap_rev, nxt])
    s11 = longs(sec_rows)
    sec = [t for t in s11 if t["kind"] == "secondary"]
    check("11. after the primary hit its target, a doji tapping the move's zone: secondary BUY at the next open",
          len(sec) == 1 and sec[0]["zone"] in ("OB", "FVG") and sec[0]["entry"] == nxt[0]
          and sec[0]["i"] > s11[0]["exit_i"] and sec[0]["stop"] < sec[0]["zone_bottom"], s11)
    tap_plain = (101.0, 101.05, 100.25, 100.3)
    check("    a tap by an ordinary candle (not a reversal candle): no secondary",
          not [t for t in longs(build([SWEEP, INV, TRIG, UP1, TP] + pull + [tap_plain, nxt])) if t["kind"] == "secondary"])
    open_rows = build([SWEEP, INV, TRIG, UP1, (100.4, 100.6, 100.25, 100.5), tap_rev, nxt])
    s11c = longs(open_rows)
    check("    while the primary is still open the zone tap is ignored (one trade at a time, secondary only after)",
          len(s11c) == 1 and s11c[0]["kind"] == "primary" and s11c[0]["exit_i"] is None, s11c)

    # 12. the mirror: SELL with a hammer at the top; an inverted hammer at the top is not a SELL signal
    sh = V4.sequence(V4.mirror(full), DAY)
    check("12. mirror: the same picture upside down is a primary SELL whose signal is a hammer at the top",
          len(sh) == 1 and sh[0]["side"] == "short" and sh[0]["signal_pattern"] == "hammer"
          and sh[0]["stop"] > sh[0]["entry"] > sh[0]["target"], sh)
    check("    an inverted hammer at the top (mirror of the hammer at the low) gives no SELL",
          not [t for t in V4.sequence(V4.mirror(build([SWEEP, HAMMER, TRIG, UP1, TP])), DAY) if t["side"] == "short"])

    # 13. the 1-hour trend skip
    h0 = datetime(2026, 11, 3, tzinfo=timezone.utc)
    down, legs = [], []
    for w in range(8):                       # an hourly downtrend: 3 hours down, 2 hours up, lower each time
        top = 200 - 3 * w
        legs += [top, top - 2, top - 4, top - 2, top - 1]
    for hr, base in enumerate(legs):         # 12 x 5m candles per hour
        for q in range(12):
            down.append((h0 + timedelta(minutes=60 * hr + 5 * q), base, base + 0.6, base - 0.6, base, 1))
    dirs = V4.htf_dirs(down, DAY)
    check("13. higher timeframe: an hourly downtrend reads 'down' (longs skipped there)", dirs[-1] == "down", dirs[-12:])
    check("    and the mirror of it reads 'up' for shorts' (src) terms", V4.htf_dirs(V4.mirror(down), DAY)[-1] == "up")
    check("    the owner's skip rules (12 Nov): weak BOS on, the 1-hour trend skip off by default",
          V4.DEFAULTS["htf"] is False and V4.DEFAULTS["bos_vol_x"] == 1.2 and V4.DEFAULTS["bos_body_atr"] == 0.8)
    weak = build([SWEEP, INV, TRIG], bos_vol=100)
    strong = build([SWEEP, INV, TRIG])
    per = {m: (PB.owner_setups(weak, DAY, version="v4", market=m, symbol="TST", intraday=m != "CRYPTO"),
               PB.owner_setups(strong, DAY, version="v4", market=m, symbol="TST", intraday=m != "CRYPTO"))
           for m in ("NSE", "US", "CRYPTO")}
    check("    the weak-BOS skip works the same in all three markets (NSE, US, crypto)",
          all(not w and [g["setup"] for g in st] == ["v4_primary_long"] for w, st in per.values()), per)

    # 14. the scanner: the trigger on the last candle is reported (live), named; v2 / v3 never return v4
    upto = full[:full.index(full[-3]) + 1]           # ends with the trigger candle
    got = PB.owner_setups(upto, DAY, version="v4")
    check("14. Scanner v4 names the primary on its trigger candle ('v4 primary long', the sweep in words)",
          [g["setup"] for g in got] == ["v4_primary_long"] and got[0]["name"] == "v4 primary long"
          and "below the swing low" in got[0]["liquidity"] and got[0]["scanner"] == "v4"
          and got[0]["price"] == TRIG[3], got)
    for v in ("v2", "v3"):
        check("    Scanner %s never returns v4 setups" % v,
              not [g for g in PB.owner_setups(upto, DAY, version=v) if g["setup"].startswith("v4_")])

    # 18. F&O only on Bank Nifty: the F&O agent runs v4 on Bank Nifty's own chart (owner, 12 Nov 2026)
    import auto_fno as AF
    calls = []
    saved = (AF.P.load_ledger, AF.P.load_config, AF.P.setup_decision)
    AF.index_rows = lambda idx, now: upto
    AF.record = lambda rec: None
    AF.P.load_ledger = lambda cfg=None: {"open": [], "closed": []}
    AF.P.load_config = lambda: {}
    AF.P.setup_decision = lambda m, sym, s: calls.append((m, sym, s["setup"])) or {"result": "PAPER BUY", "why": "t",
                                                                                   "time": "x", "symbol": sym}
    ms, logs = {}, []
    wed_11 = datetime(2026, 11, 11, 11, 0, tzinfo=AF.IST)
    out = AF.v4_process(AF.DEFAULTS, wed_11, ms, logs.append)
    check("18. F&O on v4: the Nifty 50 and Bank Nifty charts are scanned, their v4 setups go to the paper agents",
          calls == [("NSE", "NIFTY", "v4_primary_long"), ("NSE", "BANKNIFTY", "v4_primary_long")]
          and AF.DEFAULTS["v4_indices"] == ["NIFTY", "BANKNIFTY"], (calls, logs))
    AF.v4_process(AF.DEFAULTS, wed_11, ms, logs.append)
    check("    the same candle is not read twice", len(calls) == 2, calls)
    check("    outside 09:20-15:00 IST nothing is scanned",
          not AF.v4_process(AF.DEFAULTS, datetime(2026, 11, 11, 15, 10, tzinfo=AF.IST), {}, logs.append))
    AF.P.load_ledger, AF.P.load_config, AF.P.setup_decision = saved

    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        P.fetch_price = lambda m, t: (100.1, datetime.now(timezone.utc))
        cfg = P.load_config()
        cfg["accounts"]["CRYPTO"]["scanner_version"] = "v4"
        P.save_json(P.CONFIG, cfg)
        chart = {"version": "v4", "market": "CRYPTO", "symbol": "TST"}
        empty = {"open": [], "closed": []}
        live = PB.owner_setups(upto, DAY, ledger=empty, **chart)
        check("15. the live path (ledger given) reports the same primary", [g["setup"] for g in live] == ["v4_primary_long"], live)
        rec = P.setup_decision("CRYPTO", "TST", live[0], news=[])
        check("    a v4 account paper trades it with its liquidity target",
              rec["result"] == "PAPER BUY" and rec["steps"]["1_scanner"]["scanner"] == "v4"
              and rec["steps"]["4_exit"]["target"] == 103.0, rec)
        led = P.load_ledger(cfg)
        check("    the open v4 trade blocks the scanner and the paper entry on that chart",
              not PB.owner_setups(upto, DAY, ledger=led, **chart)
              and P.setup_decision("CRYPTO", "TST", live[0])["result"] == "skipped")
        # the primary closes at its target; the secondary comes on the zone tap
        exit_at = sec_rows[s11[0]["exit_i"]][0] + timedelta(minutes=1)
        P.close_position(led, cfg, led["open"][0], 103, "target", exit_at)
        P.save_json(P.LEDGER, led)
        sec_upto = sec_rows[:-1]                     # ends with the reversal candle in the zone
        live2 = PB.owner_setups(sec_upto, DAY, ledger=led, **chart)
        check("16. after the real primary close, the reversal candle in the zone is a live secondary",
              [g["setup"] for g in live2] == ["v4_secondary_long"], live2)
        if live2:
            P.fetch_price = lambda m, t: (100.66, datetime.now(timezone.utc))
            second = P.setup_decision("CRYPTO", "TST", live2[0])
            check("    the matching secondary fills (the tap is the signal candle)", second["result"] == "PAPER BUY", second)
            check("    a secondary on another chart cannot use this primary",
                  P.setup_decision("CRYPTO", "OTHER", live2[0])["result"] == "skipped")
        v2rec = P.setup_decision("CRYPTO", "ABC", {"setup": "abcd_long", "name": "A-B-C-D long", "side": "long",
                                                   "price": 100.3, "stop": 99.0, "target_2r": 102.9}, news=[])
        v3rec = P.setup_decision("CRYPTO", "XYZ", {"setup": "v3_sweep_long", "name": "v3 sweep long", "side": "long",
                                                   "price": 100.3, "stop": 99.0, "target": 103.0}, news=[])
        check("17. a v4 account skips v2 and v3 setups",
              v2rec["result"] == "skipped" and v3rec["result"] == "skipped" and "Scanner v4" in v3rec["why"], (v2rec, v3rec))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
