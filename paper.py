#!/usr/bin/env python3
"""
paper.py - multi-market PAPER trading: NSE, BSE, Nifty/Bank Nifty F&O, US stocks and crypto.

Virtual money only. Nothing here talks to a broker or places a real order.
Stock and crypto prices: Yahoo Finance (free, unofficial, can lag). F&O prices: fno.py
(NSE's option chain when it answers, else a Black-Scholes model from India VIX, marked "model").

Symbols (prefix picks the market; a bare symbol uses "default_market" in config):
    NSE:RELIANCE   BSE:RELIANCE   US:TSLA   CRYPTO:BTC
    NFO:NIFTY-20261103-22800-CE    NFO:BANKNIFTY-20261124-48000-PE    NFO:NIFTY-FUT-20261124

Accounts: NSE, BSE and NFO share one INDIA account (Rs 50,000 by default); US and CRYPTO have their own.

    python paper.py price NSE:RELIANCE NFO:NIFTY-20261103-22800-CE
    python paper.py buy NSE:RELIANCE --stop 1165 --target 2R      # auto-sized to your max loss
    python paper.py buy NSE:KOTAKBANK --stop orb-mid              # stop from the scanner's opening range
    python paper.py buy NFO:NIFTY-20261103-22800-CE --stop 30% --lots 1
    python paper.py check [--watch 60]    # stops / breakeven / targets / flat-by-close
    python paper.py sell NSE:RELIANCE     # close by hand
    python paper.py status                # cash, open positions, today's numbers
    python paper.py journal               # every closed trade + win rate, average R
    python paper.py reset INDIA --yes     # start an account over (INDIA, US, CRYPTO or ALL)

Accounts, limits, charges and square-off times live in trader/paper/config.json (made on first
run; new defaults are merged in). Standard-library Python 3.8+. Nothing to pip install.
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.path.join("trader", "paper")
CONFIG = os.path.join(BASE, "config.json")
LEDGER = os.path.join(BASE, "ledger.json")
WATCHLIST = os.path.join("trader", "watchlist.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
IST = timezone(timedelta(hours=5, minutes=30))

MARKETS = {
    "NSE":    {"suffix": ".NS",  "cur": "Rs", "open": "09:15", "close": "15:30", "fractional": False, "account": "INDIA"},
    "BSE":    {"suffix": ".BO",  "cur": "Rs", "open": "09:15", "close": "15:30", "fractional": False, "account": "INDIA"},
    "NFO":    {"suffix": None,   "cur": "Rs", "open": "09:15", "close": "15:30", "fractional": False, "account": "INDIA"},
    "US":     {"suffix": "",     "cur": "$",  "open": "09:30", "close": "16:00", "fractional": False, "account": "US"},
    "CRYPTO": {"suffix": "-USD", "cur": "$",  "open": None,    "close": None,    "fractional": True,  "account": "CRYPTO"},
}
ACCOUNT_MARKET = {"INDIA": "NSE", "US": "US", "CRYPTO": "CRYPTO"}  # for currency formatting

DEFAULT_CONFIG = {
    "_note": "Paper money only. Edit freely. INDIA is shared by NSE, BSE and NFO (F&O). "
             "US/CRYPTO charge fee_pct per side; INDIA uses india_charges (approximate: check your broker's "
             "brokerage calculator and correct them).",
    "default_market": "NSE",
    "accounts": {
        "INDIA":  {"capital": 50000, "max_loss_per_trade": 500, "max_loss_per_trade_fno": 1500,
                   "max_position_pct": 25, "max_position_pct_fno": 40, "daily_loss_limit": 2500,
                   "max_trades_per_day": 5, "min_reward_risk": 1.0, "flat_by": "15:15",
                   "futures_margin_pct": 12.0, "breakeven_at_r": 1.0, "allow_short": True,
                   "cooldown_losses": 3, "cooldown_minutes": 120, "weekly_loss_x": 3.0, "risk_limits": False, "trade_setups": True},
        "US":     {"capital": 50000, "max_loss_per_trade": 50, "max_position_pct": 25,
                   "daily_loss_limit": 150, "max_trades_per_day": 5, "min_reward_risk": 1.0,
                   "flat_by": "15:55", "fee_pct": 0.0, "breakeven_at_r": None, "allow_short": True,
                   "cooldown_losses": 3, "cooldown_minutes": 120, "weekly_loss_x": 3.0, "risk_limits": False, "trade_setups": True},
        "CRYPTO": {"capital": 1000, "max_loss_per_trade": 10, "max_position_pct": 25,
                   "daily_loss_limit": 30, "max_trades_per_day": 10, "min_reward_risk": 1.0,
                   "flat_by": None, "fee_pct": 0.059, "breakeven_at_r": None, "allow_short": True,
                   "cooldown_losses": 3, "cooldown_minutes": 120, "weekly_loss_x": 3.0, "max_same_side": 3, "risk_limits": False, "trade_setups": True},
        # risk_limits (False while paper testing, the owner's decision of 4 Nov 2026): when True, the daily loss limit,
        # max trades per day and the rulebook guards below block new entries. Turn it on before real money.
        # trade_setups: Scanner v2's setups (the owner's A-B-C-D / playbook / FVG / OB) are paper traded (True) or
        # only recorded (False).
        # Rulebook risk guards (all accounts): after cooldown_losses losing trades in a row, no new entries for
        # cooldown_minutes; a week's net realised loss of weekly_loss_x x daily_loss_limit stops new entries until
        # Monday; CRYPTO: at most max_same_side open positions on one side (alts move with BTC). 0 = off.
        # CRYPTO fee_pct: CoinDCX USDT futures taker 0.05% + 18% GST = 0.059% a side (2 Nov 2026; maker 0.02%).
        # The bot enters and stops out with market orders, so taker. Funding (every 8 h) is not modelled.
    },
    "india_charges": {
        "_note": "Percents of the order value. Brokerage is the smaller of the flat fee and brokerage_pct "
                 "(options: flat only). STT rates as of 1 Apr 2026 (options 0.15%, futures 0.05% on the sell side).",
        "equity_intraday": {"brokerage_flat": 20, "brokerage_pct": 0.03, "stt_sell_pct": 0.025,
                            "exchange_pct": 0.00297, "stamp_buy_pct": 0.003, "gst_pct": 18},
        "options":         {"brokerage_flat": 20, "brokerage_pct": None, "stt_sell_pct": 0.15,
                            "exchange_pct": 0.03503, "stamp_buy_pct": 0.003, "gst_pct": 18},
        "futures":         {"brokerage_flat": 20, "brokerage_pct": 0.03, "stt_sell_pct": 0.05,
                            "exchange_pct": 0.00173, "stamp_buy_pct": 0.002, "gst_pct": 18},
    },
}


class PaperError(Exception):
    pass


# ------------------------------------------------------------------ storage

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp, path)


def load_config():
    if not os.path.exists(CONFIG):
        save_json(CONFIG, DEFAULT_CONFIG)
        print("Made %s with default paper accounts (edit it to change capital and limits)." % CONFIG)
    cfg = load_json(CONFIG, DEFAULT_CONFIG)
    changed = False
    for name, acc in DEFAULT_CONFIG["accounts"].items():
        merged = dict(acc)
        merged.update(cfg.get("accounts", {}).get(name, {}))
        if cfg.get("accounts", {}).get(name) != merged:
            changed = True
        cfg.setdefault("accounts", {})[name] = merged
    crypto = cfg["accounts"].get("CRYPTO", {})
    if not cfg.get("_fees_coindcx") and crypto.get("fee_pct") == 0.1:  # one-time: the old generic 0.1% -> CoinDCX
        crypto["fee_pct"] = DEFAULT_CONFIG["accounts"]["CRYPTO"]["fee_pct"]
        cfg["_fees_coindcx"] = True
        changed = True
    us = cfg["accounts"].get("US", {})
    if not cfg.get("_us_capital_50k") and float(us.get("capital", 0)) == 5000:   # one-time: owner raised US to $50k
        us["capital"] = 50000
        cfg["_us_capital_50k"] = True
        changed = True
    if "india_charges" not in cfg:
        cfg["india_charges"] = DEFAULT_CONFIG["india_charges"]
        changed = True
    if changed:  # write the new defaults (e.g. the INDIA account) into the user's file once
        save_json(CONFIG, cfg)
    return cfg


def load_ledger(cfg):
    led = load_json(LEDGER, {"accounts": {}, "open": [], "closed": []})
    topped = False
    for name, acc in cfg["accounts"].items():
        if name in ACCOUNT_MARKET:
            book = led["accounts"].setdefault(name, {"cash": float(acc["capital"]), "start_capital": float(acc["capital"])})
            # capital changed in the config (Settings): a top-up / withdrawal of the difference, history and P&L kept
            delta = float(acc["capital"]) - float(book["start_capital"])
            if abs(delta) > 1e-9:
                book["cash"] = round(float(book["cash"]) + delta, 6)
                book["start_capital"] = float(acc["capital"])
                topped = True
    if topped and os.path.exists(LEDGER):
        save_json(LEDGER, led)
    return led


def account_of(m):
    return MARKETS[m]["account"]


def acct_cfg(cfg, m):
    return cfg["accounts"][account_of(m)]


def book_of(led, m):
    return led["accounts"][account_of(m)]


# ------------------------------------------------------------------ symbols & time

def parse_symbol(raw, cfg):
    s = raw.strip().upper()
    if ":" in s:
        m, t = s.split(":", 1)
        if m not in MARKETS:
            raise PaperError("unknown market %r (use NSE, BSE, NFO, US or CRYPTO)" % m)
        t = t.replace(".NS", "").replace(".BO", "")
        if m == "CRYPTO":
            t = t.replace("-USDT", "").replace("-USD", "")
        if m == "NFO":
            import fno
            try:
                fno.parse(t)
            except fno.FnoError as e:
                raise PaperError(str(e))
        return m, t
    if s.endswith(".NS"):
        return "NSE", s[:-3]
    if s.endswith(".BO"):
        return "BSE", s[:-3]
    if s.endswith("-USD") or s.endswith("-USDT"):
        return "CRYPTO", s.rsplit("-", 1)[0]
    return cfg.get("default_market", "NSE"), s


def key(m, t):
    return "%s:%s" % (m, t)


def yahoo_symbol(m, t):
    return t + MARKETS[m]["suffix"]


def us_offset(utc):
    """US Eastern offset: DST from the 2nd Sunday of March to the 1st Sunday of November (2 AM local)."""
    y = utc.year
    mar1 = datetime(y, 3, 1, tzinfo=timezone.utc)
    start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7, hours=7)
    nov1 = datetime(y, 11, 1, tzinfo=timezone.utc)
    end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7, hours=6)
    return timedelta(hours=-4) if start <= utc < end else timedelta(hours=-5)


def local_now(m, utc):
    if m in ("NSE", "BSE", "NFO"):
        return utc.astimezone(IST)
    if m == "US":
        return utc.astimezone(timezone(us_offset(utc)))
    return utc


def hm(s):
    h, mm = s.split(":")
    return int(h), int(mm)


def session(m, utc):
    """'open', 'closed' or 'always'. Exchange holidays are not known here."""
    spec = MARKETS[m]
    if spec["open"] is None:
        return "always"
    loc = local_now(m, utc)
    if loc.weekday() >= 5:
        return "closed"
    o = loc.replace(hour=hm(spec["open"])[0], minute=hm(spec["open"])[1], second=0, microsecond=0)
    c = loc.replace(hour=hm(spec["close"])[0], minute=hm(spec["close"])[1], second=0, microsecond=0)
    return "open" if o <= loc < c else "closed"


def past_flat_by(m, acc, utc):
    if not acc.get("flat_by") or MARKETS[m]["open"] is None:
        return False
    loc = local_now(m, utc)
    h, mm = hm(acc["flat_by"])
    return (loc.hour, loc.minute) >= (h, mm)


# ------------------------------------------------------------------ instruments

def kind_of(m, t):
    """equity / options / futures (for charges, lots and margin)."""
    if m != "NFO":
        return "equity"
    import fno
    return "futures" if fno.parse(t)["type"] == "FUT" else "options"


def lot_of(m, t):
    if m != "NFO":
        return 1
    import fno
    return fno.lot_size(t)


# ------------------------------------------------------------------ prices

def fetch_price(m, t):
    """Return (price, quote_time_utc). Raises PaperError."""
    if m == "NFO":
        import fno
        try:
            p, qt, src, extra = fno.quote(t)
            return p, qt
        except fno.FnoError as e:
            raise PaperError(str(e))
        except Exception as e:
            raise PaperError("could not price %s: %s" % (t, e))
    ysym = urllib.parse.quote(yahoo_symbol(m, t), safe="")
    last = None
    for host in ("query2", "query1"):
        url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1m" % (host, ysym)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                doc = json.loads(r.read())
            res = (doc.get("chart") or {}).get("result") or []
            if not res:
                raise PaperError("Yahoo has no data for %s" % yahoo_symbol(m, t))
            meta = res[0].get("meta") or {}
            p = meta.get("regularMarketPrice")
            ts = meta.get("regularMarketTime")
            if p is None:
                closes = [c for c in ((res[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or [] if c]
                if not closes:
                    raise PaperError("no price for %s" % yahoo_symbol(m, t))
                p = closes[-1]
            qt = datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now(timezone.utc)
            return float(p), qt
        except PaperError:
            raise
        except Exception as e:
            last = e
    if m == "CRYPTO":  # cloud servers are sometimes refused by Yahoo: Coinbase's public ticker as a fallback
        try:
            req = urllib.request.Request("https://api.exchange.coinbase.com/products/%s-USD/ticker" % t,
                                         headers={"User-Agent": "trader-bot", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                doc = json.loads(r.read())
            return float(doc["price"]), datetime.now(timezone.utc)
        except Exception as e:
            last = "%s; coinbase: %s" % (last, e)
    raise PaperError("could not fetch %s: %s" % (yahoo_symbol(m, t), last))


def fetch_minutes(m, t):
    """Today's 1-minute candles [(utc, o, h, l, c)], oldest first, or [] (F&O, or no data). Used by check_once to see
    what happened BETWEEN two checks: a stop or target touched and left again in the minutes in between."""
    if m == "NFO":
        return []
    ysym = urllib.parse.quote(yahoo_symbol(m, t), safe="")
    for host in ("query2", "query1"):
        url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1m" % (host, ysym)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                doc = json.loads(r.read())
            res = ((doc.get("chart") or {}).get("result") or [None])[0]
            if not res:
                return []
            q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
            out = []
            for ts, o, h, l, c in zip(res.get("timestamp") or [], q.get("open") or [], q.get("high") or [],
                                      q.get("low") or [], q.get("close") or []):
                if None not in (ts, o, h, l, c):
                    out.append((datetime.fromtimestamp(ts, timezone.utc), float(o), float(h), float(l), float(c)))
            if out:
                return out
        except Exception:
            continue
    if m == "CRYPTO":  # Coinbase public 1-minute candles: [time, low, high, open, close, volume], newest first
        try:
            req = urllib.request.Request("https://api.exchange.coinbase.com/products/%s-USD/candles?granularity=60" % t,
                                         headers={"User-Agent": "trader-bot", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                rows = json.loads(r.read())
            return sorted((datetime.fromtimestamp(x[0], timezone.utc), float(x[3]), float(x[2]), float(x[1]), float(x[4]))
                          for x in rows)
        except Exception:
            return []
    return []


def path_since(pos, bars, now, price):
    """The price path to check for this position: the 1-minute candles since the last check, then the live price.
    The candle that was still forming at the last check is included again (its later part was not seen); before the
    first check, only candles that started after the entry (the entry's own minute may hold prices from before it)."""
    seen, entry = pos.get("last_seen"), pos.get("entry_time")
    try:
        if seen:
            since = datetime.fromisoformat(seen) - timedelta(seconds=60)
        elif entry:
            since = datetime.fromisoformat(entry)
        else:
            since = None
    except ValueError:
        since = None
    path = [b for b in bars if since is not None and since <= b[0] < now]
    # the live price last. It only counts as a gap past the stop when there were no candles to look at and the
    # position was not checked in the last 15 minutes (the old rule); otherwise a resting stop fills at the stop.
    watched = False
    try:
        watched = bool(seen) and (now - datetime.fromisoformat(seen)) <= timedelta(minutes=15)
    except ValueError:
        pass
    path.append((now, price, price, price, price, not bars and not watched))
    return path


# ------------------------------------------------------------------ money

def money(m, x):
    if MARKETS[m]["fractional"] and 0 < abs(x) < 1:
        return "%s%s" % (MARKETS[m]["cur"], "%.4g" % x)
    return "%s%s" % (MARKETS[m]["cur"], format(round(x, 2), ",.2f"))


def fmt_qty(m, q):
    return ("%.6f" % q).rstrip("0").rstrip(".") if MARKETS[m]["fractional"] else str(int(q))


def charges(cfg, m, t, side, value):
    """Cost of one order (buy or sell) of this value."""
    if account_of(m) != "INDIA":
        return value * acct_cfg(cfg, m).get("fee_pct", 0) / 100
    k = kind_of(m, t)
    ch = cfg["india_charges"]["equity_intraday" if k == "equity" else k]
    brokerage = ch["brokerage_flat"]
    if ch.get("brokerage_pct") is not None:
        brokerage = min(brokerage, value * ch["brokerage_pct"] / 100)
    stt = value * ch["stt_sell_pct"] / 100 if side == "sell" else 0.0
    exch = value * ch["exchange_pct"] / 100
    sebi = value * 0.0001 / 100
    stamp = value * ch["stamp_buy_pct"] / 100 if side == "buy" else 0.0
    gst = (brokerage + exch + sebi) * ch["gst_pct"] / 100
    return brokerage + stt + exch + sebi + stamp + gst


def today_closed(led, m, utc):
    d = local_now(m, utc).date().isoformat()
    acc = account_of(m)
    return [c for c in led["closed"] if account_of(c["market"]) == acc and c["exit_date"] == d]


def trades_today(led, m, utc):
    d = local_now(m, utc).date().isoformat()
    acc = account_of(m)
    return [x for x in led["open"] + led["closed"] if account_of(x["market"]) == acc and x["entry_date"] == d]


def held_value(p, price=None):
    """What an open position ties up: its margin (futures) or its market value."""
    if p.get("margin") is not None:
        return p["margin"] + (pnl_of(p, price) if price is not None else 0.0)
    if is_short(p):  # the collateral (entry value) plus the open P&L
        return p["qty"] * p["entry"] + (pnl_of(p, price) if price is not None else 0.0)
    return p["qty"] * (price if price is not None else p["entry"])


def orb_stop(t, which):
    wl = load_json(WATCHLIST, {})
    for h in wl.get("hits", []):
        if h.get("symbol", "").upper() == t and "range_high" in h:
            hi, lo = h["range_high"], h["range_low"]
            return lo if which == "orb-low" else (hi + lo) / 2
    raise PaperError("%s has no opening range in %s (run the scanner first, or give a price)" % (t, WATCHLIST))


def resolve_stop(spec, entry, t, short=False):
    s = str(spec).strip().lower()
    if s in ("orb-mid", "orb-low"):
        return orb_stop(t, s)
    if s.endswith("%"):
        return entry * (1 + float(s[:-1]) / 100) if short else entry * (1 - float(s[:-1]) / 100)
    return float(s)


def resolve_target(spec, entry, stop, short=False):
    s = str(spec).strip().upper()
    if s.endswith("R"):
        return entry + float(s[:-1]) * (entry - stop)  # works both ways: for a short, stop > entry
    if s.endswith("%"):
        return entry * (1 - float(s[:-1]) / 100) if short else entry * (1 + float(s[:-1]) / 100)
    return float(s)


def is_short(p):
    return p.get("side") == "short"


def pnl_of(p, price):
    return ((p["entry"] - price) if is_short(p) else (price - p["entry"])) * p["qty"]


def round_px(m, x, down=True):
    f = math.floor if down else math.ceil
    if m == "CRYPTO":  # 6 significant digits, so SHIB-sized prices keep their precision
        if x <= 0:
            return x
        d = max(2, 5 - int(math.floor(math.log10(x))))
        return f(x * 10 ** d) / 10 ** d
    if m in ("NSE", "BSE", "NFO"):  # NSE tick size 0.05
        return round(f(round(x / 0.05, 6)) * 0.05, 2)
    return f(x * 100) / 100


def close_position(led, cfg, pos, price, reason, utc):
    m = pos["market"]
    book = book_of(led, m)
    fee = charges(cfg, m, pos["symbol"], "buy" if is_short(pos) else "sell", pos["qty"] * price)  # a short buys back
    gross = pnl_of(pos, price)
    if pos.get("margin") is not None:
        book["cash"] += pos["margin"] + gross - fee
    elif is_short(pos):
        book["cash"] += pos["qty"] * pos["entry"] + gross - fee
    else:
        book["cash"] += pos["qty"] * price - fee
    pnl = gross - pos.get("entry_fee", 0) - fee
    risk = abs(pos["entry"] - pos.get("risk_stop", pos["stop"])) * pos["qty"]
    rec = dict(pos)
    rec.update({"exit": round(price, 6), "exit_time": utc.isoformat(),
                "exit_date": local_now(m, utc).date().isoformat(), "exit_fee": round(fee, 4),
                "pnl": round(pnl, 4), "r": round(pnl / risk, 2) if risk > 0 else 0.0, "reason": reason})
    led["open"].remove(pos)
    led["closed"].append(rec)
    print("CLOSED %-16s %s @ %s  (%s)  P&L %s  = %+.2fR  (charges %s)"
          % (pos["key"], fmt_qty(m, pos["qty"]), money(m, price), reason, money(m, pnl), rec["r"],
             money(m, pos.get("entry_fee", 0) + fee)))
    return rec


# ------------------------------------------------------------------ commands

def cmd_price(a, cfg, led):
    now = datetime.now(timezone.utc)
    for raw in a.symbols:
        m, t = parse_symbol(raw, cfg)
        try:
            p, qt = fetch_price(m, t)
            age = (now - qt).total_seconds() / 60
            print("%-28s %14s   %s, quote %s (%s)" % (key(m, t), money(m, p), session(m, now),
                  local_now(m, qt).strftime("%Y-%m-%d %H:%M"), "%.0f min old" % age))
        except PaperError as e:
            print("%-28s %s" % (key(m, t), e))


def rulebook_guards(led, m, acc, now, short):
    """Risk guards from the trading rulebook. They only block NEW entries; exits are never blocked.
    Everything is computed from the ledger, so a restart cannot reset them."""
    name = account_of(m)
    mine = sorted((c for c in led["closed"] if account_of(c["market"]) == name and c.get("exit_time")),
                  key=lambda c: c["exit_time"])
    n, mins = int(acc.get("cooldown_losses") or 0), float(acc.get("cooldown_minutes") or 0)
    if n > 0 and mins > 0 and len(mine) >= n and all(c["pnl"] < 0 for c in mine[-n:]):
        last = datetime.fromisoformat(mine[-1]["exit_time"])
        until = last + timedelta(minutes=mins)
        if now < until:
            raise PaperError("cooldown: %d losing trades in a row for %s, no new entries until %s"
                             % (n, name, local_now(m, until).strftime("%H:%M")))
    wx = float(acc.get("weekly_loss_x") or 0)
    if wx > 0:
        today = local_now(m, now).date()
        monday = (today - timedelta(days=today.weekday())).isoformat()
        week = sum(c["pnl"] for c in mine if c.get("exit_date", "") >= monday)
        if -week >= wx * acc["daily_loss_limit"]:
            raise PaperError("weekly loss limit hit for %s (%s net this week, limit %s): no new entries until Monday"
                             % (name, money(m, -week), money(m, wx * acc["daily_loss_limit"])))
    cap = int(acc.get("max_same_side") or 0)
    if cap > 0:
        same = [p for p in led["open"] if account_of(p["market"]) == name and is_short(p) == short]
        if len(same) >= cap:
            raise PaperError("max %d open %s positions in %s (they move together): %s"
                             % (cap, "short" if short else "long", name, ", ".join(p["key"] for p in same)))


def cmd_buy(a, cfg, led):
    now = datetime.now(timezone.utc)
    m, t = parse_symbol(a.symbol, cfg)
    k = key(m, t)
    acc = acct_cfg(cfg, m)
    book = book_of(led, m)
    force = getattr(a, "force", False)
    short = getattr(a, "side", "long") == "short"
    if short and not acc.get("allow_short"):
        raise PaperError("short selling is not enabled for the %s account (allow_short in config)" % account_of(m))
    kind = kind_of(m, t)
    lot = lot_of(m, t)
    fno_trade = kind != "equity"
    if any(p["key"] == k for p in led["open"]):
        raise PaperError("%s is already open; sell it first" % k)
    sess = session(m, now)
    if sess == "closed" and not force:
        raise PaperError("%s is closed right now (a paper fill at a stale price teaches nothing). "
                         "--force to do it anyway." % m)
    if acc.get("flat_by") and sess == "open" and past_flat_by(m, acc, now) and not force:
        raise PaperError("past your flat-by time (%s): no new intraday entries" % acc["flat_by"])
    if acc.get("risk_limits", False):   # off while paper testing (owner's decision); on before real money
        lost_today = -sum(c["pnl"] for c in today_closed(led, m, now) if c["pnl"] < 0)
        if lost_today >= acc["daily_loss_limit"]:
            raise PaperError("daily loss limit hit for %s (%s lost today of %s): done for the day"
                             % (account_of(m), money(m, lost_today), money(m, acc["daily_loss_limit"])))
        if len(trades_today(led, m, now)) >= acc["max_trades_per_day"]:
            raise PaperError("max %d trades per day reached for %s" % (acc["max_trades_per_day"], account_of(m)))
        rulebook_guards(led, m, acc, now, short)

    if getattr(a, "price", None) is not None:
        entry = float(a.price)
    else:
        entry, qt = fetch_price(m, t)
        if sess == "open" and (now - qt).total_seconds() > 20 * 60:
            print("Note: the quote is %.0f minutes old (holiday, halt, or lagging data)."
                  % ((now - qt).total_seconds() / 60))
    if a.stop is None:
        raise PaperError("a stop is required (price, a percent like 2%, orb-mid or orb-low)")
    stop = round_px(m, resolve_stop(a.stop, entry, t, short), down=not short)
    if not short and stop >= entry:
        raise PaperError("stop %s is not below the entry %s (long position; buy a PE or use --side short for a "
                         "bearish view)" % (money(m, stop), money(m, entry)))
    if short and stop <= entry:
        raise PaperError("stop %s is not above the entry %s (short position)" % (money(m, stop), money(m, entry)))
    target = round_px(m, resolve_target(a.target, entry, stop, short), down=short)
    if (not short and target <= entry) or (short and target >= entry):
        raise PaperError("target %s is on the wrong side of the entry %s" % (money(m, target), money(m, entry)))
    risk_ps = abs(entry - stop)
    rr = abs(target - entry) / risk_ps
    if rr + 1e-9 < acc["min_reward_risk"] and not force:
        raise PaperError("reward:risk %.2f is under your minimum %.2f" % (rr, acc["min_reward_risk"]))

    max_loss = acc.get("max_loss_per_trade_fno", acc["max_loss_per_trade"]) if fno_trade else acc["max_loss_per_trade"]
    pos_pct = acc.get("max_position_pct_fno", acc["max_position_pct"]) if fno_trade else acc["max_position_pct"]
    equity = book["cash"] + sum(held_value(p) for p in led["open"] if account_of(p["market"]) == account_of(m))
    unit_cost = entry * acc.get("futures_margin_pct", 12) / 100 if kind == "futures" else entry
    # charges for one unit, round trip at the stop (the loss case), used in sizing
    open_side, close_side = ("sell", "buy") if short else ("buy", "sell")  # a short sells first (STT), buys back
    fee_unit_stop = (charges(cfg, m, t, open_side, entry * lot) + charges(cfg, m, t, close_side, stop * lot)) / lot
    fee_unit_tgt = (charges(cfg, m, t, open_side, entry * lot) + charges(cfg, m, t, close_side, target * lot)) / lot
    if fee_unit_tgt >= 0.5 * risk_ps and not force:
        raise PaperError("stop too tight: charges (%s a unit round trip) are %.0f%% of the risk (%s a unit). "
                         "Widen the stop or skip the trade." % (money(m, fee_unit_tgt), 100 * fee_unit_tgt / risk_ps,
                                                                money(m, risk_ps)))
    caps = {
        "max loss per trade (%s)" % money(m, max_loss): max_loss / (risk_ps + fee_unit_stop),
        "position cap (%g%% of account)" % pos_pct: equity * pos_pct / 100 / (entry if kind != "futures" else unit_cost),
        "cash" + (" (futures margin %g%%)" % acc.get("futures_margin_pct", 12) if kind == "futures" else ""):
            book["cash"] / (unit_cost + fee_unit_stop),
    }
    limiter = min(caps, key=caps.get)
    q = caps[limiter]
    want = None
    if getattr(a, "lots", None):
        want = float(a.lots) * lot
    elif getattr(a, "qty", None) is not None:
        want = float(a.qty)
    if want is not None:
        if want > q + 1e-9:
            raise PaperError("%s %s breaks a limit: %s allows %s" % (
                "--lots" if getattr(a, "lots", None) else "--qty", a.lots if getattr(a, "lots", None) else a.qty,
                limiter, ("%d lot(s)" % int(q // lot)) if lot > 1 else fmt_qty(m, q)))
        q, limiter = want, "your --lots/--qty"
    if MARKETS[m]["fractional"]:
        q = math.floor(q * 1e6) / 1e6
    else:
        q = math.floor(q / lot) * lot
    if q <= 0:
        one = (risk_ps + fee_unit_stop) * lot
        need = unit_cost * lot
        if lot > 1:
            raise PaperError("0 lots fit: one lot (%d) risks %s at the stop (max loss %s) and ties up %s "
                             "(cash %s). Skip it, or change max_loss_per_trade_fno." % (
                                 lot, money(m, one), money(m, max_loss), money(m, need), money(m, book["cash"])))
        if limiter.startswith("cash"):
            raise PaperError("not enough free cash: %s free in the %s account (open positions tie up the rest)"
                             % (money(m, book["cash"]), account_of(m)))
        raise PaperError("0 units fit: the stop is %s away and your max loss is %s. "
                         "Tighten the stop or skip the trade." % (money(m, risk_ps), money(m, max_loss)))
    full = min(v for k, v in caps.items() if not k.startswith("cash"))
    if want is None and limiter.startswith("cash") and q < 0.25 * full:
        # e.g. four open crypto shorts use the whole account: the fifth would be a dust position that only
        # uses up a "trade of the day" (2 Nov: ADA $0.15, HBAR $0.0001 shorts)
        raise PaperError("not enough free cash: %s free in the %s account buys %s, under a quarter of a normal "
                         "position (%s); skipped until a position closes" % (
                             money(m, book["cash"]), account_of(m), fmt_qty(m, q), fmt_qty(m, full)))
    fee = charges(cfg, m, t, open_side, q * entry)
    margin = round(q * unit_cost, 2) if kind == "futures" else None
    book["cash"] -= (margin if margin is not None else q * entry) + fee
    pos = {"key": k, "market": m, "symbol": t, "qty": q, "entry": round(entry, 6), "stop": stop, "risk_stop": stop,
           "target": target, "entry_fee": round(fee, 4), "entry_time": now.isoformat(),
           "entry_date": local_now(m, now).date().isoformat(), "note": getattr(a, "note", None) or "",
           "last_seen": now.isoformat(), "kind": kind, "side": "short" if short else "long"}
    if lot > 1:
        pos["lots"], pos["lot_size"] = int(q // lot), lot
    if margin is not None:
        pos["margin"] = margin
    led["open"].append(pos)
    print("PAPER %s %s  %s%s @ %s   stop %s   target %s (%.1fR)" % (
        "SHORT" if short else "BUY", k, fmt_qty(m, q), (" (%d lot)" % (q // lot)) if lot > 1 else "", money(m, entry),
        money(m, stop), money(m, target), rr))
    print("  size set by: %s.  Max loss at the stop incl. charges: %s.  %s: %s.  Cash left: %s."
          % (limiter, money(m, (risk_ps + fee_unit_stop) * q), "Margin" if margin is not None else "Position",
             money(m, margin if margin is not None else q * entry), money(m, book["cash"])))
    if acc.get("breakeven_at_r"):
        print("  Breakeven: the stop moves to the entry once price is %gR in profit." % acc["breakeven_at_r"])
    if acc.get("flat_by") and MARKETS[m]["open"]:
        print("  Intraday: `paper.py check` squares it off at %s local time if neither level hits." % acc["flat_by"])
    return pos


def cmd_sell(a, cfg, led):
    now = datetime.now(timezone.utc)
    m, t = parse_symbol(a.symbol, cfg)
    pos = next((p for p in led["open"] if p["key"] == key(m, t)), None)
    if not pos:
        raise PaperError("no open paper position in %s" % key(m, t))
    price = float(a.price) if a.price is not None else fetch_price(m, t)[0]
    close_position(led, cfg, pos, price, "manual", now)


def step_bar(led, cfg, pos, acc, b, now, sh):
    """One candle (utc, o, h, l, c) of the path for an open position: the stop first (when a candle touches both,
    assume the stop: we cannot know the order inside a minute, so the worse case), then the target, then move the
    break-even / trailing stop with the candle's best price for the next candle. Returns True if it closed."""
    m = pos["market"]
    t, o, h, l, c = b[:5]
    live = len(b) > 5                 # the live-price step (b[5]: may it count as a gap?)
    when = t if t < now else now
    stop_hit = (h >= pos["stop"]) if sh else (l <= pos["stop"])
    if stop_hit:
        gapped = b[5] if live else ((o > pos["stop"]) if sh else (o < pos["stop"]))   # opened past it: the open, worse
        fill = o if gapped else pos["stop"]
        why = "trailing stop" if pos.get("trailing") else "breakeven stop" if pos.get("breakeven") else "stop"
        close_position(led, cfg, pos, fill, why if not gapped else why + " (gapped past it)", when)
        return True
    if (l <= pos["target"]) if sh else (h >= pos["target"]):
        # a take-profit is a limit order: it fills at the target, not at a later, better price
        close_position(led, cfg, pos, pos["target"], "target", when)
        return True
    best = l if sh else h
    be = acc.get("breakeven_at_r")
    rs = pos.get("risk_stop", pos["stop"])
    be_hit = (best <= pos["entry"] - be * (rs - pos["entry"])) if (be and sh) else \
             (be and best >= pos["entry"] + be * (pos["entry"] - rs))
    if be and not pos.get("breakeven") and be_hit:
        pos["stop"], pos["breakeven"] = pos["entry"], True
        print("BREAKEVEN %-16s %s reached %gR: stop moved to the entry %s"
              % (pos["key"], money(m, best), be, money(m, pos["entry"])))
    if pos.get("trail_k") and sh:
        # trailing exit for a short (auto_crypto short_exit = trail): break-even once price has fallen
        # trail_arm_r R, then the stop follows trail_k x ATR above the lowest price seen; it never moves up
        pos["peak"] = min(pos.get("peak", pos["entry"]), best)   # for a short, "peak" is the low
        risk = rs - pos["entry"]
        if not pos.get("breakeven") and risk > 0 and pos["peak"] <= pos["entry"] - pos.get("trail_arm_r", 1.0) * risk:
            pos["stop"], pos["breakeven"] = min(pos["stop"], pos["entry"]), True
            print("BREAKEVEN %-16s low %s: stop moved to the entry %s" % (pos["key"], money(m, pos["peak"]),
                                                                        money(m, pos["entry"])))
        if pos.get("breakeven"):
            trail_to = round_px(m, pos["peak"] + pos["trail_k"] * pos["trail_atr"], down=False)
            if trail_to < pos["stop"]:
                pos["stop"], pos["trailing"] = trail_to, True
                print("TRAIL %-16s stop lowered to %s (low %s)" % (pos["key"], money(m, trail_to),
                                                                 money(m, pos["peak"])))
    elif pos.get("trail_k") and not sh:
        # trailing exit (auto_crypto rules v4): break-even once +trail_arm_r is reached, then the stop
        # follows trail_k x ATR under the highest price seen; it never moves down
        pos["peak"] = max(pos.get("peak", pos["entry"]), best)
        risk = pos["entry"] - rs
        if not pos.get("breakeven") and risk > 0 and pos["peak"] >= pos["entry"] + pos.get("trail_arm_r", 1.0) * risk:
            pos["stop"], pos["breakeven"] = max(pos["stop"], pos["entry"]), True
            print("BREAKEVEN %-16s peak %s: stop moved to the entry %s" % (pos["key"], money(m, pos["peak"]),
                                                                         money(m, pos["entry"])))
        if pos.get("breakeven"):
            trail_to = round_px(m, pos["peak"] - pos["trail_k"] * pos["trail_atr"])
            if trail_to > pos["stop"]:
                pos["stop"], pos["trailing"] = trail_to, True
                print("TRAIL %-16s stop raised to %s (peak %s)" % (pos["key"], money(m, trail_to),
                                                                  money(m, pos["peak"])))
    return False


def check_once(cfg, led):
    now = datetime.now(timezone.utc)
    if not led["open"]:
        print("No open paper positions.")
        return 0
    for pos in list(led["open"]):
        m = pos["market"]
        acc = acct_cfg(cfg, m)
        sess = session(m, now)
        try:
            price, qt = fetch_price(m, pos["symbol"])
        except PaperError as e:
            print("%-16s %s" % (pos["key"], e))
            continue
        upnl = pnl_of(pos, price)
        sh = is_short(pos)
        if sess == "closed":
            print("%-16s %s closed; last %s (open P&L %s). Checked again when it opens."
                  % (pos["key"], m, money(m, price), money(m, upnl)))
            continue
        intraday = bool(acc.get("flat_by")) and MARKETS[m]["open"] is not None
        # Walk every 1-minute candle since the last check, then the live price: a stop or target touched between two
        # checks (5 min apart) counts even if price came back by the time we look (owner's report, 5 Nov 2026).
        try:
            bars = fetch_minutes(m, pos["symbol"])
        except Exception:
            bars = []
        path = path_since(pos, bars, now, price)
        pos["last_seen"] = now.isoformat()
        closed = False
        for b in path:
            if step_bar(led, cfg, pos, acc, b, now, sh):
                closed = True
                break
        if closed:
            continue
        if intraday and pos["entry_date"] != local_now(m, now).date().isoformat():
            close_position(led, cfg, pos, price, "carried overnight: missed the flat-by", now)
        elif intraday and past_flat_by(m, acc, now):
            close_position(led, cfg, pos, price, "flat by %s" % acc["flat_by"], now)
        else:
            to_stop = abs(price / pos["stop"] - 1) * 100
            to_tgt = abs(pos["target"] / price - 1) * 100
            print("%-16s %s%s  open P&L %s   %.2f%% from the stop%s, %.2f%% from the target"
                  % (pos["key"], "SHORT " if sh else "", money(m, price), money(m, upnl), to_stop,
                     " (breakeven)" if pos.get("breakeven") else "", to_tgt))
    return len(led["open"])


def cmd_check(a, cfg, led):
    if not a.watch:
        check_once(cfg, led)
        return
    try:
        while True:
            print("--- %s" % datetime.now(IST).strftime("%H:%M:%S IST"))
            left = check_once(cfg, led)
            save_json(LEDGER, led)
            if not left:
                break
            time.sleep(a.watch)
    except KeyboardInterrupt:
        print("Stopped watching.")


def cmd_status(a, cfg, led):
    now = datetime.now(timezone.utc)
    for name, m0 in ACCOUNT_MARKET.items():
        book, acc = led["accounts"][name], cfg["accounts"][name]
        opens = [p for p in led["open"] if account_of(p["market"]) == name]
        closed_all = [c for c in led["closed"] if account_of(c["market"]) == name]
        if not opens and not closed_all and not a.all:
            continue
        held, lines = 0.0, []
        for p in opens:
            try:
                px = fetch_price(p["market"], p["symbol"])[0]
            except PaperError:
                px = p["entry"]
            held += held_value(p, px)
            lines.append("    %-28s %s @ %s  now %s  P&L %s  stop %s%s  target %s"
                         % (p["key"], fmt_qty(p["market"], p["qty"]), money(m0, p["entry"]), money(m0, px),
                            money(m0, pnl_of(p, px)), money(m0, p["stop"]),
                            " (BE)" if p.get("breakeven") else "", money(m0, p["target"])))
        eq = book["cash"] + held
        tc = today_closed(led, m0, now)
        print("%s  equity %s  cash %s  start %s  total %s"
              % (name, money(m0, eq), money(m0, book["cash"]), money(m0, book["start_capital"]),
                 money(m0, eq - book["start_capital"])))
        print("  today: %d trades, closed P&L %s (daily limit -%s)"
              % (len(trades_today(led, m0, now)), money(m0, sum(c["pnl"] for c in tc)), money(m0, acc["daily_loss_limit"])))
        for ln in lines:
            print(ln)
    if not led["open"] and not led["closed"] and not a.all:
        print("No paper trades yet. `paper.py status --all` shows every account.")


def cmd_journal(a, cfg, led):
    closed = led["closed"]
    if a.market:
        want = a.market.upper()
        closed = [c for c in closed if c["market"] == want or account_of(c["market"]) == want]
    if not closed:
        print("No closed paper trades yet.")
        return
    print("%-10s %-30s %8s %12s %12s %12s %7s  %s" % ("date", "symbol", "qty", "entry", "exit", "P&L", "R", "why"))
    for c in closed[-a.last:]:
        m = c["market"]
        print("%-10s %-30s %8s %12s %12s %12s %+6.2fR  %s" % (c["exit_date"], c["key"], fmt_qty(m, c["qty"]),
              money(m, c["entry"]), money(m, c["exit"]), money(m, c["pnl"]), c["r"], c["reason"]))
    print()
    for m in MARKETS:
        cs = [c for c in closed if c["market"] == m]
        if not cs:
            continue
        wins = [c for c in cs if c["pnl"] > 0]
        losses = [c for c in cs if c["pnl"] < 0]
        print("%-6s %3d trades  %d won  %d lost  %d flat  win rate %.0f%%  average %+.2fR  total %s  best %s  worst %s"
              % (m, len(cs), len(wins), len(losses), len(cs) - len(wins) - len(losses), 100 * len(wins) / len(cs),
                 sum(c["r"] for c in cs) / len(cs), money(m, sum(c["pnl"] for c in cs)),
                 money(m, max(c["pnl"] for c in cs)), money(m, min(c["pnl"] for c in cs))))
    if len(closed) < 30:
        print("Under 30 trades: too few to judge a strategy. Keep the journal going.")


def cmd_reset(a, cfg, led):
    if not a.yes:
        raise PaperError("this wipes paper history; add --yes to confirm")
    want = a.market.upper()
    names = list(ACCOUNT_MARKET) if want == "ALL" else [MARKETS[want]["account"] if want in MARKETS else want]
    for name in names:
        if name not in ACCOUNT_MARKET:
            raise PaperError("unknown account %r (INDIA, US, CRYPTO or ALL)" % name)
        led["open"] = [p for p in led["open"] if account_of(p["market"]) != name]
        led["closed"] = [c for c in led["closed"] if account_of(c["market"]) != name]
        cap = float(cfg["accounts"][name]["capital"])
        led["accounts"][name] = {"cash": cap, "start_capital": cap}
        print("Reset the %s paper account to %s." % (name, money(ACCOUNT_MARKET[name], cap)))


def main(argv=None):
    p = argparse.ArgumentParser(description="Multi-market PAPER trading (NSE, BSE, F&O, US, crypto). Virtual money only.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("price"); s.add_argument("symbols", nargs="+")
    s = sub.add_parser("buy")
    s.add_argument("symbol")
    s.add_argument("--stop", help="price, percent (2%%), orb-mid or orb-low")
    s.add_argument("--target", default="2R", help="price, 1R/2R/..., or percent (default 2R)")
    s.add_argument("--qty", help="override the auto size in units (still checked against the limits)")
    s.add_argument("--lots", help="F&O: number of lots (still checked against the limits)")
    s.add_argument("--price", help="fill price instead of the quote (e.g. what your broker app shows)")
    s.add_argument("--note")
    s.add_argument("--force", action="store_true", help="allow outside market hours / below min reward:risk")
    s.add_argument("--side", choices=["long", "short"], default="long", help="short: paper accounts with allow_short (CRYPTO, US, INDIA equity intraday); stop above, target below")
    s = sub.add_parser("sell"); s.add_argument("symbol"); s.add_argument("--price")
    s = sub.add_parser("check"); s.add_argument("--watch", type=int, default=0, help="repeat every N seconds")
    s = sub.add_parser("status"); s.add_argument("--all", action="store_true")
    s = sub.add_parser("journal"); s.add_argument("--market"); s.add_argument("--last", type=int, default=30)
    s = sub.add_parser("reset"); s.add_argument("market"); s.add_argument("--yes", action="store_true")
    a = p.parse_args(argv)
    try:
        cfg = load_config()
        led = load_ledger(cfg)
        {"price": cmd_price, "buy": cmd_buy, "sell": cmd_sell, "check": cmd_check, "status": cmd_status,
         "journal": cmd_journal, "reset": cmd_reset}[a.cmd](a, cfg, led)
        if a.cmd != "price":
            save_json(LEDGER, led)
        return 0
    except PaperError as e:
        print("paper.py: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())


# ------------------------------------------------------------------ Scanner v2 setups: the agents, no broker

def setup_decision(market, symbol, s, news=None, now_iso=None):
    """One of the owner's setups found by Scanner v2 (smc_playbook.owner_setups dict), taken through the agents
    Entry (the candle close), Exit (stop, 2R, costs in R), Budget (size from this account's limits), Risk (costs <=
    0.25R, at least one unit), then the Broker: a paper trade at the live price with that stop and 2R target (the
    owner's decision for paper testing, 4 Nov 2026), or LOG ONLY when the account's trade_setups is off.
    Returns the decision record for decisions.jsonl."""
    rec = {"time": now_iso or datetime.now(IST).isoformat(), "symbol": "%s:%s" % (market, symbol),
           "setup": s["setup"], "scanner_v2": True, "steps": {}, "result": None}
    st = rec["steps"]
    st["1_scanner"] = {"scanner": "v2", "setup": s["setup"], "setup_name": s.get("name"), "side": s["side"],
                       "bar_end": s.get("bar_end"), "price": s["price"], **(s.get("details") or {})}
    st["2_news"] = news if news is not None else "not fetched for stock setups (hundreds a day)"

    def done(result, why):
        rec["result"], rec["why"] = result, why
        return rec

    entry, stop, target, short = s["price"], s.get("stop"), s.get("target_2r"), s["side"] == "short"
    st["3_entry"] = {"side": s["side"], "price_now": entry, "note": "entry = the close of the candle that completed it"}
    risk = ((stop - entry) if short else (entry - stop)) if stop is not None else 0
    if risk <= 0:
        return done("skipped", "price %s is already past the stop %s" % (entry, stop))
    cfg = load_config()
    acc = cfg["accounts"][MARKETS[market]["account"]] if market in MARKETS else cfg["accounts"]["US"]
    units = min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / entry)
    qty = units if market == "CRYPTO" else int(units)
    cost = None
    if market in ("NSE", "BSE"):
        if qty >= 1:
            o, c = ("sell", "buy") if short else ("buy", "sell")
            cost = (charges(cfg, "NSE", symbol, o, qty * entry) + charges(cfg, "NSE", symbol, c, qty * target)) / (qty * risk)
    else:
        cost = (entry + target) * float(acc.get("fee_pct") or 0) / 100 / risk
    st["4_exit"] = {"entry": entry, "stop": stop, "target": target, "r_multiple": 2.0,
                    "stop_pct": round(risk / entry * 100, 3), "fee_r": round(cost, 3) if cost is not None else None}
    st["5_timemachine"] = "n/a (these setups are backtested instead: research_smcp / research_abcd)"
    if qty <= 0 or (market != "CRYPTO" and qty < 1):
        return done("skipped", "0 units fit: the stop is %s away and the max loss is %s" % (round(risk, 6),
                                                                                      acc["max_loss_per_trade"]))
    if cost is not None and cost > 0.25:
        return done("skipped", "fees eat %.2fR of the trade (max 0.25R)" % cost)
    name = s.get("name") or s["setup"]
    if not acc.get("trade_setups", True):
        st["6-8_budget_risk_broker"] = {"verdict": "pass, NOT sent to the broker (trade_setups off)",
                                        "qty": round(qty, 6) if market == "CRYPTO" else qty, "entry": entry,
                                        "stop": stop, "target": target, "max_loss": round(risk * qty, 2)}
        st["9_alerts"] = "no trade, nothing to watch"
        return done("LOG ONLY", "%s: passed the agents; recorded only (trade_setups is off)" % name)
    # paper trade it: paper.py sizes at the live price, keeps the stop / 2R target, and its own checks still apply
    import contextlib
    import io
    led = load_ledger(cfg)
    args = type("A", (), {"symbol": "%s:%s" % (market, symbol), "stop": str(stop), "target": str(target), "qty": None,
                          "price": None, "note": "scanner v2: %s" % name, "force": False,
                          "side": "short" if short else "long"})()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            cmd_buy(args, cfg, led)
        save_json(LEDGER, led)
    except PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    pos = next(p for p in led["open"] if p["key"] == "%s:%s" % (market, symbol))
    st["6-8_budget_risk_broker"] = {"verdict": "PASS, paper %s filled" % ("short" if short else "buy"), "qty": pos["qty"],
                                    "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
                                    "max_loss": round(abs(pos["entry"] - pos["stop"]) * pos["qty"] + pos.get("entry_fee", 0), 2),
                                    "report": buf.getvalue().strip().splitlines()}
    st["9_alerts"] = "live.py checks stop %s / target %s every cycle" % (pos["stop"], pos["target"])
    return done("PAPER SHORT" if short else "PAPER BUY", "%s @ %s, stop %s, target %s (Scanner v2: %s)" % (
        fmt_qty(market, pos["qty"]), pos["entry"], pos["stop"], pos["target"], name))
