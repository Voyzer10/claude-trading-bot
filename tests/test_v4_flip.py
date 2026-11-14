#!/usr/bin/env python3
"""The v4 flip rule (owner, 14 Nov 2026), both ways. Offline.

  1. Engine: every flip closes a trade from an earlier day's BOS setup at the candle's close and opens the opposite
     side from a setup whose BOS formed that day; switched off, no flips.
  2. live_candidate: with a v4 trade open on the chart only an opposite-side flip trigger comes back.
  3. paper.setup_decision: a flip closes the open position at the current price, then takes the new trade; a
     setup without the flip mark still waits.

    python tests/test_v4_flip.py
"""
import json
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def walk(days, seed):
    """Choppy 5-minute sessions (75 candles a day) with a trend that turns every few days."""
    rnd = random.Random(seed)
    out, c = [], 1000.0
    t0 = datetime(2026, 8, 3, 3, 45, tzinfo=timezone.utc)
    for d in range(days):
        drift = 0.0006 * (1 if (d // 3) % 2 == 0 else -1)
        for j in range(75):
            o = c
            c = o * (1 + drift + rnd.gauss(0, 0.003))
            h = max(o, c) * (1 + abs(rnd.gauss(0, 0.0015)))
            l = min(o, c) * (1 - abs(rnd.gauss(0, 0.0015)))
            if rnd.random() < 0.08:                      # some doji-like candles
                c = o * (1 + rnd.gauss(0, 0.0002))
            out.append((t0 + timedelta(days=d, minutes=5 * j), o, h, l, c, 1000))
    return out


def day_of(t):
    return t.date()


if __name__ == "__main__":
    import scanner_v4 as V4

    # ------------------------------------------------------------------ 1. engine
    flips, checked = 0, True
    for seed in range(12):
        rows = walk(30, seed)
        day = [day_of(r[0]) for r in rows]
        on = V4.sequence(rows, day_of, intraday=True)
        off = V4.sequence(rows, day_of, intraday=True, flip_same_day=False)
        if any(str(t.get("exit_reason", "")).startswith("flip") for t in off):
            checked = False
        done = [t for t in on if t.get("exit_i") is not None]
        for n, t in enumerate(done):
            if not str(t.get("exit_reason", "")).startswith("flip"):
                continue
            flips += 1
            nxt = [u for u in done[n + 1:] + [u for u in on if u.get("exit_reason") == "open"] if u.get("flipped")]
            new = next((u for u in nxt if u["i"] == t["exit_i"]), None)
            ok = (new is not None and new["side"] != t["side"] and t["kind"] == "primary"
                  and t["exit"] == rows[t["exit_i"]][4] and day[t["bos"]] < day[t["exit_i"]]
                  and day[new["bos"]] == day[new["i"]] and new["entry"] == rows[new["i"] + 1][1])
            if not ok:
                checked = False
                print("   bad flip", t, new)
    check("1. flips happen on choppy test charts", flips > 0, flips)
    check("   each flip: old primary (earlier day's BOS) out at the close, opposite side in at the next open "
          "(its BOS today); none with the switch off", checked)
    check("   the rule is on by default", V4.DEFAULTS["flip_same_day"] is True)

    # ------------------------------------------------------------------ 2. live_candidate
    real_seq = V4.sequence
    flip_short = {"i": 99, "kind": "primary", "side": "short", "pending": True, "flip": True}
    plain_short = {"i": 99, "kind": "primary", "side": "short", "pending": True}
    rows100 = [(None,)] * 100
    led = {"open": [{"key": "NSE:TCS", "market": "NSE", "symbol": "TCS", "scanner": "v4", "v4_chart": "NSE:TCS",
                     "setup": "v4_primary_long", "side": "long"}], "closed": []}
    V4.sequence = lambda *a, **k: [dict(flip_short), dict(plain_short)]
    got = V4.live_candidate(rows100, day_of, led, "NSE:TCS", intraday=True)
    check("2. open long + flip short trigger -> only the flip comes back", len(got) == 1 and got[0].get("flip"), got)
    led["open"][0]["setup"] = "v4_primary_short"
    check("   open short + flip short -> nothing (same side)", V4.live_candidate(rows100, day_of, led, "NSE:TCS") == [])
    opt = {"key": "NFO:X-PE", "market": "NFO", "symbol": "X-PE", "scanner": "v4", "v4_chart": "NSE:TCS",
           "setup": "v4_primary_long", "side": "long"}
    check("   an option bought on a long setup counts as long", V4.direction(opt) == "long"
          and V4.direction(dict(opt, setup="v4_primary_short")) == "short")
    led["open"] = []
    check("   no open trade -> every pending trigger", len(V4.live_candidate(rows100, day_of, led, "NSE:TCS")) == 2)
    V4.sequence = real_seq

    # ------------------------------------------------------------------ 3. paper.setup_decision
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        cfg = P.load_config()
        cfg["accounts"]["INDIA"]["scanner_version"] = "v4"
        P.save_json(P.CONFIG, cfg)
        now = datetime.now(timezone.utc)
        pos = {"key": "NSE:TCS", "market": "NSE", "symbol": "TCS", "qty": 10, "entry": 1000.0, "stop": 990.0,
               "risk_stop": 990.0, "target": 1020.0, "entry_fee": 2.0, "kind": "equity", "side": "long",
               "entry_time": (now - timedelta(hours=1)).isoformat(), "entry_date": now.date().isoformat(),
               "scanner": "v4", "setup": "v4_primary_long", "v4_chart": "NSE:TCS",
               "v4_signal_at": (now - timedelta(hours=1)).isoformat(), "margin": 2000.0, "leverage": 5}
        led = P.load_ledger(cfg)
        led["open"], led["closed"] = [dict(pos)], []
        P.book_of(led, "NSE")["cash"] = 48000.0
        P.save_json(P.LEDGER, led)
        P.fetch_price = lambda m, t: (995.0, datetime.now(timezone.utc))
        P.session = lambda m, n: "open"
        P.past_flat_by = lambda m, acc, n: False
        s = {"setup": "v4_primary_short", "side": "short", "scanner": "v4", "name": "v4 primary short",
             "price": 995.0, "stop": 1001.0, "target": 980.0, "v4_signal_at": now.isoformat(),
             "details": {"flip": True, "flip_from_side": "long"}}
        rec = P.setup_decision("NSE", "TCS", dict(s))
        led = P.load_ledger(cfg)
        closed = led["closed"][-1] if led["closed"] else {}
        check("3. flip: the open long is closed at the current price with the flip reason",
              closed.get("key") == "NSE:TCS" and closed.get("exit") == 995.0 and "flip" in closed.get("reason", ""),
              closed)
        new = next((p for p in led["open"] if p["key"] == "NSE:TCS"), {})
        check("   then the short is taken", rec["result"] == "PAPER SHORT" and new.get("side") == "short"
              and new.get("setup") == "v4_primary_short", (rec["result"], rec.get("why"), new))
        check("   the decision records the flip", rec["steps"].get("0_flip", {}).get("closed") == "NSE:TCS"
              and rec["why"].startswith("flip, closed NSE:TCS first"), (rec["steps"].get("0_flip"), rec.get("why")))
        s2 = dict(s, setup="v4_primary_long", side="long", stop=989.0, target=1010.0,
                  details={})                            # no flip mark: waits for the open short
        rec2 = P.setup_decision("NSE", "TCS", s2)
        check("   a setup without the flip mark still waits for the open trade", rec2["result"] == "skipped"
              and "wait for the open trade" in rec2["why"], (rec2["result"], rec2.get("why")))
        s3 = dict(s, setup="v4_primary_short", side="short")
        rec3 = P.setup_decision("NSE", "TCS", s3)
        check("   a flip mark on the same side as the open trade does nothing", rec3["result"] == "skipped", rec3)
    finally:
        os.chdir(old)

    print()
    if FAILS:
        print("%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("all checks passed")
