"""
api/_chart.py - "View on chart" for a paper position (owner, 13 Nov 2026).

  GET /api/py/chart/position?key=US:QCOM[&entry_time=...]
      {"candles": [[t, o, h, l, c], ...] (UTC seconds, 5-minute), "pos": {side, entry, stop, risk_stop, target,
       entry_time, exit_time, exit, signal_at, setup, liquidity, reason}, "chart": "US:QCOM", "box": bool,
       "links": [{"name", "url"}], "note"}

The candles are the ones the scanner reads (Yahoo 5-minute for NSE / US / indices, the crypto chart for CRYPTO).
An option position (NFO) is drawn on its underlying index chart without the box: its levels are option premiums.
Broker links open the symbol only: Kite, CoinDCX and TradingView take no drawings in a link.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

router = APIRouter()
INDEX_YAHOO = {"NIFTY": "^NSEI", "NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK"}


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


@router.get("/api/py/chart/position")
def chart_position(key: str, entry_time: str = ""):
    pos, is_open = _find(key, entry_time or None)
    if not pos:
        raise HTTPException(404, "no paper position %s" % key)
    market, sym, chart, box = chart_of(pos)
    et = _iso(pos.get("entry_time"))
    try:
        cs = candles(market, sym, et)
    except Exception as e:
        raise HTTPException(502, "candles for %s: %s" % (chart, str(e)[:200]))
    note = None
    if not box:
        note = ("An option: drawn on %s's chart; its entry / stop / target are option premiums, so no box. "
                "Markers show the signal and the entry." % sym)
    elif pos.get("market") == "CRYPTO":
        note = "Crypto prices are Coinbase (USD), the bot's feed; CoinDCX quotes INR / USDT pairs, a little apart."
    return {"chart": chart, "tf": "5m", "open": is_open, "box": box, "note": note,
            "candles": cs, "links": links(market, sym, pos),
            "pos": {k: pos.get(k) for k in ("key", "market", "symbol", "side", "qty", "entry", "stop", "risk_stop",
                                           "target", "entry_time", "exit_time", "exit", "reason", "setup",
                                           "setup_name", "scanner", "liquidity", "entry_reason", "trailing",
                                           "breakeven", "locked", "trail_k")}
                   | {"signal_at": pos.get("v4_signal_at"), "last": pos.get("last_price")}}
