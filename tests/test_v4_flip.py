#!/usr/bin/env python3
"""The v4 flip rule and the latest-BOS rule (owner, 14 Nov 2026), both ways. Offline.

  1. Engine: every flip closes a trade from an earlier day's BOS setup at the candle's close and opens the opposite
     side from a setup whose BOS formed that day; switched off, no flips.
  2. live_candidate: with a v4 trade open every trigger comes back (paper decides), except the one it came from.
  3. paper.setup_decision: a flip closes the open position at the current price, then takes the new trade; a
     setup without the flip mark still waits.
  4. Latest BOS: with a trade open, a setup of a newer BOS is taken as well (at most 2 open on a chart); live it
     becomes a second position with its own key (NSE:TCS#2).

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
    V4.DEFAULTS.update(structure_bos=False)   # mechanics on hand-built / random charts (the 20 Nov BOS is in test_v4_sweep_target)

    # ------------------------------------------------------------------ 1. engine
    flips, checked = 0, True
    for seed in range(12):
        rows = walk(30, seed)
        day = [day_of(r[0]) for r in rows]
        on = V4.sequence(rows, day_of, intraday=True)
        off = V4.sequence(rows, day_of, intraday=True, flip_same_day=False, latest_bos=False)
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

    # latest BOS: never more than max_open at once; each extra trade's BOS is newer than every trade open then
    stacked, ok_lb, over = 0, True, 0
    for seed in range(12):
        rows = walk(30, seed)
        seq = V4.sequence(rows, day_of, intraday=True)
        span = [(t["i"], t["exit_i"] if t.get("exit_i") is not None else 10 ** 9, t) for t in seq if not t.get("pending")]
        for i, x, t in span:
            live_then = [u for j, y, u in span if j < i and y > i]
            if len(live_then) + 1 > V4.DEFAULTS["max_open"] and not str(t.get("flipped", "")):
                over += 1
            if t.get("latest_bos"):
                stacked += 1
                if not live_then or any(t["bos"] <= u.get("bos", u["i"]) for u in live_then):
                    ok_lb = False
                    print("   bad latest", t["i"], t["bos"], [(u["i"], u.get("bos")) for u in live_then])
        if any(t.get("latest_bos") for t in V4.sequence(rows, day_of, intraday=True, latest_bos=False)):
            ok_lb = False
    check("   latest BOS: extra trades happen on the test charts", stacked > 0, stacked)
    check("   each is from a BOS newer than every trade open then; none with the switch off", ok_lb)
    check("   never more than %d trades open on a chart" % V4.DEFAULTS["max_open"], over == 0, over)

    # ------------------------------------------------------------------ 2. live_candidate
    # (17 Nov 2026: with trades open every trigger comes back; paper.setup_decision takes the flip / latest-BOS ones
    # and records the rest as skipped, so none is dropped unseen. Only the trigger an open position came from is not.)
    real_seq = V4.sequence
    t99 = datetime(2026, 11, 16, 16, 30, tzinfo=timezone.utc)
    rows100 = [(t99 - timedelta(minutes=5 * (99 - k)), 1, 1, 1, 1, 0) for k in range(100)]
    flip_short = {"i": 99, "kind": "primary", "side": "short", "pending": True, "flip": True}
    plain_short = {"i": 99, "kind": "primary", "side": "short", "pending": True}
    led = {"open": [{"key": "NSE:TCS", "market": "NSE", "symbol": "TCS", "scanner": "v4", "v4_chart": "NSE:TCS",
                     "setup": "v4_primary_long", "side": "long",
                     "v4_signal_at": (t99 - timedelta(hours=1)).isoformat()}], "closed": []}
    V4.sequence = lambda *a, **k: [dict(flip_short), dict(plain_short)]
    got = V4.live_candidate(rows100, day_of, led, "NSE:TCS", intraday=True)
    check("2. a trade open: every trigger comes back (the flip one and a plain one, which paper records as skipped)",
          len(got) == 2 and got[0].get("flip"), got)
    led["open"][0]["v4_signal_at"] = t99.astimezone(timezone(timedelta(hours=-5))).isoformat()   # ET, as US rows
    check("   the trigger the open position came from is not offered again",
          V4.live_candidate(rows100, day_of, led, "NSE:TCS") == [])
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
        import _old_budget
        _old_budget.apply(P)   # written against the pre-17-Nov budgets
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
        check("   a setup without the flip mark is skipped and says why (the engine had closed the open trade)",
              rec2["result"] == "skipped" and "NSE:TCS is still open on this chart" in rec2["why"]
              and "engine had already closed" in rec2["why"], (rec2["result"], rec2.get("why")))
        s3 = dict(s, setup="v4_primary_short", side="short")
        rec3 = P.setup_decision("NSE", "TCS", s3)
        check("   a flip mark on the same side as the open trade does nothing", rec3["result"] == "skipped", rec3)

        # 4. latest BOS: the short is open; a newer BOS's long setup triggers -> a second position NSE:TCS#2
        s4 = dict(s, setup="v4_primary_long", side="long", price=995.0, stop=990.0, target=1010.0,
                  details={"latest_bos": True}, v4_signal_at=datetime.now(timezone.utc).isoformat())
        rec4 = P.setup_decision("NSE", "TCS", s4)
        led = P.load_ledger(cfg)
        keys = sorted(p["key"] for p in led["open"])
        check("4. latest BOS: a second position with its own key, the first stays open",
              rec4["result"] == "PAPER BUY" and keys == ["NSE:TCS", "NSE:TCS#2"]
              and "0_latest_bos" in rec4["steps"], (rec4["result"], rec4.get("why"), keys))
        two = next(p for p in led["open"] if p["key"] == "NSE:TCS#2")
        check("   it is still a TCS position on the TCS chart", two["symbol"] == "TCS" and two["v4_chart"] == "NSE:TCS"
              and two["side"] == "long", two)
        rec5 = P.setup_decision("NSE", "TCS", dict(s4, v4_signal_at=datetime.now(timezone.utc).isoformat()))
        check("   a third one waits (max 2 open on a chart)", rec5["result"] == "skipped", (rec5["result"], rec5.get("why")))
        P.check_once(cfg, P.load_ledger(cfg)) if hasattr(P, "check_once") else None
        led = P.load_ledger(cfg)
        check("   the runner's check handles both positions (prices by symbol, not key)",
              len([p for p in led["open"] if p["symbol"] == "TCS"]) == 2, [p["key"] for p in led["open"]])

        # 5. a v4 option also exits on its underlying's v4 stop / target (owner, 17 Nov 2026), premium ones stay
        E = datetime(2026, 11, 16, 16, 17, tzinfo=timezone.utc)
        mins = [(E + timedelta(minutes=k), 667.0, 667.0 + 0.5 * k, 666.8, 667.2) for k in range(6)]   # QQQ rises
        put = {"key": "USOPT:QQQ261118P00666000", "market": "USOPT", "symbol": "QQQ261118P00666000", "entry_time": E.isoformat(),
               "underlying_plan": {"market": "US", "symbol": "QQQ", "side": "short", "stop": 669.43, "target": 663.07}}
        P.underlying_data = lambda m, s, since, now: (667.5, [b for b in mins if b[0] + timedelta(seconds=60) > since])
        why = P.underlying_exit(put, E + timedelta(minutes=7))
        check("5. QQQ's 1-minute high reached the v4 stop 669.43 between checks -> the put exits ('underlying stop')",
              why is not None and why.startswith("underlying stop: QQQ reached 669.5") and "669.43" in why, why)
        put["underlying_plan"]["stop"] = 671.0
        check("   below the stop and above the target: no exit, the check moves on",
              P.underlying_exit(put, E + timedelta(minutes=7)) is None and put["underlying_plan"]["checked_until"])
        P.underlying_data = lambda m, s, since, now: (662.9, [])
        why = P.underlying_exit(put, E + timedelta(minutes=9))
        check("   the live price at the v4 target 663.07 -> 'underlying target'", why is not None
              and why.startswith("underlying target: QQQ reached 662.9"), why)
        long_call = {"key": "NFO:NIFTY25NOV24000CE", "entry_time": E.isoformat(),
                     "underlying_plan": {"market": "NSE", "symbol": "NIFTY", "side": "long", "stop": 23950.0, "target": 24100.0}}
        P.underlying_data = lambda m, s, since, now: (23990.0, [(E, 24000.0, 24010.0, 23940.0, 23990.0)])
        check("   a Nifty call: the index's low under the stop -> exit (long side mirrored)",
              (P.underlying_exit(long_call, E + timedelta(minutes=2)) or "").startswith("underlying stop: NIFTY reached 23940"))
        def broken(m, s, since, now):
            raise RuntimeError("feed down")
        P.underlying_data = broken
        check("   no underlying data: never closes the trade (retried next check)", P.underlying_exit(long_call, E) is None)

        # the plan is saved on the option bought from a v4 setup
        P.underlying_data = lambda m, s, since, now: (667.5, [])
        P.fetch_price = lambda m, t: (7.2, datetime.now(timezone.utc))
        cfg2 = P.load_config()
        led2 = P.load_ledger(cfg2)
        led2["open"] = [p for p in led2["open"] if not p["key"].startswith("USOPT:")]
        op = {"kind": "PE", "premium": 7.2, "stop": 5.77, "target": 8.86, "name": "QQQ261118P00666000", "lot": 100,
              "iv": 0.2, "delta": -0.46, "expiry": "2026-11-18"}
        st2 = {}
        rec6 = {"steps": st2}
        def done2(result, why):
            rec6["result"], rec6["why"] = result, why
            return rec6
        P._option_setup(st2, done2, cfg2, cfg2["accounts"]["USFNO"], "QQQ",
                        {"setup": "v4_primary_short", "side": "short", "price": 666.32, "stop": 669.43, "target": 663.07,
                         "name": "v4 primary short"}, op, "v4", led2,
                        {"v4_chart": "US:QQQ", "v4_signal_at": E.isoformat()}, mk="USOPT")
        bought = next((p for p in P.load_ledger(cfg2)["open"] if p["key"] == "USOPT:QQQ261118P00666000"), {})
        check("   a v4 option buy saves QQQ's v4 stop / target on the position; the premium stop / target stay",
              bought.get("underlying_plan", {}).get("stop") == 669.43 and bought["underlying_plan"]["target"] == 663.07
              and bought["underlying_plan"]["side"] == "short" and bought.get("stop") == 5.77
              and "QQQ itself" in str(st2.get("9_alerts")), (rec6.get("result"), rec6.get("why"), bought.get("underlying_plan")))
    finally:
        os.chdir(old)

    print()
    if FAILS:
        print("%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("all checks passed")
