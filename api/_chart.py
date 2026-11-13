"""
api/_chart.py - "View on chart" for a paper position (owner, 13 Nov 2026).

  GET /api/py/chart/position?key=US:QCOM[&entry_time=...]   an open or closed paper trade
  GET /api/py/chart/decision?time=...&symbol=US:QCOM          a scanner candidate (skipped / blocked / traded)
      {"candles": [[t, o, h, l, c], ...] (UTC seconds, 5-minute), "pos": {side, entry, stop, risk_stop, target, ...},
       "markers": [{"t", "kind", "text"}], "verdict": {"tone", "title", "lines"}, "chart", "box", "open",
       "links": [{"name", "url"}], "note"}
  The verdict says why a trade won or lost (or why a candidate was skipped) and what price did next: for a closed
  trade the best it went and whether price reached the target after the exit; for a skipped one what the planned
  trade would have done (target or stop first) on the same candles. (owner, 13 Nov 2026)

The candles are the ones the scanner reads (Yahoo 5-minute for NSE / US / indices, the crypto chart for CRYPTO).
An option position (NFO) is drawn on its underlying index chart without the box: its levels are option premiums.
Broker links open the symbol only: Kite, CoinDCX and TradingView take no drawings in a link.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

router = APIRouter()
INDEX_YAHOO = {"NIFTY": "^NSEI", "NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK"}
DECISIONS = os.path.join("trader", "live", "decisions.jsonl")   # relative, like paper.py (the API runs in /opt/trader)


def _iso(s):
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _find(key, entry_time=None):
    import paper as P
    led = P.load_ledger(P.load_config())
    for p in led.get("open", []):
        if p.get("key") == key and (not entry_time or p.get("entry_time") == entry_time):
            return p, True
    for p in reversed(led.get("closed", [])):
        if p.get("key") == key and (not entry_time or p.get("entry_time") == entry_time):
            return p, False
    return None, False


def chart_of(pos):
    """(market, symbol, chart key, box?) to draw: an option is drawn on its underlying index, without the box."""
    m, sym = pos.get("market"), pos.get("symbol", "")
    if m == "NFO":
        under = (pos.get("v4_chart") or "").split(":")[-1] or sym.split("-")[0]
        return "INDEX", under.upper(), "NSE:%s" % under.upper(), False
    if m in ("NSE", "BSE") and sym.upper() in INDEX_YAHOO:
        return "INDEX", sym.upper(), "NSE:%s" % sym.upper(), True
    return m, sym, "%s:%s" % (m, sym), True


def candles(market, sym, since):
    """5-minute candles [(t, o, h, l, c)] from a little before `since` to now."""
    import scan_nse as S
    age = (datetime.now(timezone.utc) - since).days if since else 0
    rng = "5d" if age < 4 else "1mo" if age < 25 else "60d"
    if market == "CRYPTO":
        import scan_crypto as C
        d = C.crypto_chart(sym, rng, "5m")
    elif market == "INDEX":
        d = S.yahoo_chart(INDEX_YAHOO.get(sym, sym), rng, "5m", "")
    else:
        d = S.yahoo_chart(sym, rng, "5m", ".NS" if market == "NSE" else ".BO" if market == "BSE" else "")
    if not d or not d.get("t"):
        return []
    out = [(int(t), o, h, l, c) for t, o, h, l, c in zip(d["t"], d["o"], d["h"], d["l"], d["c"])
           if None not in (o, h, l, c)]
    if since:   # keep about 1.5 sessions before the entry for context
        lo = int((since - timedelta(hours=30)).timestamp())
        out = [r for r in out if r[0] >= lo] or out
    return out


def links(market, sym, pos):
    """Open the symbol on a broker / chart site (no drawings: none of them takes one in a link)."""
    out = []
    if market in ("NSE", "BSE", "INDEX", "NFO"):
        try:
            import kite as K
            k = K.resolve(pos.get("key") if pos.get("market") == "NFO" else "%s:%s" % (
                "NSE" if market == "INDEX" else market, sym))
            seg = {"NFO": "NFO-OPT"}.get(k["exchange"], k["exchange"])
            out.append({"name": "Kite", "url": "https://kite.zerodha.com/chart/ext/ciq/%s/%s/%d" % (
                seg, k["tradingsymbol"], k["token"])})
        except Exception:
            pass
        tv = {"NIFTY": "NSE:NIFTY", "NIFTY50": "NSE:NIFTY", "BANKNIFTY": "NSE:BANKNIFTY"}.get(sym.upper(),
                                                                                           "NSE:%s" % sym.upper())
        out.append({"name": "TradingView", "url": "https://www.tradingview.com/chart/?symbol=%s&interval=5" % tv})
    elif market == "US":
        out.append({"name": "TradingView", "url": "https://www.tradingview.com/chart/?symbol=%s&interval=5" % sym.upper()})
    elif market == "CRYPTO":
        out.append({"name": "TradingView (Coinbase, the bot's prices)",
                    "url": "https://www.tradingview.com/chart/?symbol=COINBASE:%sUSD&interval=5" % sym.upper()})
        out.append({"name": "CoinDCX", "url": "https://coindcx.com/trade/%sUSDT" % sym.upper()})
    return out


def _ts(iso):
    t = _iso(iso)
    return int(t.timestamp()) if t else None


def _hm(ts):
    """A UTC second -> HH:MM IST (the dashboard's clock)."""
    return datetime.fromtimestamp(ts, timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %H:%M")


def _decisions():
    path = DECISIONS
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("time"):
                    out.append(r)
    except FileNotFoundError:
        pass
    return out


def decision_of(pos):
    """The scanner's record of a paper trade: the traded decision for this symbol closest to (and before) its entry."""
    et = _ts(pos.get("entry_time"))
    sym = pos.get("v4_chart") or pos.get("key")
    best = None
    for r in _decisions():
        if r.get("symbol") not in (sym, pos.get("key")) or not str(r.get("result") or "").startswith("PAPER"):
            continue
        t = _ts(r["time"])
        if et is None or t is None or abs(et - t) > 20 * 60:
            continue
        if best is None or abs(et - t) < abs(et - _ts(best["time"])):
            best = r
    return best


def setup_markers(rec):
    """BOS / sweep / signal / trigger markers from a decision record's scanner step."""
    sc = ((rec or {}).get("steps") or {}).get("1_scanner") or {}
    out = []
    for key, kind, text in (("BOS_at", "bos", "BOS"), ("sweep_at", "sweep", "sweep"), ("signal_at", "signal", None),
                            ("primary_closed_at", "info", "primary closed"), ("tapped_at", "info", "zone tap")):
        t = _ts(sc.get(key))
        if t:
            label = text or (sc.get("signal") or "signal")
            out.append({"t": t, "kind": kind, "text": label})
    return out, sc


def setup_line(sc):
    """The setup in one line: BOS -> sweep -> signal -> entry."""
    if not sc:
        return None
    parts = []
    if sc.get("BOS_at"):
        parts.append("BOS %s" % _hm(_ts(sc["BOS_at"])))
    if sc.get("sweep_at"):
        parts.append("sweep %s%s" % (_hm(_ts(sc["sweep_at"])), (" (%s)" % sc["swept_px"]) if sc.get("swept_px") else ""))
    if sc.get("signal_at"):
        parts.append("%s %s" % (sc.get("signal") or "signal", _hm(_ts(sc["signal_at"]))))
    if sc.get("trigger_px"):
        parts.append("trigger %s" % sc["trigger_px"])
    if sc.get("zone"):
        parts.append("%s %s-%s" % (sc["zone"], sc.get("zone_low"), sc.get("zone_high")))
    return "Setup: " + " -> ".join(parts) if parts else (sc.get("liquidity") and "Setup: %s" % sc["liquidity"])


def walk(cs, start, side, entry, stop, target, until=None):
    """Follow a planned trade on the candles from `start` (UTC s): ("target" | "stop" | "open", time, R, best R, best
    time). Stop first when one candle touches both (the worse case, as the backtests do)."""
    risk = abs(entry - stop)
    if not risk:
        return None
    sh = side == "short"
    best, best_t = 0.0, None
    for t, o, h, l, c in cs:
        if t < start or (until and t > until):
            continue
        fav = ((entry - l) if sh else (h - entry)) / risk
        if fav > best:
            best, best_t = fav, t
        if (h >= stop) if sh else (l <= stop):
            return "stop", t, -1.0, round(best, 2), best_t
        if target is not None and ((l <= target) if sh else (h >= target)):
            return "target", t, round(abs(target - entry) / risk, 2), round(best, 2), best_t
    last = [r for r in cs if r[0] >= start and (not until or r[0] <= until)]
    if not last:
        return None
    c = last[-1][4]
    return "open", last[-1][0], round(((entry - c) if sh else (c - entry)) / risk, 2), round(best, 2), best_t


EXIT_WHY = {
    "stop": "price hit the original stop: the move went against the setup before reaching the target",
    "breakeven stop": "price went in favour, the Trade Manager moved the stop to the entry, then price came back to it",
    "trailing stop": "the Trade Manager trailed the stop behind the move and price came back to it",
    "profit lock stop": "the Trade Manager locked part of the profit and price came back to the lock",
    "target": "price reached the target",
    "trade manager: reversal": "the Trade Manager saw a reversal candle near the best price and took the profit",
    "trade manager: no follow-through": "the trade went nowhere for too long, so the Trade Manager closed it",
    "carried overnight": "the trade was still open at the next session (missed the flat-by)",
    "day end": "the session ended with the trade open",
}


def _exit_words(reason):
    r = (reason or "").lower()
    for k, v in EXIT_WHY.items():
        if r.startswith(k) or r.startswith("trade manager: " + k.split(": ")[-1]):
            return v
    if r.startswith("flat by"):
        return "the session's flat-by time closed it (no overnight trades)"
    if r.startswith("time stop"):
        return "the crypto rules' time stop closed it"
    if "gapped" in r:
        return "price opened past the stop"
    return reason or "closed"


def closed_verdict(pos, cs, rec, sc):
    """Why a closed trade won or lost, and what price did after."""
    R = pos.get("r")
    side, entry, rs, tgt = pos.get("side") or "long", pos["entry"], pos.get("risk_stop", pos["stop"]), pos.get("target")
    risk = abs(entry - rs) if rs is not None else 0
    et, xt = _ts(pos.get("entry_time")), _ts(pos.get("exit_time"))
    tone = "good" if (R or 0) > 0.05 else "bad" if (R or 0) < -0.05 else "flat"
    title = "%s %+.2fR: %s" % ("Win" if tone == "good" else "Loss" if tone == "bad" else "Flat", R or 0,
                               pos.get("reason") or "closed")
    lines = ["Why it closed: " + _exit_words(pos.get("reason"))]
    sl = setup_line(sc)
    if sl:
        lines.insert(0, sl)
    if risk and et and xt:
        sh = side == "short"
        inside = [r for r in cs if et <= r[0] <= xt]
        if inside:
            bt, bh = max(((r[0], (entry - r[3]) if sh else (r[2] - entry)) for r in inside), key=lambda x: x[1])
            need = abs(tgt - entry) / risk if tgt else None
            lines.append("Best it went: %+.2fR at %s%s" % (bh / risk, _hm(bt),
                         (" (the target needed %+.2fR)" % need) if need else ""))
        if tgt is not None and pos.get("reason", "").split(" (")[0] != "target":
            reach = next((r[0] for r in cs if r[0] > xt and ((r[3] <= tgt) if sh else (r[2] >= tgt))), None)
            lines.append("After the exit: price reached the target at %s" % _hm(reach) if reach else
                         "After the exit: price did not reach the target on these candles")
        elif tgt is not None:
            further = [r for r in cs if r[0] > xt]
            if further:
                ext = min(r[3] for r in further) if sh else max(r[2] for r in further)
                lines.append("After the target: price went on to %+.2fR" % ((((entry - ext) if sh else (ext - entry)) / risk)))
    for e in (pos.get("tm_log") or [])[-4:]:
        lines.append("Trade Manager %s: %s" % (_hm(_ts(e.get("t"))) if _ts(e.get("t")) else "", e.get("text")))
    return {"tone": tone, "title": title, "lines": lines}


def _base(pos, market, sym, chart, box, cs, is_open):
    note = None
    if not box:
        note = ("An option: drawn on %s's chart; its entry / stop / target are option premiums, so no box. "
                "Markers show the setup, the entry and the exit." % sym)
    elif market == "CRYPTO":
        note = "Crypto prices are Coinbase (USD), the bot's feed; CoinDCX quotes INR / USDT pairs, a little apart."
    return {"chart": chart, "tf": "5m", "open": is_open, "box": box, "note": note, "candles": cs,
            "links": links(market, sym, pos)}


@router.get("/api/py/chart/position")
def chart_position(key: str, entry_time: str = ""):
    pos, is_open = _find(key, entry_time or None)
    if not pos:
        raise HTTPException(404, "no paper position %s" % key)
    market, sym, chart, box = chart_of(pos)
    rec = decision_of(pos)
    marks, sc = setup_markers(rec)
    first = min([m["t"] for m in marks] + [_ts(pos.get("entry_time")) or 0]) or None
    since = datetime.fromtimestamp(first, timezone.utc) if first else _iso(pos.get("entry_time"))
    try:
        cs = candles(market, sym, since)
    except Exception as e:
        raise HTTPException(502, "candles for %s: %s" % (chart, str(e)[:200]))
    side = pos.get("side") or "long"
    et, xt = _ts(pos.get("entry_time")), _ts(pos.get("exit_time"))
    if not any(m["kind"] == "signal" for m in marks) and _ts(pos.get("v4_signal_at")):
        marks.append({"t": _ts(pos.get("v4_signal_at")), "kind": "signal", "text": "signal"})
    if et:
        marks.append({"t": et, "kind": "entry", "text": "short" if side == "short" else "buy"})
    for e in pos.get("tm_log") or []:
        t = _ts(e.get("t"))
        txt = str(e.get("text") or "")
        if t and not txt.startswith("exit at"):
            marks.append({"t": t, "kind": "tm", "text": txt.split(":")[0]})
    if xt:
        marks.append({"t": xt, "kind": "win" if (pos.get("r") or 0) > 0.05 else "loss" if (pos.get("r") or 0) < -0.05
                      else "exit", "text": "exit: %s" % (pos.get("reason") or "")[:40]})
    out = _base(pos, market, sym, chart, box, cs, is_open)
    out["markers"] = sorted(marks, key=lambda m: m["t"])
    if is_open:
        sl = setup_line(sc)
        out["verdict"] = {"tone": "flat", "title": "Open: %s" % (pos.get("setup_name") or "trade"),
                          "lines": [x for x in (sl, pos.get("liquidity") and "Why taken: %s" % pos["liquidity"],
                                                pos.get("entry_reason")) if x]}
    else:
        out["verdict"] = closed_verdict(pos, cs, rec, sc)
    out["pos"] = {k: pos.get(k) for k in ("key", "market", "symbol", "side", "qty", "entry", "stop", "risk_stop",
                                         "target", "entry_time", "exit_time", "exit", "reason", "setup",
                                         "setup_name", "scanner", "liquidity", "entry_reason", "trailing",
                                         "breakeven", "locked", "trail_k", "r", "pnl", "mfe_r", "mae_r")} \
        | {"signal_at": pos.get("v4_signal_at"), "last": pos.get("last_price")}
    return out


def _plan(rec):
    """Entry / stop / target the agents planned for a candidate, from whichever step recorded them."""
    st = rec.get("steps") or {}
    sc = st.get("1_scanner") or {}
    plan = {"side": sc.get("side") or "long"}
    for step in ("6-8_budget_risk_broker", "4_exit", "3_entry"):
        d = st.get(step)
        if isinstance(d, dict):
            for k in ("entry", "stop", "target"):
                if plan.get(k) is None and d.get(k) is not None:
                    plan[k] = d[k]
            if plan.get("entry") is None and d.get("price_now") is not None:
                plan["entry"] = d["price_now"]
    if plan.get("entry") is None:
        plan["entry"] = sc.get("price")
    return plan, sc


SKIP_KIND = [("past the stop", "price had already moved past the stop when the agents saw it"),
             ("0 units fit", "the stop was too far for the max loss per trade"),
             ("fees eat", "costs would have eaten too much of the reward"),
             ("unticked", "this setup type is switched off in Settings"),
             ("runs Scanner", "the account runs a different scanner version"),
             ("wait for the open trade", "one trade at a time per chart: another trade was still open"),
             ("no fresh confirmed signal", "the signal was not fresh after the last exit (v4)"),
             ("secondary needs", "a secondary trade needs a closed primary and a later zone tap (v4)"),
             ("reward", "the reward : risk was below the account's minimum"),
             ("R:R", "the reward : risk was below the account's minimum"),
             ("not enough free cash", "the paper account had no free cash for it"),
             ("daily", "a daily risk limit was reached"), ("only on", "F&O trades only these underlyings")]


@router.get("/api/py/chart/decision")
def chart_decision(time: str, symbol: str):
    rec = next((r for r in reversed(_decisions()) if r.get("time") == time and r.get("symbol") == symbol), None)
    if not rec:
        raise HTTPException(404, "no decision %s at %s" % (symbol, time))
    market, sym = symbol.split(":", 1) if ":" in symbol else ("US", symbol)
    pos = {"key": symbol, "market": market, "symbol": sym}
    m2, s2, chart, box = chart_of(pos)
    plan, sc = _plan(rec)
    marks, _ = setup_markers(rec)
    bar = _ts(sc.get("bar_end")) or _ts(rec["time"])
    first = min([m["t"] for m in marks] + [bar or 0]) or None
    try:
        cs = candles(m2, s2, datetime.fromtimestamp(first, timezone.utc) if first else None)
    except Exception as e:
        raise HTTPException(502, "candles for %s: %s" % (chart, str(e)[:200]))
    res = str(rec.get("result") or "")
    traded = res.startswith("PAPER")
    if bar:
        marks.append({"t": bar, "kind": "entry" if traded else "skip",
                      "text": ("short" if plan["side"] == "short" else "buy") if traded else res or "candidate"})
    lines = []
    sl = setup_line(sc)
    if sl:
        lines.append(sl)
    why = rec.get("why") or ""
    plain = next((v for k, v in SKIP_KIND if k.lower() in why.lower()), None)
    lines.append("Agents said: %s" % why if why else "No reason recorded")
    if plain and not traded:
        lines.append("In short: %s" % plain)
    e, s_, t_ = plan.get("entry"), plan.get("stop"), plan.get("target")
    if e is not None and s_ is not None and bar:
        w = walk(cs, bar + 1, plan["side"], e, s_, t_, until=bar + 24 * 3600)
        if w:
            how, at, r, best, bt = w
            if how == "target":
                lines.append("If taken: the target came first at %s (%+.2fR)" % (_hm(at), r))
            elif how == "stop":
                lines.append("If taken: the stop came first at %s (-1R; best before it %+.2fR)" % (_hm(at), best))
            else:
                lines.append("If taken: neither stop nor target yet; %+.2fR at the last candle (best %+.2fR)" % (r, best))
            if not traded:
                lines.append("So skipping it %s" % ("missed a winner" if how == "target" else "saved a loss"
                                                    if how == "stop" else "has not mattered yet"))
            marks.append({"t": at, "kind": "win" if how == "target" else "loss" if how == "stop" else "exit",
                          "text": "would hit target" if how == "target" else "would hit stop" if how == "stop" else "still open"})
    rr = (abs(t_ - e) / abs(e - s_)) if (e is not None and s_ is not None and t_ is not None and e != s_) else None
    out = _base(pos, m2, s2, chart, box and e is not None and s_ is not None, cs, False)
    out["markers"] = sorted(marks, key=lambda m: m["t"])
    out["verdict"] = {"tone": "good" if traded else "bad" if res == "blocked" else "flat",
                      "title": "%s: %s" % (res or "candidate", sc.get("setup_name") or rec.get("setup") or ""),
                      "lines": lines}
    exit_t = next((m["t"] for m in out["markers"] if m["kind"] in ("win", "loss")), None)
    out["pos"] = {"key": symbol, "market": market, "symbol": sym, "side": plan["side"], "entry": e, "stop": s_,
                  "risk_stop": s_, "target": t_, "entry_time": datetime.fromtimestamp(bar, timezone.utc).isoformat()
                  if bar else None, "exit_time": datetime.fromtimestamp(exit_t, timezone.utc).isoformat() if exit_t else None,
                  "setup_name": sc.get("setup_name") or rec.get("setup"), "liquidity": sc.get("liquidity"),
                  "reason": res, "rr": round(rr, 2) if rr else None, "planned": True}
    return out
