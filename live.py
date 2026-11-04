#!/usr/bin/env python3
"""
live.py - hands-off live scanner for NSE, BSE and crypto.

Start it once (start_live.bat) and leave the window open. During NSE/BSE hours
it re-scans every few minutes; crypto is scanned around the clock (a new
15-minute candle = a new scan). Every cycle also checks your paper trades.
Everything lands in trader/live/:

    trader/live/state.json   the latest scans, new hits and paper positions (Claude reads this)
    trader/live/log.txt      one line per cycle, so you can see what changed when

    python live.py                       # NSE + BSE + crypto
    python live.py --markets CRYPTO      # crypto only
    python live.py --markets NSE         # NSE only
    python live.py --interval 180        # every 3 minutes
    python live.py --once                # one cycle and exit (handy to test)

It never places an order. A hit is a chart that matched a rule, not a buy.
Data: Yahoo Finance's free, unofficial endpoints (can lag). Holidays are not
in a calendar here: on a holiday the scans come back empty and it backs off.
"""
import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import scan_crypto as C
import scan_nse as S

LIVE_DIR = os.path.join("trader", "live")
STATE = os.path.join(LIVE_DIR, "state.json")
LOG = os.path.join(LIVE_DIR, "log.txt")
OPEN_HM, CLOSE_HM = S.OPEN, S.CLOSE


def now_ist():
    return datetime.now(S.IST)


def log(msg):
    line = "%s  %s" % (now_ist().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    os.makedirs(LIVE_DIR, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


_push_note = {"done": False}


def save_state(state):
    os.makedirs(LIVE_DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, STATE)
    push_dashboard(state)


def push_dashboard(state):
    """Send the snapshot to the web dashboard (dashboard_push.py). Never stops the runner."""
    try:
        import dashboard_push
        res = dashboard_push.push(state)
        if state.get("runner_mode") == "cloud":
            return  # the cloud runner stores the snapshot itself
        if res.get("pushed") and not _push_note["done"]:
            log("Dashboard: pushed (%s bytes, storage %s)." % (res.get("bytes"), res.get("storage")))
            _push_note["done"] = True
        elif not res.get("pushed") and not _push_note["done"]:
            log("Dashboard: snapshot saved to trader/live/dashboard_snapshot.json (open it with start_dashboard.bat).")
            _push_note["done"] = True
    except Exception as e:
        if not _push_note.get("err"):
            log("Dashboard push failed: %s (the runner keeps going)" % e)
            _push_note["err"] = True


def load_state():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def universe(market, a):
    if market == "NSE" and a.nifty50:
        return list(S.NIFTY50), "built-in Nifty 50"
    if market == "NSE" and not os.path.exists(S.UNIVERSE_FILES["NSE"]) and not a._tried_download:
        a._tried_download = True
        try:
            n, _ = S.download_nifty500()
            log("Downloaded the Nifty 500 list (%d symbols)." % n)
        except S.ScanError as e:
            log("Nifty 500 download failed (%s); using the built-in Nifty 50." % e)
    return S.universe_for(market)


def paper_snapshot():
    """Run paper.py's stop/target/flat-by check and return the open and today's closed trades."""
    try:
        import paper as P
    except ImportError:
        return None
    if not os.path.exists(P.LEDGER):
        return {"open": [], "closed_today": []}
    cfg = P.load_config()
    led = P.load_ledger(cfg)
    if led["open"]:
        P.check_once(cfg, led)
        P.save_json(P.LEDGER, led)
    today = now_ist().date().isoformat()
    opens = []
    for p in led["open"]:
        row = dict(p)
        try:
            row["last"] = P.fetch_price(p["market"], p["symbol"])[0]
            row["open_pnl"] = round(P.pnl_of(p, row["last"]), 2)   # sign-aware: a short gains when price falls
        except Exception:
            pass
        opens.append(row)
    return {"open": opens, "closed_today": [c for c in led["closed"] if c.get("exit_date") == today]}


COOLDOWN = timedelta(hours=6)  # one evaluated breakout per coin per 6 h, like the backtest's one trade at a time


def crypto_cycle(state, a):
    """24/7: daily setups once per UTC day, the 15-minute scan whenever a new candle has closed."""
    utc = now_ist().astimezone(timezone.utc)
    ms = state["markets"].setdefault("CRYPTO", {})
    try:
        import auto_crypto
        tf = C.set_timeframe(auto_crypto.load_cfg().get("timeframe", "15m"))
    except Exception:
        tf = C.set_timeframe("15m")
    if ms.get("timeframe") != tf:
        if ms.get("timeframe"):
            log("CRYPTO timeframe now %dm candles (4h range = %d candles)" % (tf, C.RANGE_BARS))
        ms["timeframe"], ms["intraday"] = tf, None   # rescan on the new candles
    syms, src = C.universe()
    ms["universe_source"] = src
    d = ms.get("daily") or {}
    if d.get("scanned_on") != utc.date().isoformat():
        try:
            res = C.daily_scan(syms, utc, a.workers, quiet=True)
            res["scanned_on"] = utc.date().isoformat()
            ms["daily"] = res
            tags = {}
            for h in res["hits"]:
                tags[h["setup"]] = tags.get(h["setup"], 0) + 1
            log("CRYPTO daily: %d of %d charts, closes through %s UTC; %s"
                % (res["scanned"], len(syms), res["closes_through"],
                   ", ".join("%s %d" % kv for kv in sorted(tags.items())) or "no setups"))
        except Exception as e:
            state["errors"].append("CRYPTO daily: %s" % e)
            log("CRYPTO daily scan failed: %s" % e)
    try:  # each coin's behaviour over 30 days, once a UTC day, in a background thread (display only)
        import coin_profile
        if coin_profile.due():
            coin_profile.refresh_async(syms, log)
    except Exception as e:
        log("CRYPTO coin profiles not started: %s" % e)
    if (ms.get("intraday") or {}).get("as_of") == C.last_bar_close(utc).isoformat():
        return  # no new candle yet
    try:
        res = C.intraday_scan(syms, utc, a.workers, quiet=True)
    except Exception as e:
        state["errors"].append("CRYPTO intraday: %s" % e)
        log("CRYPTO %dm scan failed: %s" % (C.BAR_MIN, e))
        return
    data = res.pop("_data", None)
    try:  # Scanner v2: the owner's setups (A-B-C-D, playbook, FVG / order block) -> the agents (record only, no trade)
        import scanner_v2 as V2
        V2.crypto(state, data, C.BAR_MIN, datetime.fromisoformat(res["as_of"]), log)
    except Exception as e:
        log("CRYPTO scanner v2 failed: %s" % e)
    today = now_ist().date().isoformat()
    seen = ms.get("seen") if ms.get("seen_date") == today else {}  # display only: first time seen today
    # Which hits go to the agents, matching the backtest (research.py crypto_events): a FRESH cross of the
    # 4h high, and at most one per coin every 6 hours. (Before: one per coin per day, so by early morning
    # every coin was "used up" and later breakouts were never evaluated.)
    last_ev = ms.get("last_event") or {}
    new = []
    for h in res["hits"]:
        k = "%s/%s" % (h["symbol"], h["setup"])
        h["first_seen"] = seen.get(k, datetime.fromisoformat(res["as_of"]).astimezone(S.IST).strftime("%H:%M"))
        seen.setdefault(k, h["first_seen"])
        bar_end = h.get("bar_end") or res["as_of"]
        prev = last_ev.get(k)
        cooling = bool(prev) and datetime.fromisoformat(bar_end) - datetime.fromisoformat(prev) < COOLDOWN
        h["new"] = bool(h.get("fresh", True)) and not cooling
        if h["new"]:
            last_ev[k] = bar_end
            new.append("%s (%s)" % (h["symbol"], {"range_breakout_4h": "breakout", "range_breakdown_4h": "breakdown"}
                                    .get(h["setup"], "oversold")))
    horizon = datetime.fromisoformat(res["as_of"]) - timedelta(days=1)
    ms["last_event"] = {k: v for k, v in last_ev.items() if datetime.fromisoformat(v) > horizon}
    ms["seen"], ms["seen_date"] = seen, today
    ms["intraday"] = res
    brk = sum(1 for h in res["hits"] if h["setup"] == "range_breakout_4h")
    osd = sum(1 for h in res["hits"] if h["setup"] == "oversold_15m")
    bdn = sum(1 for h in res["hits"] if h["setup"] == "range_breakdown_4h")
    log("CRYPTO %dm @%s IST: %d/%d usable; %d above their 4h high, %d below their 4h low, %d oversold%s"
        % (C.BAR_MIN, datetime.fromisoformat(res["as_of"]).astimezone(S.IST).strftime("%H:%M"), res["usable"], res["scanned"],
           brk, bdn, osd, ("; NEW: " + ", ".join(new[:15])) if new else ""))
    if a.auto_paper:
        try:
            import auto_crypto
            auto_crypto.process(state, res, log)
        except Exception as e:
            state["errors"].append("auto paper: %s" % e)
            log("auto paper failed: %s" % e)


def cycle(state, a, markets):
    now = now_ist()
    today = now.date().isoformat()
    state.setdefault("markets", {})
    state["errors"] = []
    for m in markets:
        if m == "CRYPTO":
            crypto_cycle(state, a)
            continue
        if m == "US":
            try:
                import auto_us
                auto_us.process(state, log, auto=a.auto_paper)
            except Exception as e:
                state["errors"].append("US: %s" % e)
                log("US cycle failed: %s" % e)
            try:  # Scanner v2 on ~95 liquid US stocks -> the agents (record only, no trade)
                import scanner_v2 as V2
                V2.us(state, V2.US_WATCH, S.fetch_many, log)
            except Exception as e:
                log("US scanner v2 failed: %s" % e)
            continue
        if m == "FNO":
            if a.auto_paper:
                try:
                    import auto_fno
                    auto_fno.process(state, log)
                except Exception as e:
                    state["errors"].append("FNO: %s" % e)
                    log("FNO cycle failed: %s" % e)
            continue
        ms = state["markets"].setdefault(m, {})
        syms, src = universe(m, a)
        ms["universe_source"] = src
        # daily setups: once per day (before/at the first cycle), and again after the close
        d = ms.get("daily") or {}
        after_close = now >= S.at(now, CLOSE_HM) + timedelta(minutes=5)
        want_eod = after_close and not d.get("eod_done_for") == today
        if d.get("scanned_on") != today or want_eod:
            try:
                res = S.daily_scan(syms, m, now, a.min_price, a.min_volume, a.workers, quiet=True)
                res["scanned_on"] = today
                if after_close:
                    res["eod_done_for"] = today
                ms["daily"] = res
                tags = {}
                for h in res["hits"]:
                    tags[h["setup"]] = tags.get(h["setup"], 0) + 1
                log("%s daily: %d of %d charts, closes through %s; %s"
                    % (m, res["scanned"], len(syms), res["closes_through"],
                       ", ".join("%s %d" % kv for kv in sorted(tags.items())) or "no setups"))
            except Exception as e:
                state["errors"].append("%s daily: %s" % (m, e))
                log("%s daily scan failed: %s" % (m, e))
        # opening-range breakouts: every cycle during the session
        cutoff = S.orb_cutoff(now)
        if now >= S.at(now, CLOSE_HM) + timedelta(minutes=5) or not S.orb_ready(cutoff, a.or_minutes):
            continue
        prev = ms.get("orb") or {}
        if prev.get("as_of") == cutoff.isoformat():
            continue  # no new completed bar since the last scan
        try:
            side = "long"
            if m == "NSE" and a.auto_paper:  # breakdowns too, for the NSE short path (auto_nse allow_short)
                try:
                    import auto_nse
                    side = "both" if auto_nse.load_cfg().get("allow_short") else "long"
                except Exception:
                    pass
            res = S.orb_scan(syms, m, now, cutoff, a.or_minutes, a.min_price, a.workers, quiet=True, side=side)
        except Exception as e:
            state["errors"].append("%s orb: %s" % (m, e))
            log("%s ORB scan failed: %s" % (m, e))
            continue
        data = res.pop("_data", None)
        try:  # Scanner v2 on the same 5m candles -> the agents (record only, no trade)
            import scanner_v2 as V2
            V2.nse(state, m, data, cutoff, S.SUFFIX[m], S.fetch_many, S.IST, a.workers, log)
        except Exception as e:
            log("%s scanner v2 failed: %s" % (m, e))
        if res["scanned"] and res["usable"] == 0:
            ms["orb"] = res
            ms["orb"]["note"] = "no usable charts: holiday, or Yahoo lagging"
            log("%s ORB: %d charts but none usable (holiday or data lag)." % (m, res["scanned"]))
            state["holiday_suspected"] = today
            continue
        seen = ms.get("seen") if ms.get("seen_date") == today else {}
        new = []
        for h in res["hits"]:
            h["first_seen"] = seen.get(h["symbol"], cutoff.strftime("%H:%M"))
            h["new"] = h["symbol"] not in seen
            if h["new"]:
                new.append(h["symbol"])
                seen[h["symbol"]] = h["first_seen"]
        ms["seen"], ms["seen_date"] = seen, today
        ms["orb"] = res
        holding = sum(1 for h in res["hits"] if h["holding"])
        log("%s ORB @%s: %d/%d usable broke out (%d still above the range)%s"
            % (m, cutoff.strftime("%H:%M"), len(res["hits"]), res["usable"], holding,
               ("; NEW: " + ", ".join(new[:15]) + (" ..." if len(new) > 15 else "")) if new else ""))
        if m == "NSE" and a.auto_paper:
            try:
                import auto_nse
                auto_nse.process(state, res, log)
            except Exception as e:
                state["errors"].append("auto NSE: %s" % e)
                log("auto NSE failed: %s" % e)
    # keep trader/watchlist.json current for paper.py --stop orb-mid
    hits, have = [], set()
    for m in markets:
        mstate = state["markets"].get(m, {})
        for h in (mstate.get("orb") or mstate.get("intraday") or {}).get("hits", []):
            if h["symbol"] not in have:
                have.add(h["symbol"])
                hits.append(h)
    if hits:
        os.makedirs(S.OUT_DIR, exist_ok=True)
        with open(S.WATCHLIST_FILE, "w", encoding="utf-8") as fh:
            json.dump({"mode": "orb", "market": "+".join(markets), "as_of": now.isoformat(), "hits": hits}, fh, indent=2)
    try:
        snap = paper_snapshot()
        if snap is not None:
            state["paper"] = snap
    except Exception as e:
        state["errors"].append("paper: %s" % e)
        log("paper check failed: %s" % e)
    state["updated"] = now.isoformat()


def next_wake(now, a):
    """When to run next: just after the next 5-minute bar completes, or at tomorrow's ORB time."""
    orb_time = S.at(now, OPEN_HM) + timedelta(minutes=a.or_minutes + 5, seconds=30)
    eod = S.at(now, CLOSE_HM) + timedelta(minutes=6)
    pre_open = S.at(now, OPEN_HM) - timedelta(minutes=15)
    if now.weekday() < 5 and now < pre_open:
        return pre_open, "pre-open daily scan"
    if now.weekday() < 5 and now < orb_time:
        return orb_time, "first opening-range scan"
    if now.weekday() < 5 and now < eod:
        step = max(300, a.interval)
        nxt = now + timedelta(seconds=step)
        nxt = nxt.replace(minute=nxt.minute - nxt.minute % 5, second=30, microsecond=0)
        if nxt <= now:
            nxt += timedelta(minutes=5)
        return min(nxt, eod), "next scan"
    day = now + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return S.at(day, OPEN_HM) - timedelta(minutes=15), "market closed; next session"


def crypto_wake(now, a):
    """Every --interval (min 5 min), 75 s after a 5-minute mark: paper stops get checked, and the
    15-minute scan runs about a minute after each candle closes (scan_crypto.SETTLE_MIN)."""
    nxt = now + timedelta(seconds=max(300, a.interval))
    nxt = nxt.replace(minute=nxt.minute - nxt.minute % 5, second=0, microsecond=0) + timedelta(seconds=75)
    while nxt - now > timedelta(seconds=max(300, a.interval)):
        nxt -= timedelta(minutes=5)
    return nxt if nxt > now else nxt + timedelta(minutes=5)


def heartbeat(state, active, wake):
    """One log line per cycle (every 5 minutes), so the log shows the runner is alive and what it looked at."""
    parts = []
    mk = state.get("markets") or {}
    for m in active:
        ms = mk.get(m) or {}
        if m == "CRYPTO":
            it = ms.get("intraday") or {}
            when = datetime.fromisoformat(it["as_of"]).astimezone(S.IST).strftime("%H:%M") if it.get("as_of") else "-"
            parts.append("CRYPTO %sm candle %s, %d above 4h high" % (
                ms.get("timeframe", 15), when, sum(1 for h in it.get("hits", []) if h.get("setup") == "range_breakout_4h")))
        elif m == "US":
            parts.append("US %s" % (ms.get("status") or "-"))
        elif m in ("NSE", "BSE"):
            orb = ms.get("orb") or {}
            parts.append("%s %s" % (m, ("ORB %d hits" % len(orb.get("hits", []))) if orb.get("as_of", "")[:10] ==
                                    now_ist().date().isoformat() else "closed / waiting"))
        else:
            parts.append(m)
    paper = state.get("paper") or {}
    n_open = len(paper.get("open", [])) if isinstance(paper, dict) else 0
    return "Cycle: %s; %d open paper position%s; next check %s" % (
        "; ".join(parts) or "paused", n_open, "" if n_open == 1 else "s", wake.strftime("%H:%M"))


CONTROL = os.path.join("trader", "live", "control.json")
ALL_MARKETS = ("CRYPTO", "US", "NSE", "BSE", "FNO")


def read_control():
    """Market on/off switches from the dashboard (trader/live/control.json). Missing file = everything on."""
    c = {m: True for m in ALL_MARKETS}
    c["paused"] = False
    try:
        with open(CONTROL, encoding="utf-8") as fh:
            c.update(json.load(fh))
    except Exception:
        pass
    return c


def active_markets(markets, control):
    if control.get("paused"):
        return []
    return [m for m in markets if control.get(m, True)]


def positions_only(state):
    """Paused, or every started market switched off: still watch open paper positions (stops must work)."""
    state["errors"] = []
    snap = paper_snapshot()
    if snap is not None:
        state["paper"] = snap
    state["updated"] = now_ist().isoformat()


COMMANDS = os.path.join("trader", "live", "commands.jsonl")
COMMANDS_DONE = os.path.join("trader", "live", "commands_done.jsonl")


class Restart(Exception):
    pass


def take_commands():
    """Requests from the dashboard (the API appends them to trader/live/commands.jsonl). The runner is the only
    process that writes the paper ledger, so the dashboard asks and the runner does it."""
    if not os.path.exists(COMMANDS):
        return []
    work = COMMANDS + ".work"
    try:
        os.replace(COMMANDS, work)
        with open(work, encoding="utf-8") as fh:
            rows = [json.loads(x) for x in fh if x.strip()]
        os.remove(work)
        return rows
    except Exception as e:
        log("Dashboard commands unreadable: %s" % e)
        return []


def _done(cmd, ok, detail):
    row = dict(cmd)
    row.update({"done_at": now_ist().isoformat(), "ok": ok, "detail": detail})
    try:
        old = []
        if os.path.exists(COMMANDS_DONE):
            with open(COMMANDS_DONE, encoding="utf-8") as fh:
                old = fh.readlines()[-199:]
        with open(COMMANDS_DONE, "w", encoding="utf-8") as fh:
            fh.writelines(old + [json.dumps(row) + "\n"])
    except Exception:
        pass
    log("Dashboard: %s %s -> %s" % (cmd.get("action"), cmd.get("key") or "", detail))


def run_commands(state):
    """Returns True when the dashboard asked for a scan right now. Raises Restart for a restart."""
    import paper as P
    scan_now = False
    for cmd in take_commands():
        act = cmd.get("action")
        try:
            if act in ("close", "close_all"):
                cfg = P.load_config()
                led = P.load_ledger(cfg)
                targets = [p for p in led["open"] if act == "close_all" or p["key"] == cmd.get("key")]
                if not targets:
                    _done(cmd, False, "no such open position")
                    continue
                out = []
                for pos in list(targets):
                    try:
                        px = P.fetch_price(pos["market"], pos["symbol"])[0]
                    except Exception as e:
                        out.append("%s: no price (%s), still open" % (pos["key"], e))
                        continue
                    rec = P.close_position(led, cfg, pos, px, "manual (dashboard)", datetime.now(timezone.utc))
                    out.append("%s closed at %s, P&L %.2f (%+.2fR)" % (pos["key"], px, rec["pnl"], rec["r"]))
                P.save_json(P.LEDGER, led)
                state["paper"] = paper_snapshot()
                _done(cmd, True, "; ".join(out))
            elif act == "run_now":
                scan_now = True
                _done(cmd, True, "scan starting")
            elif act == "restart":
                _done(cmd, True, "restarting")
                raise Restart()
            else:
                _done(cmd, False, "unknown action %r" % act)
        except Restart:
            raise
        except Exception as e:
            _done(cmd, False, "failed: %s" % e)
    return scan_now


def restart_self():
    """Under systemd (TRADER_SERVICE=1) exit and let the service restart us; otherwise start a fresh copy of
    this process in place. Either way new code and settings are loaded."""
    if os.environ.get("TRADER_SERVICE"):
        sys.exit(3)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def notify(state):
    try:
        import alerts
        alerts.notify_cycle(state)
    except Exception:
        pass


def main(argv=None):
    p = argparse.ArgumentParser(description="Live NSE/BSE/crypto scanner loop. Never places an order.")
    p.add_argument("--markets", default="NSE,BSE,CRYPTO")
    p.add_argument("--interval", type=int, default=300, help="seconds between scans in the session (min 300)")
    p.add_argument("--nifty50", action="store_true", help="scan the built-in Nifty 50 instead of the Nifty 500")
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--min-price", type=float, default=20.0)
    p.add_argument("--min-volume", type=int, default=100000)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--once", action="store_true")
    p.add_argument("--auto-paper", action="store_true",
                   help="run the full agent pipeline on new crypto breakouts and take PAPER trades (auto_crypto.py)")
    a = p.parse_args(argv)
    a._tried_download = False
    markets =[m.strip().upper() for m in a.markets.split(",") if m.strip()]
    for m in markets:
        if m not in S.SUFFIX and m not in ("CRYPTO", "US", "FNO"):
            print("Unknown market %s (NSE, BSE, FNO, US or CRYPTO)." % m)
            return 1
    stocks = [m for m in markets if m in S.SUFFIX]
    always = [m for m in markets if m in ("CRYPTO", "US", "FNO")]
    state = load_state()
    state.update({"status": "running", "markets_scanned": markets, "pid": os.getpid()})
    log("live.py started: %s, every %d s in the session%s. Ctrl+C to stop."
        % ("+".join(markets), max(300, a.interval), "; AUTO PAPER trading on breakouts" if a.auto_paper else ""))
    try:
        import alerts
        alerts.send("runner", "Trader runner started: %s (paper)" % "+".join(markets))
    except Exception:
        pass
    last_active = None
    try:
        while True:
            control = read_control()
            active = active_markets(markets, control)
            if active != last_active:
                log("Automation: %s" % ("PAUSED from the dashboard (open positions still watched)" if control.get("paused")
                                        else ("on for " + "+".join(active)) if active
                                        else "every started market is switched off (open positions still watched)"))
                last_active = active
            state["markets_scanned"] = active
            state["markets_started"] = markets
            run_commands(state)
            try:
                if active:
                    cycle(state, a, active)
                else:
                    positions_only(state)
            except Exception as e:
                state.setdefault("errors", []).append(str(e))
                log("cycle failed: %s" % e)
                traceback.print_exc()
            if a.once:
                state["status"] = "stopped (--once)"
                save_state(state)
                break
            if not stocks:
                wake, why = crypto_wake(now_ist(), a), "next check"
            elif state.get("holiday_suspected") == now_ist().date().isoformat() and S.is_session(now_ist()):
                wake, why = now_ist() + timedelta(minutes=30), "no usable data (holiday?); retry"
            else:
                wake, why = next_wake(now_ist(), a)
            if stocks and always:
                cw = crypto_wake(now_ist(), a)
                if cw < wake:
                    wake, why = cw, "next check"
            state["next_run"] = wake.isoformat()
            state["status"] = "running (%s at %s)" % (why, wake.strftime("%a %H:%M"))
            try:
                log(heartbeat(state, active, wake))
            except Exception as e:
                log("heartbeat failed: %s" % e)
            save_state(state)
            print("  ... %s at %s IST" % (why, wake.strftime("%a %d %b %H:%M:%S")), flush=True)
            notify(state)
            while now_ist() < wake:
                time.sleep(min(5, max(1, (wake - now_ist()).total_seconds())))
                if os.path.exists(COMMANDS):
                    now_scan = run_commands(state)
                    save_state(state)
                    if not now_scan:
                        continue
                    if (state["markets"].get("CRYPTO") or {}).get("intraday"):
                        state["markets"]["CRYPTO"]["intraday"]["as_of"] = None  # rescan the last candle
                    break
    except Restart:
        state["status"] = "restarting (dashboard)"
        save_state(state)
        log("live.py restarting (asked from the dashboard).")
        restart_self()
    except KeyboardInterrupt:
        state["status"] = "stopped"
        save_state(state)
        log("live.py stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
