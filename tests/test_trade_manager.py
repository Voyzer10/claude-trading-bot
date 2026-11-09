#!/usr/bin/env python3
"""The Trade Manager (paper.py, 7 Nov 2026): the agent thinks about every open trade and reacts. Offline: prices and
1-minute candles are faked.

    python tests/test_trade_manager.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def minutes(now, start_ago, closes, spread=0.05):
    """1-minute bars from `start_ago` minutes ago: each close given, open = previous close."""
    out, prev = [], closes[0]
    for k, c in enumerate(closes):
        t = now - timedelta(minutes=start_ago - k)
        out.append((t, prev, max(prev, c) + spread, min(prev, c) - spread, c))
        prev = c
    return out


def run(P, side, target, bars_fn, live, entry_ago=40, tm=True, extra=None, stop=99.0, pos_extra=None):
    cfg = P.load_config()
    acc = cfg["accounts"]["CRYPTO"]
    acc.update({"fee_pct": 0.0, "trade_manager": tm, "tm_candle_min": 5, "tm_stale_min": 60})
    acc.update(extra or {})
    P.save_json(P.CONFIG, cfg)
    led = P.load_ledger(cfg)
    led["open"], led["closed"] = [], []
    P.fetch_price = lambda m, t: (100.0, datetime.now(timezone.utc))
    P.cmd_buy(type("A", (), {"symbol": "CRYPTO:TST", "stop": str(stop), "target": str(target), "qty": None,
                             "price": None, "note": "t", "force": True, "side": side})(), cfg, led)
    now = datetime.now(timezone.utc)
    pos = led["open"][0]
    pos.update(pos_extra or {})
    pos["entry_time"] = (now - timedelta(minutes=entry_ago)).isoformat()
    pos.pop("last_seen", None)
    pos.pop("covered_until", None)
    P.fetch_minutes = lambda m, t, days=1: bars_fn(now)
    P.fetch_price = lambda m, t: (live, now)
    P.check_once(cfg, led)
    return (led["open"][0] if led["open"] else None), led["closed"]


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        # the owner's US trade (6 Nov): 2 points from the target, it reversed and hit the stop
        up_then_down = [100.2, 100.6, 101.0, 101.4, 101.7, 101.9, 101.6, 101.0, 100.4, 99.8, 99.2, 98.8]
        pos, closed = run(P, "long", 102.0, lambda n: minutes(n, 30, up_then_down), 98.8, tm=False)
        check("1. without the Trade Manager: up to 101.9 (target 102), then the full stop: -1R",
              closed and closed[0]["exit"] == 99.0 and closed[0]["reason"] == "stop", closed)
        pos, closed = run(P, "long", 102.0, lambda n: minutes(n, 30, up_then_down), 98.8)
        check("   with it: 80% of the way to the target locks half the move -> out at 101.0 (+1R) instead",
              closed and closed[0]["exit"] == 101.0 and closed[0]["reason"] == "profit lock stop", closed)
        if closed:
            check("   the closed trade records how far it went: mfe ~ +1.95R, mae", closed[0].get("mfe_r", 0) >= 1.9
                  and "mae_r" in closed[0], closed[0])
            texts = [x["text"] for x in closed[0].get("tm_log") or []]
            check("   the trade keeps what the manager did: breakeven, profit lock, then the lock stop hit",
                  any(t.startswith("breakeven") for t in texts) and any(t.startswith("profit lock") for t in texts)
                  and any("hit at" in t for t in texts), texts)
            check("   ... and the same actions go to the runner log (TRADE MANAGER: CRYPTO:TST ...)",
                  any(e.startswith("CRYPTO:TST profit lock") for e in P.TM_EVENTS), P.TM_EVENTS)

        pos, closed = run(P, "long", 103.0, lambda n: minutes(n, 30, [100.3, 100.7, 101.1, 101.3, 100.8, 100.2, 99.7]),
                          99.7)
        check("2. +1.3R then back down: breakeven -> out at the entry 100, not the stop",
              closed and closed[0]["exit"] == 100.0 and closed[0]["reason"] == "breakeven stop", closed)

        # reversal: +2R towards a far 4R target, then a bearish engulfing 5-minute candle near the high
        now0 = datetime.now(timezone.utc)
        base = int(now0.timestamp() // 300) * 300

        def rev_bars(n):
            t0 = datetime.fromtimestamp(base, timezone.utc) - timedelta(minutes=30)
            seq = [100.2, 100.6, 101.0, 101.3, 101.6] + [101.6, 101.7, 101.8, 101.9, 102.0] + \
                  [102.05, 101.9, 101.7, 101.5, 101.4]
            out, prev = [], 100.0
            for k, c in enumerate(seq):
                out.append((t0 + timedelta(minutes=15 + k), prev, max(prev, c) + 0.05, min(prev, c) - 0.05, c))
                prev = c
            return out
        pos, closed = run(P, "long", 104.0, rev_bars, 101.45)
        check("3. +2R, then a bearish engulfing candle at the top -> the Trade Manager takes the profit (~+1.45R)",
              closed and closed[0]["reason"].startswith("trade manager: reversal") and closed[0]["exit"] == 101.45,
              closed)

        pos, closed = run(P, "long", 102.0, lambda n: minutes(n, 30, [100.1, 100.2, 100.0, 99.9, 100.1]), 100.1,
                          entry_ago=75)
        check("4. 75 min and it went nowhere (best +0.25R, now +0.1R) -> closed: no follow-through",
              closed and "no follow-through" in closed[0]["reason"], closed)
        pos, closed = run(P, "long", 102.0, lambda n: minutes(n, 30, [100.1, 100.2, 100.0, 99.9, 100.1]), 100.1,
                          entry_ago=40)
        check("   the same at 40 min: still open (patience before 60 min)", pos is not None and not closed, closed)

        down_then_up = [99.8, 99.4, 99.0, 98.6, 98.3, 98.1, 98.4, 99.0, 99.6, 100.2, 100.8, 101.2]
        pos, closed = run(P, "short", 98.0, lambda n: minutes(n, 30, down_then_up), 101.2, stop=101.0)
        check("5. shorts the same way: 95% to the target, then a rally -> locked at 99.0 (+1R)",
              closed and closed[0]["exit"] == 99.0 and closed[0]["reason"] == "profit lock stop", closed)

        cfg = P.load_config()
        led = P.load_ledger(cfg)
        led["open"], led["closed"] = [], []
        P.fetch_price = lambda m, t: (100.0, datetime.now(timezone.utc))
        P.cmd_buy(type("A", (), {"symbol": "CRYPTO:TRL", "stop": "99", "target": "102", "qty": None, "price": None,
                                 "note": "t", "force": True, "side": "long"})(), cfg, led)
        led["open"][0].update({"trail_k": 2.0, "trail_atr": 0.5, "trail_arm_r": 1.0,
                               "entry_time": (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()})
        P.fetch_minutes = lambda m, t, days=1: []
        P.fetch_price = lambda m, t: (100.05, datetime.now(timezone.utc))
        P.check_once(cfg, led)
        check("6. the backtested crypto trailing exit is left alone (no stale exit at 90 min)", led["open"], led["closed"])

        # Scanner v4 trades: only the PDF's exits (owner, 10 Nov 2026): stop / target, no Trade Manager
        v4 = {"scanner": "v4", "setup": "v4_primary_long"}
        pos, closed = run(P, "long", 102.0, lambda n: minutes(n, 30, up_then_down), 98.8, pos_extra=v4)
        check("10. a v4 trade ignores the Trade Manager: 95% to the target, then the full stop (-1R), as the PDF says",
              closed and closed[0]["exit"] == 99.0 and closed[0]["reason"] == "stop" and not closed[0].get("tm_log"),
              closed)
        pos, closed = run(P, "long", 103.0, lambda n: minutes(n, 30, [100.3, 100.7, 101.1, 101.3, 101.2]), 101.2,
                          pos_extra=v4)
        check("   no breakeven move either: +1.3R and the stop stays at 99", pos and pos["stop"] == 99.0
              and not pos.get("breakeven"), pos)
        pos, closed = run(P, "long", 102.0, lambda n: minutes(n, 30, [100.1, 100.2, 100.0, 99.9, 100.1]), 100.1,
                          entry_ago=75, pos_extra=v4)
        check("   no 'went nowhere' exit at 75 min: still open", pos is not None and not closed, closed)
        pos, closed = run(P, "long", 102.0, lambda n: minutes(n, 30, up_then_down), 98.8, pos_extra=v4,
                          extra={"v4_pdf_only": False})
        check("   with v4_pdf_only off, the Trade Manager manages it again (locked at +1R)",
              closed and closed[0]["reason"] == "profit lock stop", closed)
        import auto_crypto as AC
        cfg = P.load_config()
        cfg["accounts"]["CRYPTO"]["v4_pdf_only"] = True
        P.save_json(P.CONFIG, cfg)
        led = P.load_ledger(cfg)
        led["open"], led["closed"] = [], []
        P.fetch_price = lambda m, t: (100.0, datetime.now(timezone.utc))
        for sym, extra_pos in (("V4X", v4), ("OLD", {})):
            P.cmd_buy(type("A", (), {"symbol": "CRYPTO:" + sym, "stop": "99", "target": "102", "qty": None,
                                     "price": None, "note": "t", "force": True, "side": "long"})(), cfg, led)
            led["open"][-1].update(extra_pos, entry_time=(datetime.now(timezone.utc) - timedelta(hours=20)).isoformat())
        P.save_json(P.LEDGER, led)
        AC.time_stops({"max_hold_hours": 12}, lambda x: None)
        left = [p["key"] for p in P.load_ledger(P.load_config())["open"]]
        check("11. the crypto 12h time stop closes an old-rules trade but not a v4 trade (not in the PDF)",
              left == ["CRYPTO:V4X"], left)

        import dashboard_push as D
        check("7. dashboard: 'TRADE MANAGER: ...' log lines are their own kind (the Logs filter 'trade manager')",
              D.kind_of("TRADE MANAGER: CRYPTO:TST breakeven: ...") == "tm")
        from api import _ops as O
        now = datetime.now(timezone.utc)
        led = {"open": [{"symbol": "AAA", "market": "US", "stop": 10, "breakeven": True, "mfe_r": 1.2,
                         "tm_log": [{"t": now.isoformat(), "text": "breakeven: price reached +1R"}]},
                        {"symbol": "BBB", "market": "US", "stop": 20, "locked": True, "mfe_r": 1.8}],
               "closed": [{"symbol": "CCC", "tm_log": [{"t": now.isoformat(), "text": "exit at 5 (+1.2R): reversal"},
                                                        {"t": "2020-01-01T00:00:00+00:00", "text": "profit lock: old"}]}]}
        card = O._tm_status(led, led["open"], now)
        check("8. the Trade Manager agent card: watching 2, AAA breakeven, BBB profit locked, today's counts only",
              card["status"] == "active" and "AAA breakeven" in card["now"] and "BBB profit locked" in card["now"]
              and card["tm"]["today"] == {"breakeven": 1, "profit lock": 0, "exit": 1}
              and card["tm"]["last"][0]["symbol"] in ("AAA", "CCC"), card)
        check("   and standby with no open trade", O._tm_status({"open": [], "closed": []}, [], now)["status"] == "standby")
        check("   the agents list calls agent 9 'Trade Manager'", any(a[2] == "Trade Manager" for a in O.AGENTS))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
