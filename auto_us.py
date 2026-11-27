#!/usr/bin/env python3
"""
auto_us.py - the original 11-agent pack, run automatically on live US breakouts,
with PAPER trades only (paper.py's US account; nothing is sent to a broker).

live.py --markets US --auto-paper calls process() every cycle. During 9:50 AM - 3:30 PM ET,
every `scan_every_min` minutes it runs the pack's scanner over the whole US universe. Each NEW,
FRESH breakout (triggered within `fresh_minutes`) goes through the pack's own scripts in us\\:

  1 scanner      trader-scanner/scan.py orb
  2 news         trader-news/news.py           (recorded, never acted on)
  3 entry        trader-entry/entry.py check   (must still say TRIGGERED), then the LIVE price must still be
                 above the range high (else "reversed") and at most max_chase_r R past it
  4 exit         trader-exit/exit.py plan      (stop at the range midpoint, 2R target)
  5 timemachine  trader-timemachine/timemachine.py run   (skips a negative edge)
  6 budget       trader-budget/size.py
  7 risk         trader-risk/check.py          (must PASS)
  8 broker       ..\\paper.py buy US:TICKER    (paper fill at the live price; your --auto-paper is the yes)
  9 alerts       trader-alerts/alerts.py add --from-plan; live.py's paper check closes stops,
                 targets and the 3:55 PM ET flat-by
 10 analyst      run by hand: python us\\us_flow.py analyst TICKER (needs sec_user_agent)
 11 pelosi       run by hand: python us\\us_flow.py pelosi

SHORTS (allow_short, on by default since 2 Nov 2026): the scanner also reports opening-range BREAKDOWNS
(a 5-minute close below the range low). The pack's entry / exit / time machine / budget / risk scripts are
long-only, so a breakdown goes through this file's own short path instead:
  3 entry        live price still below the range low (else "reversed"); chase at most max_chase_r R past
                 it; market regime: SPY below its own opening-range midpoint and its open (short_regime)
  4 exit         stop at the range midpoint (above the entry), target 2R below, min_stop_pct
  5 timemachine  n/a (the pack's is long-only): not a gate
  6-8            paper.py short in the US account (sizes to max loss; daily loss, trades/day, position cap)
  9 alerts       live.py's paper check: stop, target, 3:55 PM ET flat-by
Not backtested yet: paper only, judge it on its paper results.

Rules: trader/live/auto_us_config.json (made on first run). Decisions: trader/live/decisions.jsonl.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import paper as P

ROOT = os.path.dirname(os.path.abspath(__file__))
US = os.path.join(ROOT, "us")
LIVE_DIR = os.path.join("trader", "live")
CFG_FILE = os.path.join(LIVE_DIR, "auto_us_config.json")
DECISIONS = os.path.join(LIVE_DIR, "decisions.jsonl")
PY = sys.executable

DEFAULTS = {
    "_note": "Auto PAPER trading rules for US stocks. Paper money only.",
    "scan_every_min": 10,
    "max_confirm": 200,          # scanner stage 2: the N most traded candidates get real highs/lows
    "fresh_minutes": 15,         # only breakouts that triggered this recently
    "max_new_per_cycle": 5,
    "target": "2R",
    "min_stop_pct": 0.3,         # skip stops tighter than this % of the entry
    "min_mc_avg_r": 0.0,         # time machine replays must average at least this
    "min_history_trades": 10,
    "min_history_avg_r": 0.0,
    "allow_short": True,         # also trade opening-range breakdowns, on paper (see the docstring)
    "short_regime": True,        # shorts only while SPY is below its opening-range midpoint and its open
    "max_chase_r": 0.5,          # skip if the live price already ran this many R past the range (longs and shorts)
    "or_minutes": 15,
}


def load_cfg():
    os.makedirs(LIVE_DIR, exist_ok=True)
    if not os.path.exists(CFG_FILE):
        with open(CFG_FILE, "w", encoding="utf-8") as fh:
            json.dump(DEFAULTS, fh, indent=2)
    cfg = dict(DEFAULTS)
    with open(CFG_FILE, encoding="utf-8") as fh:
        cfg.update(json.load(fh))
    return cfg


def et_now(utc):
    return P.local_now("US", utc)


def sh(args, cwd=US, timeout=180):
    r = subprocess.run([PY] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def us_json(rel):
    try:
        with open(os.path.join(US, rel), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def tail(text, n=6):
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-n:]


def record(rec):
    with open(DECISIONS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def parse_at(at, day):
    t = datetime.strptime(at.strip(), "%I:%M %p")
    return day.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


def spy_weak(or_minutes=15, utc=None):
    """True if SPY's last completed 5-minute close is below its opening-range midpoint and below its open."""
    import scan_nse as S
    d = S.yahoo_chart("SPY", "1d", "5m", "")
    if not d or not d.get("t"):
        return None
    utc = utc or datetime.now(timezone.utc)
    off = P.us_offset(utc)
    bars = []
    for t, o, h, l, c in zip(d["t"], d["o"], d["h"], d["l"], d["c"]):
        et = datetime.fromtimestamp(t, timezone(off))
        if et.minute % 5 or et.second or not (9 * 60 + 30 <= et.hour * 60 + et.minute < 16 * 60):
            continue
        if datetime.fromtimestamp(t, timezone.utc) + timedelta(minutes=5) > utc:
            continue  # still forming
        bars.append((et, o, h, l, c))
    n = or_minutes // 5
    if len(bars) <= n:
        return None
    rng = bars[:n]
    mid = (max(b[2] for b in rng) + min(b[3] for b in rng)) / 2
    last = bars[-1][4]
    return last < mid and last < bars[0][1]


def run_short(tk, hit, cfg, log, auto):
    """An opening-range breakdown, sold short on paper (see the docstring)."""
    import contextlib
    import io
    rec = {"time": datetime.now(P.IST).isoformat(), "symbol": "US:" + tk, "setup": "orb_short", "steps": {},
           "result": None}
    st = rec["steps"]
    st["1_scanner"] = dict(hit, setup_name="ORB short", scanner="rules",
                            liquidity="opening range low %s" % hit.get("or_low"))

    def done(result, why):
        rec["result"], rec["why"] = result, why
        st["10_analyst"] = "by hand: python us\\us_flow.py analyst %s" % tk
        st["11_pelosi"] = "by hand: python us\\us_flow.py pelosi"
        record(rec)
        log("AUTO US %s: %s (%s)" % (tk, result, why))
        return rec

    _, out = sh([os.path.join("trader-news", "news.py"), "--tickers", tk, "--hours", "12", "--no-sec", "--all"])
    st["2_news"] = tail(out, 8)
    try:
        price, _ = P.fetch_price("US", tk)
    except Exception as e:
        return done("skipped", "no live price: %s" % e)
    lo, hi = float(hit["or_low"]), float(hit["or_high"])
    stop = P.round_px("US", (hi + lo) / 2, down=False)
    risk = stop - price
    chase = (lo - price) / risk if risk > 0 else None
    st["3_entry"] = {"side": "short", "price_now": price, "trigger": lo,
                     "chase_r": round(chase, 2) if chase is not None else None}
    if price >= lo:
        return done("skipped", "price %s moved back inside the opening range (low %s): reversed" % (price, lo))
    if risk <= 0:
        return done("skipped", "price %s is already past the stop %s" % (price, stop))
    if cfg.get("max_chase_r") and chase > cfg["max_chase_r"]:
        return done("skipped", "chasing: price is %.2fR below the range low (max %.2fR)" % (chase, cfg["max_chase_r"]))
    if cfg.get("short_regime"):
        try:
            weak = spy_weak(cfg.get("or_minutes", 15))
        except Exception as e:
            weak = None
            st["regime"] = "unavailable: %s" % e
        st["regime"] = weak
        if weak is None:
            return done("skipped", "market regime unknown (no SPY bars)")
        if not weak:
            return done("skipped", "market regime: SPY is not below its opening-range midpoint and its open (no shorts)")
    target = P.round_px("US", price - 2 * risk, down=True)
    stop_pct = risk / price * 100
    st["4_exit"] = {"entry": price, "stop": stop, "target": target, "stop_pct": round(stop_pct, 2),
                    "r_multiple": 2.0}
    if stop_pct < cfg["min_stop_pct"]:
        return done("skipped", "stop too tight: %.2f%% (min %.2f%%)" % (stop_pct, cfg["min_stop_pct"]))
    st["5_timemachine"] = "n/a for shorts (the pack's time machine is long-only): not a gate"
    if not auto:
        return done("ready", "all checks passed; auto paper is off")
    pcfg = P.load_config()
    led = P.load_ledger(pcfg)
    args = type("A", (), {"symbol": "US:" + tk, "stop": str(stop), "target": str(target), "qty": None, "lots": None,
                          "price": str(price), "note": "auto_us: orb short", "force": False, "side": "short",
                          "setup": "orb_short", "scanner": "rules", "setup_name": "ORB short",
                          "liquidity": "opening range low %s" % lo,
                          "entry_reason": "close below the opening range low %s" % lo})()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            P.cmd_buy(args, pcfg, led)
        P.save_json(P.LEDGER, led)
    except P.PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    pos = next(p for p in led["open"] if p["key"] == "US:" + tk)
    st["6-8_budget_risk_broker"] = {"verdict": "PASS, paper short filled", "qty": pos["qty"], "entry": pos["entry"],
                                    "stop": pos["stop"], "target": pos["target"],
                                    "max_loss": round((pos["stop"] - pos["entry"]) * pos["qty"], 2),
                                    "report": buf.getvalue().strip().splitlines()}
    st["9_alerts"] = "live.py checks stop %s / target %s every cycle; flat by 3:55 PM ET" % (pos["stop"], pos["target"])
    return done("PAPER SHORT", "%s sh @ %s, stop %s, target %s (opening-range breakdown, SPY weak)" % (
        pos["qty"], pos["entry"], pos["stop"], pos["target"]))


def sync_pack_config():
    """The pack's budget and risk scripts read us/trader/config.json; give them the paper US account's numbers
    (2 Nov: budget was unset, so every long that passed the time machine failed at the budget step)."""
    path = os.path.join(US, "trader", "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            c = json.load(fh)
    except Exception:
        c = {}
    pcfg = P.load_config()
    acc = pcfg["accounts"]["US"]
    led = P.load_ledger(pcfg)
    want = {"budget": round(float(led["accounts"]["US"]["cash"]), 2), "max_loss_per_trade_usd": acc["max_loss_per_trade"],
            "max_daily_loss_usd": acc["daily_loss_limit"],
            # no daily trade / order COUNT limit (owner, 21 Nov 2026): 0 = off in trader-risk/check.py
            "max_trades_per_day": 0, "max_orders_per_day": 0,
            "max_position_pct": acc["max_position_pct"]}
    if any(c.get(k) != v for k, v in want.items()):
        c.update(want)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(c, fh, indent=2)


def run_one(tk, hit, cfg, log, auto):
    if hit.get("side") == "short":
        return run_short(tk, hit, cfg, log, auto)
    rec = {"time": datetime.now(P.IST).isoformat(), "symbol": "US:" + tk, "setup": "orb", "steps": {}, "result": None}
    st = rec["steps"]
    st["1_scanner"] = dict(hit, setup_name="ORB", scanner="rules",
                            liquidity="opening range high %s" % hit.get("or_high"))

    def done(result, why):
        rec["result"], rec["why"] = result, why
        st["10_analyst"] = "by hand: python us\\us_flow.py analyst %s" % tk
        st["11_pelosi"] = "by hand: python us\\us_flow.py pelosi"
        record(rec)
        log("AUTO US %s: %s (%s)" % (tk, result, why))
        return rec

    _, out = sh([os.path.join("trader-news", "news.py"), "--tickers", tk, "--hours", "12", "--no-sec", "--all"])
    st["2_news"] = tail(out, 8)

    rc, out = sh([os.path.join("trader-entry", "entry.py"), "check", tk, "--setup", "orb", "--write"])
    e = us_json(os.path.join("trader", "entry.json")) or {}
    st["3_entry"] = {"status": e.get("status"), "time": e.get("time"), "price": e.get("price"), "level": e.get("level")}
    if e.get("symbol") != tk or e.get("status") != "triggered":
        return done("skipped", "entry says %s" % e.get("status"))

    rc, out = sh([os.path.join("trader-exit", "exit.py"), "plan", "--stop", "or-mid", "--target", cfg["target"], "--write"])
    plan = us_json(os.path.join("trader", "plan.json")) or {}
    if plan.get("symbol") != tk or plan.get("date") != e.get("date"):
        return done("skipped", "exit planner refused: %s" % " ".join(tail(out, 2)))
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    stop_pct = (entry - stop) / entry * 100
    st["4_exit"] = {"entry": entry, "stop": stop, "target": target, "stop_pct": round(stop_pct, 2)}
    if stop_pct < cfg["min_stop_pct"]:
        return done("skipped", "stop too tight: %.2f%% (min %.2f%%)" % (stop_pct, cfg["min_stop_pct"]))
    # the plan is built from the breakout candle's close; the paper fill is at the LIVE price. Check it is still
    # above the range high (3 Nov AAPL: the 9:50 candle closed at 333.82 over the 332.67 high, but the fill came at
    # 331.96, back inside the range, and it stopped out) and not too far past it (same rules as the short path).
    try:
        price_now, _ = P.fetch_price("US", tk)
    except Exception as ex:
        return done("skipped", "no live price: %s" % ex)
    trig = float(hit.get("or_high") or e.get("level") or entry)
    risk_now = price_now - stop
    chase = (price_now - trig) / risk_now if risk_now > 0 else None
    st["3_entry"].update({"price_now": price_now, "trigger": trig,
                          "chase_r": round(chase, 2) if chase is not None else None})
    if price_now <= trig:
        return done("skipped", "price %s moved back inside the opening range (high %s): reversed" % (price_now, trig))
    if risk_now <= 0:
        return done("skipped", "price %s is already at or under the stop %s" % (price_now, stop))
    if cfg.get("max_chase_r") and chase > cfg["max_chase_r"]:
        return done("skipped", "chasing: price is %.2fR above the range high (max %.2fR)" % (chase, cfg["max_chase_r"]))

    rc, out = sh([os.path.join("trader-timemachine", "timemachine.py"), "run", "--write"], timeout=300)
    tm = us_json(os.path.join("trader", "timemachine.json")) or {}
    mc, hist = tm.get("mc") or {}, tm.get("history") or {}
    st["5_timemachine"] = {"p_target": mc.get("p_target"), "p_stop": mc.get("p_stop"), "p_neither": mc.get("p_neither"),
                           "avg_R": mc.get("avg_R"), "history_triggered": hist.get("triggered"),
                           "history_avg_R": hist.get("avg_R"), "verdict": tm.get("verdict")}
    if (tm.get("plan") or {}).get("symbol") != tk or mc.get("avg_R") is None:
        return done("skipped", "time machine could not run: %s" % " ".join(tail(out, 2)))
    if mc["avg_R"] < cfg["min_mc_avg_r"]:
        return done("skipped", "time machine: replays average %+.2fR" % mc["avg_R"])
    if (hist.get("triggered") or 0) >= cfg["min_history_trades"] and (hist.get("avg_R") or 0) < cfg["min_history_avg_r"]:
        return done("skipped", "time machine: this rule averaged %+.2fR over %d past fires" % (hist["avg_R"], hist["triggered"]))

    try:
        sync_pack_config()
    except Exception as ex:
        log("AUTO US: could not sync the pack's budget config: %s" % ex)
    rc, out = sh([os.path.join("trader-budget", "size.py"), "--write"])
    st["6_budget"] = tail(out, 4)
    orders = (us_json(os.path.join("trader", "orders.json")) or {}).get("orders", [])
    o = next((x for x in orders if x.get("symbol") == tk), None)
    if not o:
        return done("skipped", "budget wrote no order: %s" % " ".join(tail(out, 2)))

    rc, out = sh([os.path.join("trader-risk", "check.py")])
    risk = us_json(os.path.join("trader", "state", "risk.json")) or {}
    res = [x for x in risk.get("results", []) if x.get("symbol") == tk and x.get("kind") == "entry"]
    st["7_risk"] = {"verdict": res[-1].get("verdict") if res else None,
                    "reasons": res[-1].get("reasons") if res else tail(out, 3)}
    if not res or res[-1].get("verdict") != "PASS":
        return done("blocked", "risk: %s" % "; ".join(st["7_risk"]["reasons"] or ["no PASS"]))

    if not auto:
        return done("ready", "all checks passed; auto paper is off")
    rc, out = sh([os.path.join(ROOT, "paper.py"), "buy", "US:" + tk, "--qty", str(o["qty"]),
                  "--stop", str(stop), "--target", str(target), "--note", "auto_us: orb"], cwd=ROOT)
    st["8_broker"] = tail(out, 4)
    if rc != 0:
        return done("blocked", "paper.py: %s" % " ".join(tail(out, 1)))
    _, out = sh([os.path.join("trader-alerts", "alerts.py"), "add", "--from-plan"])
    st["9_alerts"] = tail(out, 3)
    return done("PAPER BUY", "%s sh, stop %s, target %s; replays %+.2fR, history %s" % (
        o["qty"], stop, target, mc["avg_R"],
        ("%s fires %+.2fR" % (hist.get("triggered"), hist.get("avg_R"))) if hist.get("triggered") else "n/a"))


# The Scanner (v4, v3 or v2, per Settings) on US stocks: the owner's setups on a fixed list of liquid names, each new 5m candle while the session
# is open. They go through the agents and are recorded only (paper.setup_decision: LOG ONLY, no broker).
US_WATCH = ("AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V MA UNH HD PG COST JNJ XOM CVX ABBV MRK PEP KO WMT BAC "
            "WFC CSCO ORCL CRM ADBE AMD INTC QCOM TXN AMAT MU NFLX DIS NKE MCD SBUX MAR HLT BKNG ABNB UBER LYFT "
            "CAT DE BA GE HON LMT RTX UPS FDX GS MS C AXP BLK SCHW PYPL SQ SHOP COIN PLTR SNOW CRWD PANW NOW "
            "INTU ISRG LLY PFE TMO DHR AMGN GILD CVS CI T VZ TMUS CMCSA CHTR SPGI ICE CME MMM DOW LIN F GM RIVN "
            "SPY QQQ").split()
# the Nasdaq-100 (owner, 13 Nov 2026: "NASDAQ as a index and uske stocks ko bhi watch list m add karo"); list as
# published in Nov 2026 (stockanalysis.com); names already above are not repeated
NASDAQ_100 = ("AAPL NVDA MSFT AMZN MU AMD TSLA META WMT GOOGL SPCX GOOG AVGO COST CSCO PLTR INTC AMAT TXN PANW LRCX "
              "NFLX AMGN CRWD LIN GILD ADI KLAC PEP SHOP QCOM TMUS ISRG SNDK ASML MRVL VRTX BKNG STX SBUX ADP WDC MAR "
              "MRNA ADBE INTU CSX MNST FTNT REGN CTAS CDNS SNPS MELI CMCSA CEG MDLZ ARM APP DASH ROST ORLY ABNB HON "
              "AEP NXPI DDOG MPWR FAST ADSK LITE PCAR IDXX PDD MSTR PYPL FANG CCEP XEL KDP HONA BKR ROP EXC TRI FER "
              "PAYX MCHP WDAY TER TTWO ALAB GEHC ODFL AXON NBIS DXCM RKLB CPRT CRWV ALNY").split()
# the Dow Jones Industrial Average's 30 (owner, 13 Nov 2026: "DOW bhi issi m hi add kardo"); list as of July 2026
# (topforeignstocks.com), with DIA, its ETF (US F&O trades DIA options too)
DOW_30 = ("MMM GOOGL AMZN AXP AMGN AAPL BA CAT CVX CSCO KO GS HD HON IBM JNJ JPM MCD MRK MSFT NKE NVDA PG CRM SHW "
          "TRV UNH V WMT DIS").split()
US_WATCH = list(dict.fromkeys(US_WATCH + NASDAQ_100 + DOW_30 + ["DIA"]))
# the indices on the US watch list (Yahoo, 5-minute closes): key, Yahoo symbol, name
US_INDICES = [("NDX", "^NDX", "Nasdaq-100"), ("IXIC", "^IXIC", "Nasdaq Composite"), ("SPX", "^GSPC", "S&P 500"),
              ("DJI", "^DJI", "Dow Jones")]
_SETUP_BAR = {"last": None}


def scan_setups(log):
    from zoneinfo import ZoneInfo
    import scan_nse as S
    et = ZoneInfo("America/New_York")
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=1)).replace(second=0, microsecond=0)
    last = last - timedelta(minutes=last.minute % 5)     # end of the last closed 5m candle
    lt = last.astimezone(et)
    if not ((9, 35) <= (lt.hour, lt.minute) <= (16, 0)) or _SETUP_BAR["last"] == last.isoformat():
        return
    _SETUP_BAR["last"] = last.isoformat()
    ver = __import__("smc_playbook").scanner_version("US")
    data, _ = S.fetch_many(US_WATCH, "5d" if ver == "v6" else "1d", "5m", 8, "", True)
    try:   # the dashboard's US watch list (owner, 10 Nov 2026)
        quotes = {s: q for s in US_WATCH for q in [S.watch_quote(data.get(s))] if q}
        idx, _ = S.fetch_many([y for _, y, _ in US_INDICES], "1d", "5m", 3, "", True)
        indices = {k: dict(q, name=n, yahoo=y) for k, y, n in US_INDICES for q in [S.watch_quote(idx.get(y))] if q}
        with open(os.path.join(LIVE_DIR, "us_watch.json"), "w", encoding="utf-8") as fh:
            json.dump({"as_of": last.isoformat(), "symbols": list(US_WATCH), "quotes": quotes, "indices": indices}, fh)
    except Exception as e:
        log("US watch list not saved: %s" % e)
    keep = lambda r: (9, 30) <= (r[0].hour, r[0].minute) < (16, 0)
    setups = S.setups_scan(data, "US", "", last, et, 8, keep)
    if not setups:
        if ver == "v6":
            try:
                import scanner_v6_bridge as V6B
                f = V6B.funnel_summary("US")
                log("AUTO US V6 funnel: %d symbols, %d in transition, %d sweeps, %d patterns, %d confirmed, %d dropped (no pool)" % (
                    f["symbols"], f["transition"], f["sweeps"], f["patterns"], f["confirmed"], f["no_pool_drops"]))
            except Exception:
                pass
        return
    by = {}
    for x in setups:
        try:
            rec = P.setup_decision("US", x["symbol"], x)
        except Exception as e:
            log("AUTO US %s %s failed: %s" % (x["symbol"], x["setup"], e))
            continue
        record(rec)
        by[rec["result"]] = by.get(rec["result"], 0) + 1
    ver = (setups[0].get("scanner") if setups else None) or __import__("smc_playbook").scanner_version("US")
    log("AUTO US: Scanner %s found %d of your setups (%s): %s" % (
        ver, len(setups), ", ".join("%s %s" % (x["symbol"], x.get("name")) for x in setups[:8]) + (" ..." if len(setups) > 8 else ""),
        ", ".join("%d %s" % (v, k) for k, v in sorted(by.items()))))


def process(state, log, auto=True):
    cfg = load_cfg()
    utc = datetime.now(timezone.utc)
    et = et_now(utc)
    ms = state.setdefault("markets", {}).setdefault("US", {})
    if P.session("US", utc) != "open":
        ms["status"] = "closed"
        return
    try:
        scan_setups(log)
    except Exception as e:
        log("US Scanner failed: %s" % e)
    import smc_playbook as PB
    own = PB.v4_only("US")
    if own:                        # Scanner v4 / v5 only: the opening-range breakout scan and trades are off
        ms["status"] = "Scanner %s only: the opening-range breakout rules are off" % own
        if ms.get("v4_note") != utc.date().isoformat():
            ms["v4_note"] = utc.date().isoformat()
            log("AUTO US: Scanner %s only: opening-range breakouts are not scanned or traded today" % own)
        return
    start = et.replace(hour=9, minute=50, second=0, microsecond=0)
    stop = et.replace(hour=15, minute=30, second=0, microsecond=0)
    if not (start <= et < stop):
        ms["status"] = "open, outside the 9:50-15:30 ET entry window"
        return
    last = ms.get("last_scan_utc")
    if last and utc - datetime.fromisoformat(last) < timedelta(minutes=cfg["scan_every_min"]):
        return
    if not os.path.exists(os.path.join(US, "trader", "universe.txt")):
        sh([os.path.join("trader-scanner", "scan.py"), "universe"], timeout=300)
    log("US scan starting (whole universe, a few minutes)...")
    try:
        rc, out = sh([os.path.join("trader-scanner", "scan.py"), "orb", "--max-confirm", str(cfg["max_confirm"]),
                      "--side", "both" if cfg.get("allow_short") else "long"], timeout=900)
    except subprocess.TimeoutExpired:
        log("US scan timed out")
        return
    ms["last_scan_utc"] = utc.isoformat()
    wl = us_json(os.path.join("trader", "watchlist.json")) or {}
    hits = wl.get("hits", [])
    today = et.date().isoformat()
    seen = ms.get("seen") if ms.get("seen_date") == today else {}
    fresh, new = [], []
    for h in hits:
        if h["symbol"] in seen:
            continue
        new.append(h["symbol"])
        try:
            age = et - parse_at(h["at"], et)
        except Exception:
            seen[h["symbol"]] = h.get("at")
            continue
        if age <= timedelta(minutes=cfg["fresh_minutes"]):
            fresh.append(h)       # marked seen only once it is actually run below
        else:
            seen[h["symbol"]] = h.get("at")  # stale: never run
    ms.update({"seen": seen, "seen_date": today, "as_of": wl.get("as_of"), "hits": len(hits),
               "status": "scanned", "summary": tail(out, 1)})
    log("US ORB @%s: %d hits, %d new, %d fresh (<= %d min)%s" % (
        wl.get("as_of"), len(hits), len(new), len(fresh), cfg["fresh_minutes"],
        ("; FRESH: " + ", ".join(h["symbol"] + (" (short)" if h.get("side") == "short" else "") for h in fresh[:15]))
        if fresh else ""))
    fresh.sort(key=lambda h: (-h.get("bar_index", 0), h["symbol"]))
    out_recs = []
    for h in fresh[:cfg["max_new_per_cycle"]]:
        seen[h["symbol"]] = h.get("at")
        try:
            out_recs.append(run_one(h["symbol"], h, cfg, log, auto))
        except Exception as ex:
            log("AUTO US %s failed: %s" % (h["symbol"], ex))
    auto_st = state.setdefault("auto", {"recent": []})
    auto_st["recent"] = (auto_st.get("recent", []) + [{"time": r["time"], "symbol": r["symbol"], "result": r["result"],
                                                       "why": r["why"]} for r in out_recs])[-20:]
