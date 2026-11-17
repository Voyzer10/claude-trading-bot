#!/usr/bin/env python3
"""Intraday margin and the v4 time machine (owner, 14 Nov 2026). Offline.

  1. INDIA stocks buy on 5x intraday margin, US stocks on 4x: the position ties up qty x entry / leverage, the max
     loss per trade still sets the size, the close gives the margin back plus the P&L. Crypto and leverage 1 do
     not use margin. The setting is editable (RISK_FIELDS) and capped at 5x.
  2. timemachine_v4: replay odds add up, are repeatable with a seed, lean the right way on a trending chart, count a
     candle touching both levels as the stop; history runs the v4 rules; run() is info only.
  3. paper.v4_timemachine: only for v4 setups, uses the scanner's candles, never raises.
  4. api/_timemachine: the four step-5 formats normalise to one shape; runs() reads decisions.jsonl newest first.

    python tests/test_margin_tm.py
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


def buy(P, cfg, led, symbol, price, stop, target, side="long"):
    a = type("A", (), {"symbol": symbol, "stop": str(stop), "target": str(target), "qty": None, "price": price,
                       "note": "test", "force": True, "side": side})()
    return P.cmd_buy(a, cfg, led)


def rows_walk(n, drift=0.0, vol=0.002, seed=1, start=None):
    """n 5-minute candles, 75 a day (NSE-like), a random walk with a drift per candle."""
    rnd = random.Random(seed)
    t = start or datetime(2026, 9, 1, 3, 45, tzinfo=timezone.utc)
    out, c, k = [], 1000.0, 0
    while len(out) < n:
        for j in range(75):
            if len(out) >= n:
                break
            o = c
            c = o * (1 + drift + rnd.gauss(0, vol))
            h, l = max(o, c) * (1 + abs(rnd.gauss(0, vol / 2))), min(o, c) * (1 - abs(rnd.gauss(0, vol / 2)))
            out.append((t + timedelta(days=k, minutes=5 * j), o, h, l, c, 1000))
        k += 1
    return out


def day_of(t):
    return t.date()


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        cfg = P.load_config()
        led = P.load_ledger(cfg)
        led["open"], led["closed"] = [], []

        # ---------------------------------------------------------------- 1. intraday margin
        india = cfg["accounts"]["INDIA"]
        check("1. defaults: INDIA 5x, US 4x", india.get("intraday_leverage") == 5
              and cfg["accounts"]["US"].get("intraday_leverage") == 4,
              (india.get("intraday_leverage"), cfg["accounts"]["US"].get("intraday_leverage")))
        cash0 = P.book_of(led, "NSE")["cash"]
        pos = buy(P, cfg, led, "NSE:TCS", 2000.0, 1990.0, 2030.0)
        q = pos["qty"]
        risk_cap = india["max_loss_per_trade"] / 10.0
        check("   NSE buy on 5x: margin = qty x entry / 5, leverage recorded",
              pos.get("leverage") == 5 and abs(pos["margin"] - round(q * 2000 / 5, 2)) < 0.01, pos)
        check("   cash goes down by the margin + the fee, not by the full value",
              abs((cash0 - P.book_of(led, "NSE")["cash"]) - (pos["margin"] + pos["entry_fee"])) < 0.01,
              (cash0, P.book_of(led, "NSE")["cash"], pos["margin"], pos["entry_fee"]))
        check("   the max loss per trade still caps the size (risk unchanged)", q <= risk_cap + 1e-9, (q, risk_cap))
        check("   the position is worth more than the cash it ties up (that's the leverage)",
              q * 2000 > pos["margin"] * 4.99, (q * 2000, pos["margin"]))
        before = P.book_of(led, "NSE")["cash"]
        now = datetime.now(timezone.utc)
        rec = P.close_position(led, cfg, pos, 2030.0, "target", now)
        fee_out = P.charges(cfg, "NSE", "TCS", "sell", q * 2030.0)
        check("   close: cash back = margin + gross P&L - fee",
              abs(P.book_of(led, "NSE")["cash"] - before - (pos["margin"] + q * 30.0 - fee_out)) < 0.01,
              (P.book_of(led, "NSE")["cash"] - before, pos["margin"], q * 30.0, fee_out))
        check("   held_value of a margin position = its margin", abs(P.held_value(pos) - pos["margin"]) < 1e-9)
        if pos in led["open"]:
            led["open"].remove(pos)

        # a stock that needed more cash than the account had at 1x now fits
        small = dict(cfg["accounts"]["INDIA"])
        P.book_of(led, "NSE")["cash"] = 20000.0
        p2 = buy(P, cfg, led, "NSE:INFY", 5000.0, 4995.0, 5015.0)
        check("   Rs 20,000 free buys Rs 5,000 stock in more than 4 shares on margin (was max 3 at 1x)",
              p2["qty"] > 4 and p2["margin"] <= 20000, (p2["qty"], p2["margin"]))
        led["open"].remove(p2)

        # leverage 1: back to the full value
        cfg["accounts"]["INDIA"]["intraday_leverage"] = 1
        P.book_of(led, "NSE")["cash"] = 50000.0
        p3 = buy(P, cfg, led, "NSE:HDFCBANK", 1000.0, 995.0, 1010.0)
        check("   intraday_leverage 1: no margin, cash pays the full value", p3.get("margin") is None
              and "leverage" not in p3, p3)
        led["open"].remove(p3)
        cfg["accounts"]["INDIA"]["intraday_leverage"] = 50          # capped at 5x
        p4 = buy(P, cfg, led, "NSE:SBIN", 800.0, 796.0, 808.0)
        check("   a leverage over 5 is capped at 5x (SEBI)", p4.get("leverage") == 5, p4.get("leverage"))
        led["open"].remove(p4)
        cfg["accounts"]["INDIA"]["intraday_leverage"] = 5

        p5 = buy(P, cfg, led, "US:AAPL", 200.0, 199.0, 202.0)
        check("   US buy on 4x: margin = qty x entry / 4", p5.get("leverage") == 4
              and abs(p5["margin"] - round(p5["qty"] * 200.0 / 4, 2)) < 0.01, p5)
        led["open"].remove(p5)
        p6 = buy(P, cfg, led, "CRYPTO:BTC", 100.0, 99.0, 102.0)
        check("   crypto on 5x margin (owner, 17 Nov): margin = qty x entry / 5",
              p6.get("leverage") == 5 and abs(p6["margin"] - round(p6["qty"] * 100.0 / 5, 2)) < 0.01, p6)
        led["open"].remove(p6)

        sys.path.insert(0, os.path.join(ROOT, "api"))
        from api import _ops as OPS
        f = OPS.RISK_FIELDS.get("intraday_leverage") or {}
        check("   Settings: intraday_leverage editable for INDIA, US and crypto, 1..5",
              f.get("min") == 1 and f.get("max") == 5 and set(f.get("accounts", [])) == {"INDIA", "US", "CRYPTO"}, f)

        # ---------------------------------------------------------------- 2. timemachine_v4
        import timemachine_v4 as TM
        flat = rows_walk(1500, 0.0, seed=3)
        a = TM.replay(flat, "long", 1000.0, 990.0, 1020.0, 40, paths=500, seed=7)
        b = TM.replay(flat, "long", 1000.0, 990.0, 1020.0, 40, paths=500, seed=7)
        check("2. replay: odds add up to 1 and repeat with the same seed",
              a == b and abs(a["p_target"] + a["p_stop"] + a["p_neither"] - 1) < 0.002, a)
        up = rows_walk(1500, 0.0015, seed=3)
        lu = TM.replay(up, "long", 1000.0, 990.0, 1010.0, 60, paths=500, seed=1)
        su = TM.replay(up, "short", 1000.0, 1010.0, 990.0, 60, paths=500, seed=1)
        check("   on a rising chart a long reaches its target first more often than a short",
              lu["p_target"] > su["p_target"] and lu["avg_r"] > su["avg_r"], (lu, su))
        wide = [(r[0], r[1], r[4] * 1.05, r[4] * 0.95, r[4], 0) for r in flat]   # every candle +-5%
        w = TM.replay(wide, "long", 1000.0, 990.0, 1010.0, 5, paths=100, seed=1)
        check("   a candle touching both levels counts as the stop", w["p_stop"] == 1.0 and w["p_target"] == 0, w)
        check("   bars_left: intraday = a typical day minus today's candles; crypto = 4 hours",
              TM.bars_left(flat[:-10], day_of, True) == 75 - (len(flat[:-10]) % 75 or 75)
              and TM.bars_left(flat, day_of, False) == TM.CRYPTO_BARS,
              (TM.bars_left(flat[:-10], day_of, True), len(flat[:-10]) % 75))
        res = TM.run(flat, day_of, True, "long", 1000.0, 990.0, 1020.0, seed=2, chart="T:FLAT")
        check("   run(): replay + history + verdict, marked info only",
              res and set(res) >= {"replay", "history", "verdict", "gate"} and "info only" in res["gate"]
              and isinstance(res["history"], dict) and "trades" in res["history"], res)
        check("   run(): too few candles -> None", TM.run(flat[:100], day_of, True, "long", 1000, 990, 1020) is None)

        # ---------------------------------------------------------------- 3. paper.v4_timemachine
        import smc_playbook as PB
        acc = cfg["accounts"]["INDIA"]
        check("3. v4_timemachine: not a v4 setup -> None",
              P.v4_timemachine("NSE", "X", {"scanner": "v2", "side": "long"}, acc, 1000, 990, 1020) is None)
        r0 = P.v4_timemachine("NSE", "NOPE", {"scanner": "v4", "side": "long"}, acc, 1000, 990, 1020)
        check("   v4 but no candles in memory -> a 'not run' note", isinstance(r0, str) and r0.startswith("not run"), r0)
        PB.LAST_ROWS["NSE:FLAT"] = (flat, day_of, True)
        r1 = P.v4_timemachine("NSE", "FLAT", {"scanner": "v4", "side": "long"}, acc, 1000.0, 990.0, 1020.0)
        check("   v4 with the scanner's candles -> the time machine's dict", isinstance(r1, dict) and "replay" in r1, r1)
        PB.LAST_ROWS["NSE:BAD"] = ("junk", day_of, True)
        r2 = P.v4_timemachine("NSE", "BAD", {"scanner": "v4", "side": "long"}, acc, 1000.0, 990.0, 1020.0)
        check("   bad candles never raise (a 'not run' note)", isinstance(r2, str) and r2.startswith("not run"), r2)

        # ---------------------------------------------------------------- 4. api/_timemachine
        from api import _timemachine as A
        v4 = A.normalise(r1)
        check("4. normalise v4: engine v4, info only, odds and history",
              v4["engine"] == "v4" and v4["gate"] == "info only" and v4["p_target"] is not None
              and v4["hist_days"] is not None, v4)
        us = A.normalise({"p_target": 0.2, "p_stop": 0.3, "p_neither": 0.5, "avg_R": -0.1, "history_triggered": 30,
                          "history_avg_R": 0.05, "verdict": "x"})
        check("   normalise US pack", us["engine"] == "us-pack" and us["avg_r"] == -0.1 and us["hist_trades"] == 30, us)
        ind = A.normalise({"replay": {"target_first": 0.4, "stop_first": 0.35, "neither": 0.25, "avg_r": 0.12,
                                      "paths": 10000, "bars_left": 30}, "history": {"fired": 12, "avg_r": 0.3}})
        check("   normalise India", ind["engine"] == "india" and ind["p_target"] == 0.4 and ind["bars"] == 30
              and ind["hist_trades"] == 12, ind)
        cr = A.normalise({"candles": 500, "sim": {"target_first": 0.1, "stop_first": 0.6, "neither": 0.3,
                                                  "avg_r": -0.4}, "history": {"fired": 4, "avg_r": -0.2}})
        check("   normalise crypto", cr["engine"] == "crypto" and cr["p_stop"] == 0.6 and cr["hist_trades"] == 4, cr)
        path = os.path.join(tmp, "d.jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"time": "2026-11-14T10:00:00+05:30", "symbol": "NSE:A", "result": "skipped",
                                 "steps": {"5_timemachine": "n/a"}}) + "\n")
            fh.write("not json\n")
            fh.write(json.dumps({"time": "2026-11-14T10:05:00+05:30", "symbol": "NSE:FLAT", "result": "traded",
                                 "steps": {"1_scanner": {"setup_name": "v4 primary", "side": "long"},
                                           "4_exit": {"entry": 1000, "stop": 990, "target": 1020},
                                           "5_timemachine": r1}}) + "\n")
            fh.write(json.dumps({"time": "2026-11-14T10:10:00+05:30", "symbol": "US:META", "result": "skipped",
                                 "steps": {"5_timemachine": {"p_target": 0.1, "p_stop": 0.2, "p_neither": 0.7,
                                                             "avg_R": -0.1}}}) + "\n")
        out = A.runs(10, path)
        check("   runs(): only dict step-5 records, newest first, with the setup and levels",
              [r["symbol"] for r in out["runs"]] == ["US:META", "NSE:FLAT"] and out["runs"][1]["entry"] == 1000
              and out["runs"][1]["setup"] == "v4 primary" and out["counts"] == {"us-pack": 1, "v4": 1}, out)
        check("   runs(): limit counts all but lists only the newest", len(A.runs(1, path)["runs"]) == 1
              and A.runs(1, path)["counts"] == {"us-pack": 1, "v4": 1})
        check("   runs(): no decisions file -> empty", A.runs(5, os.path.join(tmp, "none.jsonl"))["runs"] == [])

        # ---------------------------------------------------------------- 5. the replays on a chart
        k = TM.replay(flat, "long", 1000.0, 990.0, 1020.0, 30, paths=300, seed=4, keep=25)
        plain = TM.replay(flat, "long", 1000.0, 990.0, 1020.0, 30, paths=300, seed=4)
        check("5. replay keep=25: 25 sample paths, same odds as without keep",
              len(k["samples"]) == 25 and all(k[x] == plain[x] for x in ("p_target", "p_stop", "avg_r")), k.get("p_target"))
        okp = all(p["c"][0] == 1000.0 and (p["end"] != "stop" or p["c"][-1] == 990.0)
                  and (p["end"] != "target" or p["c"][-1] == 1020.0) and len(p["c"]) <= 31 for p in k["samples"])
        check("   each path starts at the entry and ends at the stop / target it hit", okp)
        check("   the R histogram counts every path", sum(k["r_hist"]["counts"]) == 300, k["r_hist"])
        check("   run() saves its seed (the chart redraws the same paths)", isinstance(res.get("seed"), int), res.get("seed"))

        from api import _chart as CH
        bar_t = flat[1400][0]
        rec = {"time": bar_t.isoformat(), "symbol": "NSE:FLAT", "result": "PAPER BUY", "why": "ok",
               "steps": {"1_scanner": {"setup_name": "v4 primary long", "side": "long", "bar_end": bar_t.isoformat()},
                         "4_exit": {"entry": 1000.0, "stop": 990.0, "target": 1020.0}, "5_timemachine": r1}}
        CH._decisions = lambda: [rec]
        A._history_rows = lambda m, s, upto: [r[:5] for r in flat if r[0].timestamp() + 300 <= upto]
        CH.candles = lambda m, s, since: [(int(r[0].timestamp()), r[1], r[2], r[3], r[4]) for r in flat[1300:]]
        doc = A.chart_timemachine(rec["time"], "NSE:FLAT", show=40)
        rp = doc["replay"]
        check("   /api/py/chart/timemachine: candles, levels, 40 paths starting after the decision candle",
              len(doc["candles"]) == 200 and doc["pos"]["entry"] == 1000.0 and len(rp["paths"]) == 40
              and rp["start"] == int(bar_t.timestamp()) + 300 and rp["stats"]["paths"] == TM.PATHS, rp["stats"])
        check("   the verdict explains the run, the redraw, the decision and what really happened",
              any(l.startswith("Ran: Scanner v4") for l in doc["verdict"]["lines"])
              and any(l.startswith("On the chart:") for l in doc["verdict"]["lines"])
              and any(l.startswith("Decision:") for l in doc["verdict"]["lines"])
              and any(l.startswith("What really happened") for l in doc["verdict"]["lines"]), doc["verdict"]["lines"])
        hist_now = A._history_rows("NSE", "FLAT", int(bar_t.timestamp()) + 300)
        check("   no look-ahead: the replays use only candles closed by the decision",
              hist_now[-1][0] <= bar_t, hist_now[-1][0])
    finally:
        os.chdir(old)

    print()
    if FAILS:
        print("%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("all checks passed")
