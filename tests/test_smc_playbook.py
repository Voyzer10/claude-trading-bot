#!/usr/bin/env python3
"""Offline checks of the SMC playbook engine, the scanner hit and the auto agent (no network, temp folder).

    python tests/test_smc_playbook.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smc_playbook as PB  # noqa: E402

UTC = timezone.utc
FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


def series():
    """Yesterday ranges 99.0-102 (PDL 99.0); today drifts down to ~99.5, then a doji sweeps PDL and closes back
    above it, and the next candle closes above the doji's high (candle-1 confirmation)."""
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    rows, t = [], t0
    for k in range(96):                     # the first day in the data (partial days never become "previous")
        base = 103 + (0.3 if (k // 6) % 2 else -0.3)
        rows.append((t, base, base + 0.2, base - 0.2, base + 0.05, 100))
        t += timedelta(minutes=15)
    for k in range(96):                     # yesterday: zigzag 100..102, one dip to 99.0
        base = 101 + (1 if (k // 6) % 2 else -1) * 0.5
        lo = 99.0 if k == 40 else base - 0.2
        rows.append((t, base, base + 0.2, lo, base + 0.05, 100))
        t += timedelta(minutes=15)
    p = 101.0
    for k in range(40):                     # today: zigzag drift down to ~99.5
        p -= 0.04
        wig = 0.15 if (k // 4) % 2 else -0.15
        o, c = p + wig, p - wig
        rows.append((t, o, max(o, c) + 0.1, min(o, c) - 0.1, c, 100))
        t += timedelta(minutes=15)
    rows.append((t, 99.25, 99.6, 98.8, 99.3, 300))   # sweep of PDL 99.0 + doji (body 6%)
    t += timedelta(minutes=15)
    rows.append((t, 99.3, 99.9, 99.25, 99.8, 200))   # candle 1 closes above the doji high 99.6
    return rows


def engine_checks():
    rows = series()
    ctx = PB.Context(rows, lambda t: t.date())
    i = len(rows) - 1
    got = PB.find_setups(ctx, i)
    d = [s for s in got if s["setup"] == "doji_long"]
    check("doji_long found after a PDL sweep", bool(d), got)
    if d:
        s = d[0]
        check("swept level is PDL 99.0", s["level_name"] == "PDL" and abs(s["level"] - 99.0) < 1e-9, s)
        check("confirmed on candle 1", s["confirm_at"] == 1, s)
        check("stop below the doji low", PB.stop_for(s, 0.1) < 98.8)
        check("2R target", abs(PB.target_for(ctx, i, s, "2R", 98.7) - (99.8 + 2 * 1.1)) < 1e-9)
    # a close equal to the trigger high is not a confirmation
    eq = rows[:-1] + [(rows[-1][0], 99.3, 99.7, 99.25, 99.6, 200)]
    check("close == trigger high is not confirmation",
          not [s for s in PB.find_setups(PB.Context(eq, lambda t: t.date()), len(eq) - 1) if s["setup"] == "doji_long"])
    # candle 3 cannot revive the setup: two inside candles, then the close above the doji high
    t = rows[-1][0]
    c3 = rows[:-1] + [(t, 99.3, 99.5, 99.2, 99.4, 100), (t + timedelta(minutes=15), 99.4, 99.55, 99.3, 99.35, 100),
                      (t + timedelta(minutes=30), 99.35, 99.9, 99.3, 99.8, 200)]
    doji_i = len(rows) - 2
    check("candle 3 cannot revive the doji",
          not [s for s in PB.find_setups(PB.Context(c3, lambda t: t.date()), len(c3) - 1) if s["trigger"] == doji_i])
    return rows


def scanner_checks(rows):
    import scan_crypto as C
    C.set_timeframe("15m")
    d = {"t": [int(r[0].timestamp()) for r in rows], "o": [r[1] for r in rows], "h": [r[2] for r in rows],
         "l": [r[3] for r in rows], "c": [r[4] for r in rows], "v": [r[5] for r in rows]}
    cutoff = rows[-1][0] + timedelta(minutes=15)
    r = C.intraday_one(d, cutoff)
    check("scanner tags smcp_doji_long", r is not None and "smcp_doji_long" in r["tags"], r and r["tags"])
    return r


def agent_checks(r):
    old = os.getcwd()
    tmp = tempfile.mkdtemp()
    try:
        os.chdir(tmp)
        import auto_crypto as A
        import paper as P
        A.headlines = lambda sym, n=3: []
        P.fetch_price = lambda m, s: (99.8, "test")
        logs = []
        h = {"symbol": "TEST", "setup": "smcp_doji_long", "price": 99.8, "bar_end": r["bar_end"],
             "smcp": r["smcp"]["smcp_doji_long"], "new": True}
        cfg = dict(A.DEFAULTS, smcp_struct="none", smcp_target="2R")
        rec = A.run_smcp(h, cfg, logs.append)
        check("agent paper-buys the playbook long (2R)", rec["result"] == "PAPER BUY", (rec["result"], rec.get("why")))
        st = rec["steps"]
        check("agent steps: scanner / entry / exit filled",
              st.get("1_scanner", {}).get("liquidity_swept") == "PDL" and st.get("3_entry", {}).get("pattern") == "doji"
              and "stop" in st.get("4_exit", {}), st)
        cfg1 = dict(cfg, smcp_struct="before")
        h2 = dict(h, symbol="TEST2")
        rec2 = A.run_smcp(h2, cfg1, logs.append)
        check("structure rule can skip", rec2["result"] in ("skipped", "PAPER BUY"), rec2)
        rec3 = A.run_smcp(dict(h, symbol="TEST3"), dict(cfg, smcp_target="internal", smcp_min_rr=50), logs.append)
        check("target too close is skipped", rec3["result"] == "skipped", rec3.get("why"))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)


def zone_checks():
    t = [datetime(2026, 11, 2, tzinfo=UTC)]
    rows = []

    def add(o, h, l, c):
        rows.append((t[0], o, h, l, c, 100))
        t[0] += timedelta(minutes=15)
    for k in range(60):
        b = 100 + (0.3 if (k // 3) % 2 else 0.0)
        add(b, b + 0.2, b - 0.2, b + 0.05)
    add(100.2, 100.4, 100.0, 100.3)      # candle before the impulse (high 100.4)
    add(100.3, 101.7, 100.25, 101.6)     # displacement breaking the 100.5 swing high
    add(101.6, 102.0, 100.8, 101.9)      # low 100.8: gap 100.4..100.8
    add(101.9, 102.2, 101.5, 102.1)
    add(102.1, 102.3, 101.4, 101.6)
    add(101.2, 101.5, 100.7, 101.3)      # first retest into the gap, closes up above its middle
    ctx = PB.Context(rows, lambda x: x.date())
    got = PB.zone_setups(ctx, len(rows) - 1)
    check("FVG long on the first retest", [g["setup"] for g in got] == ["fvg_long"], got)
    if got:
        check("FVG stop below the gap", PB.stop_for(got[0], 0.1) < 100.4)
    check("no zone setup before the retest", not any(PB.zone_setups(ctx, i) for i in range(60, len(rows) - 1)))


def guard_checks():
    import paper as P
    now = datetime(2026, 11, 4, 6, 0, tzinfo=UTC)
    acc = dict(P.DEFAULT_CONFIG["accounts"]["CRYPTO"])

    def closed(mins_ago, pnl):
        x = now - timedelta(minutes=mins_ago)
        return {"market": "CRYPTO", "pnl": pnl, "exit_time": x.isoformat(), "exit_date": x.date().isoformat()}
    led = {"open": [], "closed": [closed(200, -5), closed(100, -5), closed(30, -5)]}
    try:
        P.rulebook_guards(led, "CRYPTO", acc, now, False)
        check("3 losses in a row -> cooldown", False, "not blocked")
    except P.PaperError as e:
        check("3 losses in a row -> cooldown", "cooldown" in str(e), e)
    led = {"open": [], "closed": [closed(400, -5), closed(300, -5), closed(200, -5)]}
    try:
        P.rulebook_guards(led, "CRYPTO", acc, now, False)
        check("cooldown over after 2h", True)
    except P.PaperError as e:
        check("cooldown over after 2h", False, e)
    led = {"open": [], "closed": [closed(2000, -40), closed(1500, -40), closed(500, 5), closed(400, -20)]}
    try:
        P.rulebook_guards(led, "CRYPTO", acc, now, False)
        check("weekly loss limit", False, "not blocked")
    except P.PaperError as e:
        check("weekly loss limit", "weekly" in str(e), e)
    led = {"open": [{"market": "CRYPTO", "key": "CRYPTO:%s" % s, "side": "long"} for s in "ABC"], "closed": []}
    blocked = False
    try:
        P.rulebook_guards(led, "CRYPTO", acc, now, False)
    except P.PaperError:
        blocked = True
    short_ok = True
    try:
        P.rulebook_guards(led, "CRYPTO", acc, now, True)
    except P.PaperError:
        short_ok = False
    check("max 3 longs open, a short still allowed", blocked and short_ok, (blocked, short_ok))


if __name__ == "__main__":
    rows = engine_checks()
    zone_checks()
    guard_checks()
    r = scanner_checks(rows)
    if r and "smcp_doji_long" in r["tags"]:
        agent_checks(r)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
