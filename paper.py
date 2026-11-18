#!/usr/bin/env python3
"""
paper.py - multi-market PAPER trading: NSE, BSE, Nifty/Bank Nifty F&O, US stocks and crypto.

Virtual money only. Nothing here talks to a broker or places a real order.
Stock and crypto prices: Yahoo Finance (free, unofficial, can lag). F&O prices: fno.py
(NSE's option chain when it answers, else a Black-Scholes model from India VIX, marked "model").

Symbols (prefix picks the market; a bare symbol uses "default_market" in config):
    NSE:RELIANCE   BSE:RELIANCE   US:TSLA   CRYPTO:BTC
    NFO:NIFTY-20261103-22800-CE    NFO:BANKNIFTY-20261124-48000-PE    NFO:NIFTY-FUT-20261124

Accounts: NSE and BSE share the INDIA account (Rs 50,000); NFO (F&O) has its own FNO account (Rs 1,00,000, owner
12 Nov 2026); US and CRYPTO have their own.

    python paper.py price NSE:RELIANCE NFO:NIFTY-20261103-22800-CE
    python paper.py buy NSE:RELIANCE --stop 1165 --target 2R      # auto-sized to your max loss
    python paper.py buy NSE:KOTAKBANK --stop orb-mid              # stop from the scanner's opening range
    python paper.py buy NFO:NIFTY-20261103-22800-CE --stop 30% --lots 1
    python paper.py check [--watch 60]    # stops / breakeven / targets / flat-by-close
    python paper.py sell NSE:RELIANCE     # close by hand
    python paper.py status                # cash, open positions, today's numbers
    python paper.py journal               # every closed trade + win rate, average R
    python paper.py reset INDIA --yes     # start an account over (INDIA, FNO, US, CRYPTO or ALL)

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
    "NFO":    {"suffix": None,   "cur": "Rs", "open": "09:15", "close": "15:30", "fractional": False, "account": "FNO"},
    # US F&O (owner, 13 Nov 2026): QQQ / SPY options, OCC symbols (us_options.py), New York hours, own account
    "USOPT":  {"suffix": None,   "cur": "$",  "open": "09:30", "close": "16:00", "fractional": False, "account": "USFNO"},
    "US":     {"suffix": "",     "cur": "$",  "open": "09:30", "close": "16:00", "fractional": False, "account": "US"},
    "CRYPTO": {"suffix": "-USD", "cur": "$",  "open": None,    "close": None,    "fractional": True,  "account": "CRYPTO"},
}
# the Scanner version an account runs when its config does not say (Settings > Risk limits): the owner trades v4
DEFAULT_SCANNER = "v4"
ACCOUNT_MARKET = {"INDIA": "NSE", "FNO": "NFO", "US": "US", "USFNO": "USOPT", "CRYPTO": "CRYPTO"}  # currency formatting
INDIA_ACCOUNTS = ("INDIA", "FNO")   # Indian charges (india_charges), not fee_pct

# The switches every account starts with (scanner, rulebook guards, Trade Manager); each account below adds or
# overrides its own money and market settings. The comments under "accounts" explain the keys.
COMMON_ACCOUNT = {
    "max_trades_per_day": 5, "min_reward_risk": 1.0, "cooldown_losses": 3, "cooldown_minutes": 120,
    "weekly_loss_x": 3.0, "risk_limits": False, "trade_setups": True, "scanner_version": DEFAULT_SCANNER,
    "v4_setups": ["v4_primary_long", "v4_primary_short", "v4_secondary_long", "v4_secondary_short"],
    "v5_setups": ["v5_level_long", "v5_level_short"], "v5_constant": 0.146, "v5_move": "swing", "v5_target": "leg",
    "trade_manager": True, "tm_be_r": 1.0, "tm_lock_at": 0.0, "tm_lock_keep": 0.5, "tm_reversal": False,
    "tm_rev_min_r": 1.0, "tm_stale_min": 0, "tm_candle_min": 5, "tm_trail": True, "tm_trail_step": 1.0,
    "tm_trail_gap": 1.0,
}


def _account(**own):
    """An account's defaults: COMMON_ACCOUNT (its own copy: lists are never shared) with the account's settings."""
    acc = json.loads(json.dumps(COMMON_ACCOUNT))
    acc.update(own)
    return acc


DEFAULT_CONFIG = {
    "_note": "Paper money only. Edit freely. INDIA = NSE / BSE stocks, FNO = NFO (index options / futures). "
             "US/CRYPTO charge fee_pct per side; INDIA uses india_charges (approximate: check your broker's "
             "brokerage calculator and correct them).",
    "default_market": "NSE",
    "accounts": {
        # intraday_leverage (owner, 14 Nov 2026: "margin k according trade lo"): an intraday stock trade ties up
        # only qty x price / leverage of cash (the broker's intraday margin: SEBI allows at most 5x on Indian cash
        # equity, FINRA 4x intraday in the US). The risk per trade stays max_loss_per_trade; 1 = no leverage.
        "INDIA":  _account(capital=100000, max_loss_per_trade=3000, max_loss_per_trade_fno=3000, intraday_leverage=5,
                           max_position_pct=25, max_position_pct_fno=40, daily_loss_limit=9000, flat_by="15:15",
                           futures_margin_pct=12.0, breakeven_at_r=1.0, allow_short=True),
        # FNO (owner, 12 Nov 2026): its own Rs 1,00,000 budget, apart from the Rs 50,000 INDIA stock account; F&O only
        # on Nifty 50 and Bank Nifty (index ATM options), no stock options. Strategy switches are copied from INDIA
        # once when the account is made, then set on their own (Settings > F&O).
        "FNO":    _account(capital=100000, max_loss_per_trade=3000, max_loss_per_trade_fno=3000, max_position_pct=40,
                           max_position_pct_fno=40, daily_loss_limit=9000, flat_by="15:15", futures_margin_pct=12.0,
                           breakeven_at_r=1.0, allow_short=False, fno_stock_options=False,
                           fno_underlyings=["NIFTY", "BANKNIFTY"]),
        # USFNO (owner, 13 Nov 2026): US F&O, its own budget, only QQQ / SPY / DIA ATM weekly options (us_options.py);
        # strategy switches copied from US once when the account is made. fee_pct 0.5 per side stands for the
        # contract fees and the bid / ask spread (the paper fill is the quote midpoint)
        "USFNO":  _account(capital=1200, max_loss_per_trade=36, max_loss_per_trade_fno=36, max_position_pct=40,
                           max_position_pct_fno=40, daily_loss_limit=108, flat_by="15:50", fee_pct=0.5,
                           breakeven_at_r=1.0, allow_short=False, usopt_underlyings=["QQQ", "SPY", "DIA"]),
        "US":     _account(capital=1000, max_loss_per_trade=30, max_position_pct=25, intraday_leverage=4,
                           daily_loss_limit=90, flat_by="15:55", fee_pct=0.0, breakeven_at_r=None, allow_short=True),
        "CRYPTO": _account(capital=1000, max_loss_per_trade=30, max_position_pct=25, intraday_leverage=5,
                           daily_loss_limit=90, max_trades_per_day=10, flat_by=None, fee_pct=0.059, breakeven_at_r=None,
                           allow_short=True, max_same_side=3, tm_candle_min=15),
        # Trade Manager: ONE set per account, for every scanner's trades (owner, 13 Nov 2026). Defaults = the owner's
        # v4 rule: stop to the entry at +tm_be_r R, then (tm_trail) every tm_trail_step R the stop sits tm_trail_gap R
        # behind the best R; the exits below are off (0 / False) by default. Not the crypto trailing exits (trail_k).
        # trade_manager (owner, 7 Nov 2026: "agents should think and react"): stop to the entry at +tm_be_r R; once price has covered
        # tm_lock_at of the way to the target, the stop locks tm_lock_keep of that way; after +tm_rev_min_r R a
        # reversal candle near the high (bearish engulfing / long upper-wick rejection on tm_candle_min candles)
        # takes the profit; a trade that has gone nowhere after tm_stale_min minutes (best < 0.5R, now within
        # 0.3R of the entry) is closed. Every trade records how far it went for and against (mfe_r / mae_r).
        # risk_limits (False while paper testing, the owner's decision of 4 Nov 2026): when True, the daily loss limit,
        # max trades per day and the rulebook guards below block new entries. Turn it on before real money.
        # trade_setups: the Scanner's setups (v4, v3 or v2, per scanner_version) are paper traded (True) or
        # only recorded (False).
        # scanner_version: "v4" (the owner's revised v4 PDF, 11 Nov: primary, then a sequential OB/FVG secondary), "v3"
        # (the 5 Nov workflow: sweep reversal + FVG/OB retest) or "v2" (A-B-C-D, playbook, FVG/OB). Never mixed: the
        # scanner looks for one version's setups and the broker skips the others'.
        # Switch it per account from Settings > Risk limits; the next candle uses it.
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


# the strategy switches FNO starts with: INDIA's, so F&O keeps running the Scanner version it ran before the split
FNO_FROM_INDIA = ("scanner_version", "v4_setups", "v5_setups", "v5_constant", "v5_move", "v5_target", "trade_setups",
                  "risk_limits", "trade_manager", "tm_be_r", "tm_trail", "tm_trail_step", "tm_trail_gap", "tm_lock_at",
                  "tm_lock_keep", "tm_reversal",
                  "tm_rev_min_r", "tm_stale_min", "tm_candle_min", "max_loss_per_trade_fno", "futures_margin_pct",
                  "flat_by", "cooldown_losses", "cooldown_minutes", "weekly_loss_x")


def tm_one_set(acc):
    """Fold an account's two Trade Managers (v4: trailing only, v4_*; others: tm_*) into one set, keeping what its
    trades ran with: on Scanner v4 the v4 trailing (and the other exits off); otherwise the tm_* exits (no trailing)."""
    v4 = acc.get("scanner_version") == "v4"
    if v4:
        acc["tm_be_r"] = acc.get("v4_be_r", 1.0)
        acc["tm_trail"] = bool(acc.get("v4_trail", True))
        acc["tm_lock_at"], acc["tm_reversal"], acc["tm_stale_min"] = 0.0, False, 0
        acc["trade_manager"] = True
    else:
        acc["tm_trail"] = False
    acc["tm_trail_step"] = acc.get("v4_trail_step", 1.0)
    acc["tm_trail_gap"] = acc.get("v4_trail_gap", 1.0)
    for k in ("v4_trail", "v4_be_r", "v4_trail_step", "v4_trail_gap"):
        acc.pop(k, None)


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


# The owner's budget of 17 Nov 2026: Rs 1 lakh per Indian account, $1,000 per US / crypto account ($1,200 for US
# options); max loss per trade 3% of it, the daily loss limit 3 trades (9%). Applied once to the live config, and
# once to the ledger: every book restarts at its budget (cash = budget - what open positions tie up), the old trades
# stay in the ledger as history ("purana data 0 kardo, sirf data ledger m rehne do").
BUDGET_1117 = {"INDIA": 100000, "FNO": 100000, "US": 1000, "USFNO": 1200, "CRYPTO": 1000}


def budget_limits(capital):
    # max_loss_per_trade_fno is what an option / futures trade is sized by (Bank Nifty's lot needs ~Rs 2,600)
    return {"capital": capital, "max_loss_per_trade": round(capital * 0.03, 2),
            "max_loss_per_trade_fno": round(capital * 0.03, 2), "daily_loss_limit": round(capital * 0.09, 2)}


# the one-time config changes below; a NEW config already holds their results (DEFAULT_CONFIG), so it starts with
# them marked done (a fresh install ran _tm_global and lost the default trailing stop on every account)
ONE_TIME_FLAGS = ("_crypto_lev_1117", "_budget_1117", "_tm_global", "_usopt_dia", "_fees_coindcx")


def load_config():
    if not os.path.exists(CONFIG):
        save_json(CONFIG, dict(DEFAULT_CONFIG, **{f: True for f in ONE_TIME_FLAGS}))
        print("Made %s with default paper accounts (edit it to change capital and limits)." % CONFIG)
    cfg = load_json(CONFIG, DEFAULT_CONFIG)
    changed = False
    accs = cfg.setdefault("accounts", {})
    if "FNO" not in accs:  # one-time (owner, 12 Nov 2026): F&O gets its own account; INDIA = stocks, Rs 50,000
        fno = dict(DEFAULT_CONFIG["accounts"]["FNO"])
        india = accs.get("INDIA") or {}
        for k in FNO_FROM_INDIA:
            if k in india:
                fno[k] = india[k]
        accs["FNO"] = fno
        if india:
            india["capital"] = 50000
            for k in ("fno_underlyings", "fno_stock_options"):
                india.pop(k, None)
        changed = True
    if not cfg.get("_crypto_lev_1117") and "CRYPTO" in accs:  # one-time (owner, 17 Nov 2026): crypto on 5x margin
        accs["CRYPTO"].setdefault("intraday_leverage", 5)
        cfg["_crypto_lev_1117"] = changed = True
    if not cfg.get("_budget_1117"):  # one-time (owner, 17 Nov 2026): see BUDGET_1117
        for name, cap in BUDGET_1117.items():
            if name in accs:
                accs[name].update(budget_limits(cap))
        cfg["_budget_1117"] = changed = True
    if not cfg.get("_tm_global"):   # one-time (owner, 13 Nov 2026): one Trade Manager per account, every scanner
        for acc in accs.values():
            tm_one_set(acc)
        cfg["_tm_global"] = changed = True
    usf_old = accs.get("USFNO")
    if usf_old and "DIA" not in (usf_old.get("usopt_underlyings") or []) and not cfg.get("_usopt_dia"):
        usf_old["usopt_underlyings"] = list(usf_old.get("usopt_underlyings") or []) + ["DIA"]   # one-time: the Dow
        cfg["_usopt_dia"] = changed = True
    if "USFNO" not in accs:   # one-time (owner, 13 Nov 2026): US F&O gets its own account, US's scanner switches
        usf = dict(DEFAULT_CONFIG["accounts"]["USFNO"])
        us = accs.get("US") or {}
        for k in FNO_FROM_INDIA:
            if k in us and k not in ("max_loss_per_trade_fno", "futures_margin_pct", "flat_by"):
                usf[k] = us[k]
        accs["USFNO"] = usf
        changed = True
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
    if "india_charges" not in cfg:
        cfg["india_charges"] = DEFAULT_CONFIG["india_charges"]
        changed = True
    if changed:  # write the new defaults (e.g. the INDIA account) into the user's file once
        save_json(CONFIG, cfg)
    return cfg


def load_ledger(cfg):
    led = load_json(LEDGER, {"accounts": {}, "open": [], "closed": []})
    topped = split_fno(led, cfg)
    topped = budget_reset(led, cfg) or topped
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


def budget_reset(led, cfg):
    """One-time (owner, 17 Nov 2026): every book restarts at its configured budget; open positions stay open and
    keep the money they tie up (margin, or the entry value); closed trades stay as history. True if it ran."""
    if led.get("_budget_1117") or not cfg.get("_budget_1117"):
        return False
    books = led.setdefault("accounts", {})
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for name, acc in cfg.get("accounts", {}).items():
        if name not in ACCOUNT_MARKET:
            continue
        cap = float(acc["capital"])
        tied = sum((p["margin"] if p.get("margin") is not None else p["qty"] * p["entry"])
                   for p in led.get("open", []) if MARKETS.get(p.get("market"), {}).get("account") == name)
        old = books.get(name) or {}
        books[name] = {"cash": round(cap - tied, 6), "start_capital": cap,
                       "budget_reset": {"at": at, "old_cash": old.get("cash"), "old_start": old.get("start_capital"),
                                        "tied": round(tied, 4)}}
    led["_budget_1117"] = at
    return True


def split_fno(led, cfg):
    """One-time (owner, 12 Nov 2026): F&O moves out of INDIA into its own FNO book. Each book's cash stays
    start + realised P&L - money tied in open positions: the NFO trades' realised P&L and the cash their open
    positions tie up move from INDIA to FNO. Returns True if the ledger changed."""
    books = led.setdefault("accounts", {})
    if "FNO" in books or "INDIA" not in books or "FNO" not in cfg.get("accounts", {}):
        return False
    cap = float(cfg["accounts"]["FNO"]["capital"])
    realised = sum(float(c.get("pnl") or 0) for c in led.get("closed", []) if c.get("market") == "NFO")
    tied = sum((p["margin"] if p.get("margin") is not None else p["qty"] * p["entry"]) + float(p.get("entry_fee") or 0)
               for p in led.get("open", []) if p.get("market") == "NFO")
    books["INDIA"]["cash"] = round(float(books["INDIA"]["cash"]) - realised + tied, 6)
    books["FNO"] = {"cash": round(cap + realised - tied, 6), "start_capital": cap,
                    "split_from_india": {"realised": round(realised, 4), "tied": round(tied, 4)}}
    return True


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
            raise PaperError("unknown market %r (use NSE, BSE, NFO, US, USOPT or CRYPTO)" % m)
        t = t.replace(".NS", "").replace(".BO", "")
        if m == "CRYPTO":
            t = t.replace("-USDT", "").replace("-USD", "")
        if m == "NFO":
            import fno
            try:
                fno.parse(t)
            except fno.FnoError as e:
                raise PaperError(str(e))
        if m == "USOPT":
            import us_options
            try:
                us_options.parse(t)
            except us_options.NoOption as e:
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
    if m in ("US", "USOPT"):
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
    if m == "USOPT":
        return "options"
    if m != "NFO":
        return "equity"
    import fno
    return "futures" if fno.parse(t)["type"] == "FUT" else "options"


def lot_of(m, t):
    if m == "USOPT":
        return 100                       # one US equity / ETF option contract = 100 shares
    if m != "NFO":
        return 1
    k = kite_mod()
    if k:                                # the exchange's own lot size (stocks and indices)
        try:
            return k.resolve(key(m, t))["lot"]
        except Exception:
            pass
    import fno
    return fno.lot_size(t)


# ------------------------------------------------------------------ prices

def kite_mod():
    """kite.py when Zerodha is connected today (Indian market data), else None. Data only: it cannot trade."""
    try:
        import kite
        return kite if kite.connected() else None
    except Exception:
        return None


def kite_price(m, t):
    """(price, time) for NSE / BSE / NFO from Zerodha: the live tick stream first, then a Kite quote. None if
    Zerodha is not connected or does not know the instrument."""
    if m not in ("NSE", "BSE", "NFO"):
        return None
    k = kite_mod()
    if not k:
        return None
    tick = k.tick_price(key(m, t))
    if tick:
        return tick
    try:
        return k.ltp(key(m, t))
    except Exception:
        return None


def _newest_quote(res):
    """(price, time) from one Yahoo chart result: the newer of meta.regularMarketPrice (at regularMarketTime) and
    the last 1-minute close (at its candle's end). None if neither exists."""
    meta = res.get("meta") or {}
    cands = []
    if meta.get("regularMarketPrice") is not None:
        ts = meta.get("regularMarketTime")
        cands.append((datetime.fromtimestamp(ts, timezone.utc) if ts else None, float(meta["regularMarketPrice"])))
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    for ts, c in reversed(list(zip(res.get("timestamp") or [], q.get("close") or []))):
        if c is not None and ts is not None:
            cands.append((datetime.fromtimestamp(ts, timezone.utc) + timedelta(minutes=1), float(c)))
            break
    if not cands:
        return None
    now = datetime.now(timezone.utc)
    dated = [(min(t, now), p) for t, p in cands if t is not None]
    if dated:
        t, p = max(dated, key=lambda x: x[0])
        return p, t
    return cands[0][1], now


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                        "dec"), 1)}


def _nasdaq_quote(t, opener=None):
    """(price, trade time UTC) from Nasdaq's public quote API (last sale; no key), or None. Tries stock, then ETF."""
    import re
    opener = opener or urllib.request.urlopen
    for cls in ("stocks", "etf"):
        url = "https://api.nasdaq.com/api/quote/%s/info?assetclass=%s" % (urllib.parse.quote(t), cls)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                                                       "Origin": "https://www.nasdaq.com",
                                                       "Referer": "https://www.nasdaq.com/"})
            with opener(req, timeout=8) as r:
                doc = json.loads(r.read())
            pd = ((doc or {}).get("data") or {}).get("primaryData") or {}
            px = str(pd.get("lastSalePrice") or "").replace("$", "").replace(",", "").strip()
            if not px:
                continue
            ts = str(pd.get("lastTradeTimestamp") or "")
            mt = re.search(r"([A-Za-z]{3})\w*\.? (\d{1,2}), (\d{4}),? (\d{1,2}):(\d{2}) ?([AP]M)", ts)
            if not mt:
                return float(px), None
            mon, day, yr, hh, mm, ap = mt.groups()
            h = int(hh) % 12 + (12 if ap.upper() == "PM" else 0)
            local = datetime(int(yr), _MONTHS[mon.lower()], int(day), h, int(mm), tzinfo=timezone.utc)
            utc = local - us_offset(local + timedelta(hours=5))     # ET -> UTC
            return float(px), utc
        except Exception:
            continue
    return None


def _stooq_quote(t, opener=None):
    """(price, time UTC) from Stooq's CSV quote (no key), or None. Stooq times are Polish local time."""
    opener = opener or urllib.request.urlopen
    url = "https://stooq.com/q/l/?s=%s.us&f=sd2t2c&h&e=csv" % urllib.parse.quote(t.lower())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with opener(req, timeout=8) as r:
            lines = r.read().decode("utf-8", "replace").strip().splitlines()
        sym, d, tm, close = lines[1].split(",")[:4]
        if close in ("N/D", ""):
            return None
        try:
            from zoneinfo import ZoneInfo
            local = datetime.fromisoformat("%sT%s" % (d, tm)).replace(tzinfo=ZoneInfo("Europe/Warsaw"))
            return float(close), local.astimezone(timezone.utc)
        except Exception:
            return float(close), None
    except Exception:
        return None


def us_backup_quote(t):
    """The newest of the backup US quotes: (price, time UTC) or None. Nasdaq's last sale is real time, so a Nasdaq
    price whose trade time cannot be read counts as now (checked from the VPS, 6 Nov 2026: Nasdaq answers, Stooq
    does not)."""
    now = datetime.now(timezone.utc)
    n = _nasdaq_quote(t)
    got = [(n[0], n[1] or now)] if n else []
    st = _stooq_quote(t)
    if st and st[1] is not None:
        got.append(st)
    return max(got, key=lambda q: q[1]) if got else None


def crypto_live_price(t, rest=True):
    """(price, time) for a coin from Coinbase (public data, no key): the live ticker's file (crypto_ticker.py)
    first, then one REST request. None when Coinbase does not list the coin or does not answer (Yahoo then)."""
    try:
        import coinbase
    except Exception:
        return None
    q = coinbase.tick_price(t)
    if q:
        return q
    return coinbase.price(t) if rest else None


def us_live_price(t, rest=True):
    """(price, time) for a US stock from Alpaca's IEX feed (paper key, data only): the live ticker's file
    (us_ticker.py) first, then one REST request. None without Alpaca keys or an IEX price (Yahoo then)."""
    try:
        import alpaca
    except Exception:
        return None
    q = alpaca.tick_price(t)
    if q:
        return q
    return alpaca.price(t) if (rest and alpaca.configured()) else None


def fetch_price(m, t):
    """Return (price, quote_time_utc). Raises PaperError."""
    kq = kite_price(m, t)                # Indian market: Zerodha (live) when connected
    if kq:
        return float(kq[0]), kq[1]
    if m == "US":
        uq = us_live_price(t)            # US: Alpaca IEX, live (owner, 11 Nov 2026)
        if uq:
            return float(uq[0]), uq[1]
    if m == "CRYPTO":
        cq = crypto_live_price(t)        # crypto: Coinbase live (CoinDCX blocks the VPS; 11 Nov 2026)
        if cq:
            return float(cq[0]), cq[1]
    if m == "USOPT":                     # Alpaca options data, indicative feed (paper key, data only)
        import us_options
        try:
            q = us_options.price(t)
        except Exception as e:
            raise PaperError("could not price %s: %s" % (t, str(e)[:200]))
        if not q:
            raise PaperError("no Alpaca option price for %s (paper key set? market open?)" % t)
        return q
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
    last, best = None, None
    for host in ("query2", "query1"):
        # _=<now> makes every request unique, so no cache between us and Yahoo can hand back an old answer
        url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1m&includePrePost=false&_=%d" % (
            host, ysym, int(time.time()))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=8) as r:
                doc = json.loads(r.read())
            res = (doc.get("chart") or {}).get("result") or []
            if not res:
                raise PaperError("Yahoo has no data for %s" % yahoo_symbol(m, t))
            best = _newest_quote(res[0])
            if best is None:
                raise PaperError("no price for %s" % yahoo_symbol(m, t))
            break
        except PaperError:
            raise
        except Exception as e:
            last = e
    if best is not None:
        price, qt = best
        # 5 Nov 2026: US quotes stayed frozen for 15+ minutes while the market was open (crypto was fine). If the
        # 1-minute answer is stale in an open session, ask for the 5-minute chart the scanner uses (it was fresh).
        now = datetime.now(timezone.utc)
        if m in ("US", "NSE", "BSE") and session(m, now) == "open" and now - qt > timedelta(minutes=10):
            try:
                import scan_nse as SN
                d = SN.yahoo_chart(t, "1d", "5m", suffix=MARKETS[m]["suffix"])
                if d and d["t"]:
                    t5 = datetime.fromtimestamp(d["t"][-1], timezone.utc) + timedelta(minutes=5)
                    if t5 > qt:
                        price, qt = float(d["c"][-1]), min(t5, now)
            except Exception:
                pass
        # still stale (5-6 Nov 2026: Yahoo served US quotes frozen 87 min from the VPS): Nasdaq / Stooq
        if m == "US" and session(m, now) == "open" and now - qt > timedelta(minutes=10):
            b = us_backup_quote(t)
            if b and b[1] > qt:
                price, qt = b[0], min(b[1], now)
        return float(price), qt
    if m == "US":      # Yahoo failed outright: the backup sources
        b = us_backup_quote(t)
        if b:
            return float(b[0]), min(b[1], datetime.now(timezone.utc))
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


def fetch_minutes(m, t, days=1):
    """1-minute candles [(utc, o, h, l, c)] of the last `days` days (1..7), oldest first, or [] (F&O, or no data).
    Used by check_once to see what happened BETWEEN two checks: a stop or target touched and left again in the
    minutes in between."""
    k = kite_mod() if m in ("NSE", "BSE", "NFO") else None
    if k:
        try:
            now = datetime.now(timezone.utc)
            out = k.minutes(key(m, t), now - timedelta(days=max(1, min(7, int(days)))), now)
            if out:
                return out
        except Exception:
            pass
    if m in ("NFO", "USOPT"):           # no 1-minute option candles: the checks use the live premium
        return []
    if m == "US":                        # Alpaca IEX 1-minute bars (paper key, data only)
        try:
            import alpaca
            if alpaca.configured():
                now = datetime.now(timezone.utc)
                out = alpaca.minutes(t, now - timedelta(days=max(1, min(7, int(days)))), now)
                if out:
                    return out
        except Exception:
            pass
    ysym = urllib.parse.quote(yahoo_symbol(m, t), safe="")
    rng = "%dd" % max(1, min(7, int(days)))
    for host in ("query2", "query1"):
        url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1m" % (host, ysym, rng)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=8) as r:
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


def _iso(x):
    """ISO text -> aware datetime (a time saved without a zone is taken as UTC), or None."""
    try:
        d = datetime.fromisoformat(x) if x else None
    except (TypeError, ValueError):
        return None
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def covered_since(pos):
    """Where the next check must start reading 1-minute candles: one candle before the end of the last candle already
    walked (that candle may have been still forming), or the entry. pos["covered_until"] only moves as far as the
    candles that actually came back, so a late data feed or a failed fetch never skips minutes (5 Nov 2026, second
    report). Positions opened before that field existed fall back to last_seen."""
    cov, entry = _iso(pos.get("covered_until")), _iso(pos.get("entry_time"))
    if cov and entry and cov <= entry:
        return entry              # nothing walked yet: start strictly after the entry
    if cov:
        return cov - timedelta(seconds=60)
    seen = _iso(pos.get("last_seen"))
    if seen:
        return seen - timedelta(seconds=60)
    return _iso(pos.get("entry_time"))


def path_since(pos, bars, now, price):
    """The price path to check for this position: the 1-minute candles not yet walked, then the live price. Before
    the first check, only candles that started after the entry (the entry's own minute may hold prices from before
    it)."""
    since = covered_since(pos)
    path = [b for b in bars if since is not None and since <= b[0] < now]
    # the live price last. It only counts as a gap past the stop when there were no candles to look at and the
    # position was not checked in the last 15 minutes (the old rule); otherwise a resting stop fills at the stop.
    seen = _iso(pos.get("last_seen"))
    watched = bool(seen) and (now - seen) <= timedelta(minutes=15)
    # an option has no 1-minute candles (fetch_minutes): its premium jumps, and with no candles we cannot know it
    # traded at the stop, so a live premium past the stop fills there, not at the stop
    no_candles = pos.get("market") in ("NFO", "USOPT")
    path.append((now, price, price, price, price, not bars and (not watched or no_candles)))
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
    if account_of(m) not in INDIA_ACCOUNTS:
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
        if not getattr(a, "allow_second", False):
            raise PaperError("%s is already open; sell it first" % k)
        n = 2                       # the v4 latest-BOS rule: a second trade on the chart gets its own key
        while any(p["key"] == "%s#%d" % (k, n) for p in led["open"]):
            n += 1
        k = "%s#%d" % (k, n)
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
    # margin: India / US stocks (14 Nov 2026) and crypto (owner, 17 Nov 2026: 5x, like Indian crypto futures)
    lev = float(acc.get("intraday_leverage") or 1) if (kind == "equity" and m in ("NSE", "BSE", "US", "CRYPTO")) else 1.0
    lev = max(1.0, min(lev, 5.0))
    if kind == "futures":
        unit_cost = entry * acc.get("futures_margin_pct", 12) / 100
    else:
        unit_cost = entry / lev           # intraday margin: the cash one unit ties up
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
        "position cap (%g%% of account%s)" % (pos_pct, " in margin" if kind == "futures" or lev > 1 else ""):
            equity * pos_pct / 100 / unit_cost,
        "cash" + (" (futures margin %g%%)" % acc.get("futures_margin_pct", 12) if kind == "futures" else
                  " (intraday margin, %gx)" % lev if lev > 1 else ""):
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
    margin = round(q * unit_cost, 2) if (kind == "futures" or lev > 1) else None
    book["cash"] -= (margin if margin is not None else q * entry) + fee
    pos = {"key": k, "market": m, "symbol": t, "qty": q, "entry": round(entry, 6), "stop": stop, "risk_stop": stop,
           "target": target, "entry_fee": round(fee, 4), "entry_time": now.isoformat(),
           "entry_date": local_now(m, now).date().isoformat(), "note": getattr(a, "note", None) or "",
           "last_seen": now.isoformat(), "kind": kind, "side": "short" if short else "long"}
    if lot > 1:
        pos["lots"], pos["lot_size"] = int(q // lot), lot
    if margin is not None:
        pos["margin"] = margin
        if lev > 1:
            pos["leverage"] = lev
    # why this trade was taken (dashboard, downloads): the setup, the scanner that found it, the liquidity it
    # swept / the zone it retested, and the entry reason in words. Optional: callers that know them pass them.
    for f in ("setup", "setup_name", "scanner", "liquidity", "entry_reason", "v4_chart", "v4_signal_at"):
        v = getattr(a, f, None)
        if v not in (None, ""):
            pos[f] = v
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


TM_EVENTS = []   # what the Trade Manager did this check; live.py writes them to the runner log ("TRADE MANAGER: ...")


def tm_event(pos, text, now=None):
    """Record a Trade Manager action: for the runner log, and on the position (its last 8 actions)."""
    now = now or datetime.now(timezone.utc)
    TM_EVENTS.append("%s %s" % (pos.get("key"), text))
    pos.setdefault("tm_log", []).append({"t": now.isoformat(), "text": text})
    pos["tm_log"] = pos["tm_log"][-8:]


TM_KEYS = ("tm_be_r", "tm_trail", "tm_trail_step", "tm_trail_gap", "tm_lock_at", "tm_lock_keep", "tm_reversal",
           "tm_rev_min_r", "tm_stale_min", "tm_candle_min")


def pdf_only(pos):
    """A Scanner v4 trade (the crypto agent's own time stop skips it). Its exits are the account's Trade Manager,
    like every other scanner's trades (13 Nov 2026)."""
    return pos.get("scanner") == "v4"


def tm_trail(pos, best, sh, when, tm):
    """The Trade Manager's breakeven + trailing stop (scanner_v4.trail_lock_r: the same rule as the backtest)."""
    import scanner_v4 as V4
    rs = pos.get("risk_stop", pos["stop"])
    risk = abs(pos["entry"] - rs)
    if risk <= 0:
        return
    gain = ((pos["entry"] - best) if sh else (best - pos["entry"])) / risk
    lock = V4.trail_lock_r(gain, dict(tm, trade_manager=True))
    if lock is None:
        return
    m = pos["market"]
    new = round_px(m, pos["entry"] - lock * risk if sh else pos["entry"] + lock * risk, down=not sh)
    if (new < pos["stop"]) if sh else (new > pos["stop"]):
        pos["stop"], pos["breakeven"] = new, True
        if lock > 0:
            pos["trailing"] = True
            text = "trailing: price reached +%.1fR, stop moved to %s (%+.1fR)" % (gain, money(m, new), lock)
        else:
            text = "breakeven: price reached +%.1fR, stop moved to the entry %s" % (gain, money(m, new))
        print("TM %-16s %s" % (pos["key"], text))
        tm_event(pos, text, when)


def tm_cfg(acc):
    """The account's Trade Manager settings, or None when it is off."""
    if not acc.get("trade_manager"):
        return None
    d = DEFAULT_CONFIG["accounts"]["US"]
    return {k: acc.get(k, d.get(k)) for k in TM_KEYS}


def _risk(pos):
    rs = pos.get("risk_stop", pos["stop"])
    return abs(pos["entry"] - rs) if rs is not None else 0.0


def r_of(pos, px):
    """R of price px for this position (positive = in profit)."""
    risk = _risk(pos)
    if not risk:
        return 0.0
    return ((pos["entry"] - px) if is_short(pos) else (px - pos["entry"])) / risk


def _track_excursion(pos, best, worst, sh):
    """mfe_r / mae_r: the furthest the trade went for / against it, in R (kept on the closed record)."""
    if not _risk(pos):
        return
    pos["mfe_r"] = round(max(pos.get("mfe_r", 0.0), r_of(pos, best)), 3)
    pos["mae_r"] = round(min(pos.get("mae_r", 0.0), r_of(pos, worst)), 3)


def _candles(bars, start, now, minutes):
    """1-minute bars -> completed `minutes` candles [(end, o, h, l, c)] from `start`, oldest first."""
    span, groups = minutes * 60, []
    for b in bars:
        t, o, h, l, c = b[:5]
        if t < start:
            continue
        key = int(t.timestamp() // span)
        if groups and groups[-1][0] == key:
            k0, o0, h0, l0, _ = groups[-1]
            groups[-1] = (k0, o0, max(h0, h), min(l0, l), c)
        else:
            groups.append((key, o, h, l, c))
    out = []
    for key, o, h, l, c in groups:
        end = datetime.fromtimestamp((key + 1) * span, timezone.utc)
        if end <= now:
            out.append((end, o, h, l, c))
    return out


def tm_react(pos, bars, now, price, tm):
    """The Trade Manager's decision after the stop / target walk: a reason to close now, or None.
      reversal: after +tm_rev_min_r R, a completed candle near the trade's best price that is a bearish engulfing
                or a long upper-wick rejection (mirrored for shorts) -> take the profit.
      no follow-through: after tm_stale_min minutes the trade never reached +0.5R and is within 0.3R of the entry.
    """
    sh = is_short(pos)
    risk = _risk(pos)
    entry_t = _iso(pos.get("entry_time"))
    if not risk or entry_t is None:
        return None
    if tm.get("tm_reversal") and pos.get("mfe_r", 0) >= tm["tm_rev_min_r"]:
        cs = _candles(bars, entry_t, now, int(tm["tm_candle_min"]))
        seen = _iso(pos.get("tm_seen"))
        if cs:
            pos["tm_seen"] = cs[-1][0].isoformat()
        sg = -1 if sh else 1
        peak = sg * pos["entry"] + pos["mfe_r"] * risk          # the best price so far, in long terms
        for k in range(1, len(cs)):
            if seen and cs[k][0] <= seen:
                continue
            _, po, ph, pl, pc = cs[k - 1]
            _, o, h, l, c = cs[k]
            if sh:   # mirror to long terms
                po, ph, pl, pc = -po, -pl, -ph, -pc
                o, h, l, c = -o, -l, -h, -c
            rng = h - l
            engulf = pc > po and c < o and o >= pc and c <= po
            reject = rng > 0 and (h - max(o, c)) / rng >= 0.6 and (c - l) / rng <= 0.4
            if (engulf or reject) and h >= peak - 0.25 * risk:
                kind = ("bullish engulfing" if sh else "bearish engulfing") if engulf else \
                       ("lower-wick rejection" if sh else "upper-wick rejection")
                return "reversal (%s) near the best price after +%.1fR" % (kind, pos["mfe_r"])
    mins = (now - entry_t).total_seconds() / 60
    if tm.get("tm_stale_min") and mins >= tm["tm_stale_min"] and pos.get("mfe_r", 0) < 0.5 \
            and abs(r_of(pos, price)) < 0.3:
        return "no follow-through after %d min (best +%.2fR)" % (mins, pos.get("mfe_r", 0))
    return None


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
        why = ("trailing stop" if pos.get("trailing") else "profit lock stop" if pos.get("locked")
               else "breakeven stop" if pos.get("breakeven") else "stop")
        if why in ("profit lock stop", "breakeven stop") and tm_cfg(acc):
            tm_event(pos, "%s hit at %s (%+.2fR) instead of the original stop" % (why, money(m, fill), r_of(pos, fill)),
                     when)
        close_position(led, cfg, pos, fill, why if not gapped else why + " (gapped past it)", when)
        return True
    if (l <= pos["target"]) if sh else (h >= pos["target"]):
        # a take-profit is a limit order: it fills at the target, not at a later, better price
        close_position(led, cfg, pos, pos["target"], "target", when)
        return True
    best = l if sh else h
    _track_excursion(pos, best, h if sh else l, sh)
    pos.pop("pdf_only", None)              # 13 Nov 2026: no v4-only exits any more
    # the account's Trade Manager: one set for every scanner (owner, 13 Nov 2026); not the crypto trailing exits
    tm = tm_cfg(acc) if not pos.get("trail_k") else None
    rs = pos.get("risk_stop", pos["stop"])
    if tm:
        tm_trail(pos, best, sh, when, tm)
    if tm and tm.get("tm_lock_at") and pos.get("target") and not pos.get("locked"):
        way = pos["target"] - pos["entry"]
        if way and (best - pos["entry"]) / way >= tm["tm_lock_at"]:
            lock = round_px(m, pos["entry"] + tm["tm_lock_keep"] * way, down=not sh)
            if (lock < pos["stop"]) if sh else (lock > pos["stop"]):
                pos["stop"] = lock
            pos["locked"], pos["breakeven"] = True, True
            print("PROFIT LOCK %-16s %s covered %.0f%% of the way to the target: stop locked at %s"
                  % (pos["key"], money(m, best), tm["tm_lock_at"] * 100, money(m, pos["stop"])))
            tm_event(pos, "profit lock: %.0f%% of the way to the target (%s), stop locked at %s (+%.1fR)"
                     % (tm["tm_lock_at"] * 100, money(m, best), money(m, pos["stop"]), r_of(pos, pos["stop"])), when)
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


def _quotes(positions, now):
    """Live price and the 1-minute candles to walk for every open position, fetched in parallel (8 at a time) so a
    slow or rate-limited data feed cannot stretch the runner's cycle (5 Nov 2026: the dashboard froze with many
    open US positions). Returns {key: (price, quote_time, bars, error)}."""
    from concurrent.futures import ThreadPoolExecutor

    def one(pos):
        m, t = pos["market"], pos["symbol"]
        try:
            price, qt = fetch_price(m, t)
        except Exception as e:
            return pos["key"], (None, None, [], str(e))
        bars = []
        if session(m, now) != "closed":
            since = covered_since(pos)
            days = 1 if since is None else 1 + max(0, (now.date() - since.astimezone(timezone.utc).date()).days)
            try:
                bars = fetch_minutes(m, t, days)
            except Exception:
                bars = []
        return pos["key"], (price, qt, bars, None)
    if not positions:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(positions))) as ex:
        return dict(ex.map(one, positions))


def check_once(cfg, led):
    now = datetime.now(timezone.utc)
    if not led["open"]:
        print("No open paper positions.")
        return 0
    quotes = _quotes(list(led["open"]), now)
    for pos in list(led["open"]):
        price, qt, bars, err = quotes.get(pos["key"], (None, None, [], "no quote"))
        if price is None:
            print("%-16s %s" % (pos["key"], err))
            continue
        # the price the dashboard shows: the one just fetched (no second request per position)
        pos["last_price"], pos["last_price_at"] = price, now.isoformat()
        pos["quote_time"] = qt.isoformat() if qt else None
        try:
            check_position(cfg, led, pos, price, bars, now)
        except Exception as e:   # one bad position never stops the others (or the dashboard's prices)
            print("%-16s check failed: %s: %s" % (pos.get("key"), type(e).__name__, e))
    return len(led["open"])


INDEX_TICK = {"NIFTY": "NSE:NIFTY50", "BANKNIFTY": "NSE:BANKNIFTY"}


def underlying_data(market, symbol, since, now):
    """(price, 1-minute candles since `since`) of an option's underlying: QQQ / SPY / DIA (US), Nifty / Bank Nifty or
    an F&O stock (NSE). Live feeds first (Alpaca, Zerodha), Yahoo after."""
    t = symbol.upper()
    price, bars = None, []
    if market == "NSE" and t in INDEX_TICK:
        k = kite_mod()
        if k:
            try:
                q = k.tick_price(INDEX_TICK[t]) or k.ltp(INDEX_TICK[t])
                price = float(q[0]) if q else None
            except Exception:
                price = None
            try:
                bars = k.minutes(INDEX_TICK[t], since - timedelta(minutes=1), now) or []
            except Exception:
                bars = []
        if price is None or not bars:
            import fno as F
            d = F.yahoo_bars(F.FNO[t]["yahoo"], "1d", "1m")
            ys = [(datetime.fromtimestamp(ts, timezone.utc), o, h, l, c) for ts, o, h, l, c in
                  zip(d["t"], d["o"], d["h"], d["l"], d["c"]) if None not in (o, h, l, c)]
            bars = bars or ys
            if price is None and ys:
                price = float(ys[-1][4])
    else:
        price = fetch_price(market, symbol)[0]
        try:
            bars = fetch_minutes(market, symbol, 1)
        except Exception:
            bars = []
    return price, [b for b in bars if b[0] + timedelta(seconds=60) > since]


def underlying_exit(pos, now):
    """The v4 option's plan on its underlying (pos["underlying_plan"]): a reason to exit when the underlying's
    1-minute candles since the last check, or its live price, reached the v4 stop (first, as the engine) or target;
    else None. Data trouble never closes a trade: it is retried on the next check."""
    u = pos["underlying_plan"]
    since = _iso(u.get("checked_until")) or _iso(pos.get("entry_time")) or now
    try:
        px, bars = underlying_data(u["market"], u["symbol"], since, now)
    except Exception as e:
        print("%-16s underlying %s not checked: %s" % (pos["key"], u["symbol"], str(e)[:120]))
        return None
    short = u["side"] == "short"
    stop, target = u["stop"], u.get("target")
    path = [(b[2], b[3], b[0]) for b in bars] + ([(px, px, now)] if px is not None else [])
    for hi, lo, at in path:
        if (hi >= stop) if short else (lo <= stop):
            return "underlying stop: %s reached %s, the v4 stop %s" % (u["symbol"], hi if short else lo, stop)
        if target is not None and ((lo <= target) if short else (hi >= target)):
            return "underlying target: %s reached %s, the v4 target %s" % (u["symbol"], lo if short else hi, target)
    u["checked_until"] = (now.replace(second=0, microsecond=0)).isoformat()
    u["last"] = px
    return None


def check_position(cfg, led, pos, price, bars, now):
    """One open position: walk its 1-minute candles and the live price (stop first, then target), then the
    flat-by / overnight exits. Raises on bad data; check_once catches it so the other positions still run."""
    m = pos["market"]
    acc = acct_cfg(cfg, m)
    sess = session(m, now)
    upnl = pnl_of(pos, price)
    sh = is_short(pos)
    if sess == "closed":
        print("%-16s %s closed; last %s (open P&L %s). Checked again when it opens."
              % (pos["key"], m, money(m, price), money(m, upnl)))
        return
    intraday = bool(acc.get("flat_by")) and MARKETS[m]["open"] is not None
    # Walk every 1-minute candle since the last check, then the live price: a stop or target touched between two
    # checks (5 min apart) counts even if price came back by the time we look (owner's report, 5 Nov 2026).
    since = covered_since(pos)
    path = path_since(pos, bars, now, price)
    walked = [b for b in path if len(b) == 5]
    pos["last_seen"] = now.isoformat()
    if walked:   # covered up to the end of the last candle that came back, never past it
        end = min(now, walked[-1][0] + timedelta(seconds=60))
        prev = _iso(pos.get("covered_until"))
        pos["covered_until"] = max(end, prev).isoformat() if prev else end.isoformat()
    elif not pos.get("covered_until") and since is not None:
        # first check with no candles: pin the start so a later last_seen cannot skip the window
        entry = _iso(pos.get("entry_time"))
        pos["covered_until"] = (since if since == entry else since + timedelta(seconds=60)).isoformat()
    if not walked:
        print("%-16s no new 1-minute candles (late feed or fetch failed): checked the live price only; the "
              "missing minutes are read on the next check" % pos["key"])
    for b in path:
        if step_bar(led, cfg, pos, acc, b, now, sh):
            return
    if pos.get("underlying_plan"):
        why = underlying_exit(pos, now)
        if why:
            close_position(led, cfg, pos, price, why, now)
            return
    tm = tm_cfg(acc) if not pos.get("trail_k") else None
    if tm:   # the Trade Manager thinks about the trade after every check (7 Nov 2026), whatever the scanner
        why = tm_react(pos, bars, now, price, tm)
        if why:
            tm_event(pos, "exit at %s (%+.2fR): %s" % (money(m, price), r_of(pos, price), why), now)
            close_position(led, cfg, pos, price, "trade manager: " + why, now)
            return
    entry_day = pos.get("entry_date") or (_iso(pos.get("entry_time")) or now).date().isoformat()
    if intraday and entry_day != local_now(m, now).date().isoformat():
        close_position(led, cfg, pos, price, "carried overnight: missed the flat-by", now)
    elif intraday and past_flat_by(m, acc, now):
        close_position(led, cfg, pos, price, "flat by %s" % acc["flat_by"], now)
    else:
        to_stop = abs(price / pos["stop"] - 1) * 100
        to_tgt = abs(pos["target"] / price - 1) * 100 if pos.get("target") else float("nan")
        qa = _iso(pos.get("quote_time"))
        age = (now - qa).total_seconds() / 60 if qa else None
        print("%-16s %s%s  open P&L %s   %.2f%% from the stop%s, %.2f%% from the target%s"
              % (pos["key"], "SHORT " if sh else "", money(m, price), money(m, upnl), to_stop,
                 " (breakeven)" if pos.get("breakeven") else "", to_tgt,
                 "" if age is None else "   quote %.0f min old%s" % (max(0.0, age), "  STALE" if age > 10 else "")))


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
            raise PaperError("unknown account %r (INDIA, FNO, US, CRYPTO or ALL)" % name)
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


# ------------------------------------------------------------------ Scanner v3 setups: the agents, then the paper broker

INDEX_UNDERLYINGS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")


def v4_timemachine(market, symbol, s, acc, entry, stop, target):
    """The v4 time machine (timemachine_v4.py) on the candles the scanner just read: history of the rule on this
    chart + replays of the rest of the session. Information only (owner, 14 Nov 2026): never blocks a trade."""
    if s.get("scanner") != "v4":
        return None
    try:
        import smc_playbook as PB
        import scanner_v4 as V4
        import timemachine_v4 as TM
        got = PB.LAST_ROWS.get("%s:%s" % (market, symbol))
        if not got:
            return "not run: the scanner's candles for this chart are not in memory (setup came from elsewhere)"
        rows, day_of, intraday = got
        res = TM.run(rows, day_of, intraday, s["side"], entry, stop, target, V4.tm_settings(acc),
                     chart="%s:%s" % (market, symbol))
        return res or "not run: too few candles"
    except Exception as e:   # never lose the decision over the time machine
        return "not run: %s" % str(e)[:160]


def _option_setup(st, done, cfg, acc, symbol, s, op, version, led, v4_fields, mk="NFO"):
    """setup_decision for an option trade: an Indian index / F&O stock (NFO) or QQQ / SPY (USOPT): the ATM option is
    paper bought."""
    word = {"CE": "call", "PE": "put"}[op["kind"]] if mk == "USOPT" else op["kind"]
    entry, stop = s["price"], s["stop"]
    target = s.get("target") or s.get("target_2r")
    name = s.get("name") or s["setup"]
    risk_u = op["premium"] - op["stop"]
    st["4_exit"] = {"instrument": mk + ":" + op["name"], "why": "%s setup -> buy the ATM %s" % (s["side"], word),
                    "premium": op["premium"], "premium_stop": op["stop"], "premium_target": op["target"],
                    "stock_entry": entry, "stock_stop": stop, "stock_target": target, "lot": op["lot"],
                    "iv": op["iv"], "delta": op["delta"], "expiry": op["expiry"],
                    "r_multiple": round((op["target"] - op["premium"]) / risk_u, 2)}
    st["5_timemachine"] = v4_timemachine("US" if mk == "USOPT" else "NSE", symbol, s, acc, entry, stop, target) or \
        "n/a (backtest: research.py %s)" % ("usopt-sv4" if mk == "USOPT" else "fno-sv4 / bnf-sv4")
    if not acc.get("trade_setups", True):
        st["6-8_budget_risk_broker"] = {"verdict": "pass, NOT sent to the broker (trade_setups off)"}
        st["9_alerts"] = "no trade, nothing to watch"
        return done("LOG ONLY", "%s on %s: ATM %s %s recorded only (trade_setups is off)" % (name, symbol, word,
                                                                                            op["name"]))
    import contextlib
    import io
    if led is None:
        led = load_ledger(cfg)
    key = mk + ":" + op["name"]
    args = type("A", (), {"symbol": key, "stop": str(op["stop"]), "target": str(op["target"]), "qty": None,
                          "price": None, "note": "scanner %s: %s on %s (stock stop %s, target %s)" % (
                              version, name, symbol, stop, target), "force": False, "side": "long",
                          "setup": s["setup"], "setup_name": name, "scanner": version,
                          "liquidity": s.get("liquidity"),
                          "entry_reason": "Scanner %s %s on %s at %s: bought the ATM %s (IV %.0f%%, delta %.2f); "
                                          "premium stop / target = the option's value at the underlying's stop %s / target %s"
                                          % (version, s["side"], symbol, entry, word, op["iv"] * 100,
                                             op["delta"], stop, target), **v4_fields})()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            pos = cmd_buy(args, cfg, led)
        save_json(LEDGER, led)
    except PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    if version == "v4" and stop is not None:
        # the v4 plan on the underlying's own chart (owner, 17 Nov 2026): the option also exits when QQQ / Nifty
        # reaches the v4 stop or target, as the engine and the backtests do; the premium stop / target still count
        pos["underlying_plan"] = {"market": "US" if mk == "USOPT" else "NSE", "symbol": symbol, "side": s["side"],
                                  "stop": float(stop), "target": float(target) if target is not None else None}
        save_json(LEDGER, led)
    st["6-8_budget_risk_broker"] = {"verdict": "PASS, paper option bought", "qty": pos["qty"], "entry": pos["entry"],
                                    "stop": pos["stop"], "target": pos["target"],
                                    "max_loss": round(abs(pos["entry"] - pos["stop"]) * pos["qty"]
                                                      + pos.get("entry_fee", 0), 2),
                                    "report": buf.getvalue().strip().splitlines()}
    st["9_alerts"] = "live.py / Trade Manager watch the premium: stop %s, target %s" % (pos["stop"], pos["target"]) + (
        "; and %s itself: exit when it reaches the v4 stop %s or target %s" % (symbol, stop, target)
        if pos.get("underlying_plan") else "")
    return done("PAPER BUY", "%s %s @ %s, stop %s, target %s (Scanner %s: %s on %s)" % (
        pos["qty"], pos["key"], pos["entry"], pos["stop"], pos["target"], version, name, symbol))


def setup_decision(market, symbol, s, news=None, now_iso=None):
    """One of the owner's setups found by the Scanner (v3; smc_playbook.owner_setups dict), taken through the agents
    Entry (the candle close), Exit (stop, 2R or the v3 liquidity target, costs in R), Budget (size from this account's limits), Risk (costs <=
    0.25R, at least one unit), then the Broker: a paper trade at the live price with that stop and 2R target (the
    owner's decision for paper testing, 4 Nov 2026), or LOG ONLY when the account's trade_setups is off.
    Returns the decision record for decisions.jsonl."""
    rec = {"time": now_iso or datetime.now(IST).isoformat(), "symbol": "%s:%s" % (market, symbol),
           "setup": s["setup"], "scanner_v2": True, "steps": {}, "result": None}
    st = rec["steps"]
    st["1_scanner"] = {"scanner": s.get("scanner", DEFAULT_SCANNER), "setup": s["setup"], "setup_name": s.get("name"),
                       "side": s["side"], "liquidity": s.get("liquidity"), "bar_end": s.get("bar_end"),
                       "price": s["price"], **(s.get("details") or {})}
    st["2_news"] = news if news is not None else "not fetched for stock setups (hundreds a day)"

    def done(result, why):
        if rec.get("flipped_from"):
            why = "flip, closed %s first: %s" % (rec["flipped_from"], why)
        rec["result"], rec["why"] = result, why
        return rec

    # Scanner v3's sweep reversal carries its own target (the opposing liquidity); the older setups use 2R
    cfg = load_config()
    acc = cfg["accounts"][MARKETS[market]["account"]] if market in MARKETS else cfg["accounts"]["US"]
    if market in ("NSE", "BSE") and symbol.upper() in INDEX_UNDERLYINGS:
        acc = cfg["accounts"].get("FNO", acc)   # an index setup is an F&O trade: the FNO account's switches
    fno_acc = cfg["accounts"].get("FNO", acc)
    usf_acc = cfg["accounts"].get("USFNO") or {}
    us_opt = market == "US" and symbol.upper() in [u.upper() for u in (usf_acc.get("usopt_underlyings") or [])]
    if us_opt:
        acc = usf_acc                            # QQQ / SPY setups are US F&O trades: the USFNO account's switches
    version = acc.get("scanner_version", DEFAULT_SCANNER)
    st["1_scanner"]["scanner"] = version
    # versions never mix (owner, 5 and 7 Nov 2026): a setup of another version (switched after it was scanned) is
    # skipped
    import smc_playbook as _PB
    sv = _PB.setup_version(s["setup"])
    if sv != version:
        return done("skipped", "this account runs Scanner %s: %s setups are off" % (version, sv))
    if version == "v4" and s["setup"] not in acc.get("v4_setups", _PB.V4_SETUPS):
        return done("skipped", "%s is unticked in Settings (Scanner v4: setups traded)" % (s.get("name") or s["setup"]))
    if version == "v5" and s["setup"] not in acc.get("v5_setups", _PB.V5_SETUPS):
        return done("skipped", "%s is unticked in Settings (Scanner v5: setups traded)" % (s.get("name") or s["setup"]))
    led, v4_fields = None, {}
    if version == "v4":
        import scanner_v4 as V4
        chart = key(market, symbol)
        led = load_ledger(cfg)
        opened, closed = V4.chart_state(led, chart)
        signal = _iso(s.get("v4_signal_at"))
        flipped = None
        opens = V4.chart_open(led, chart) or ([opened] if opened else [])
        if opens:
            det = s.get("details") or {}
            prim = s["setup"].startswith("v4_primary_")
            olds = [o for o in opens if (o.get("setup") or "").startswith("v4_primary_")
                    and V4.direction(o) != s["side"]]
            if prim and det.get("flip") and olds:
                # the flip rule (owner, 14 Nov 2026): an open trade came from an earlier day's BOS setup and the
                # opposite side's setup of today's BOS triggered: close it at the current price, then take this one
                import contextlib
                import io
                done_flip = []
                for o in olds:
                    try:
                        px, _ = fetch_price(o["market"], o["symbol"])
                        with contextlib.redirect_stdout(io.StringIO()):
                            done_flip.append(close_position(led, cfg, o, px, "v4 flip: today's opposite BOS setup (%s)"
                                                            % s["side"], datetime.now(timezone.utc)))
                        save_json(LEDGER, led)
                    except Exception as e:
                        return done("blocked", "v4 flip: could not close %s first: %s" % (o["key"], str(e)[:160]))
                flipped = done_flip[0]
                rec["flipped_from"] = ", ".join(c["key"] for c in done_flip)
                st["0_flip"] = {"closed": rec["flipped_from"], "side": V4.direction(olds[0]),
                                "exit": flipped["exit"], "pnl": round(sum(c["pnl"] for c in done_flip), 4),
                                "r": round(sum(c["r"] for c in done_flip), 2),
                                "why": "previous day's BOS trade closed: today's opposite BOS setup triggered"}
                opens = [o for o in opens if o not in olds]
            elif prim and det.get("latest_bos") and len(opens) < int(V4.DEFAULTS["max_open"]):
                # the latest-BOS rule (owner, 14 Nov 2026): a setup of a BOS newer than the open trade's triggered:
                # take it as well (its own position, key ...#2)
                st["0_latest_bos"] = {"open": [o["key"] for o in opens],
                                      "why": "a newer BOS's setup triggered while a trade is open: taken as well"}
            elif prim and det.get("latest_bos"):
                return done("skipped", "v4: a newer BOS's setup, but %d trades are open on this chart already (max %d)"
                            % (len(opens), int(V4.DEFAULTS["max_open"])))
            elif not det.get("flip") and not det.get("latest_bos"):
                # the v4 engine had no trade open on this chart (its stop or target on the chart was hit) but the
                # paper position is still open, e.g. an option whose premium stop was not reached (owner, 17 Nov)
                return done("skipped", "v4: %s is still open on this chart, so this trigger is skipped (the v4 "
                                       "engine had already closed that trade on the chart)" % ", ".join(o["key"] for o in opens))
            else:
                return done("skipped", "v4: wait for the open trade on this chart to close")
        exited = _iso(closed.get("exit_time")) if closed else None
        if signal is None or (not flipped and exited is not None and signal <= exited):
            return done("skipped", "v4: no fresh confirmed signal after the last exit")
        if s["setup"].startswith("v4_secondary_"):
            details = s.get("details") or {}
            primary = _iso(details.get("primary_at"))
            tap = _iso(details.get("tapped_at"))
            if (not closed or closed.get("setup") != "v4_primary_" + s["side"]
                    or primary is None or primary != _iso(closed.get("v4_signal_at"))
                    or exited is None or tap is None or not exited < tap <= signal):
                return done("skipped", "v4: secondary needs a matching closed primary and a later confirmed zone tap")
        v4_fields = {"v4_chart": chart, "v4_signal_at": signal.isoformat()}
        if opens:
            v4_fields["allow_second"] = True
    entry, stop, short = s["price"], s.get("stop"), s["side"] == "short"
    target = s.get("target") or s.get("target_2r")
    st["3_entry"] = {"side": s["side"], "price_now": entry, "note": "entry = the close of the candle that completed it"}
    risk = ((stop - entry) if short else (entry - stop)) if stop is not None else 0
    if risk <= 0:
        return done("skipped", "price %s is already past the stop %s" % (entry, stop))
    is_index = symbol.upper() in INDEX_UNDERLYINGS
    fno_ok = [u.upper() for u in (fno_acc.get("fno_underlyings") or ["NIFTY", "BANKNIFTY"])]
    if market in ("NSE", "BSE") and (is_index or fno_acc.get("fno_stock_options")):
        # F&O only on the owner's underlyings (12 Nov 2026: Nifty 50 and Bank Nifty): an index setup buys its ATM option; a
        # stock's setup buys the option only if the stock is listed there, else the shares (backtests: research.py
        # bnf-sv4, fno-sv4)
        op = None
        if symbol.upper() not in fno_ok:
            if is_index:
                return done("skipped", "F&O is traded only on %s (owner, 12 Nov 2026)" % ", ".join(fno_ok))
        else:
            import fno_stock as _FS
            try:
                op = _FS.plan(symbol, s)
            except _FS.NoOption as e:
                if is_index or "has no F&O" not in str(e):
                    st["4_exit"] = {"underlying_entry": entry, "underlying_stop": stop, "underlying_target": target}
                    return done("skipped", "option: %s" % e)
        if op:
            return _option_setup(st, done, cfg, fno_acc, symbol, s, op, version, led, v4_fields)
    if us_opt:
        # US F&O (owner, 13 Nov 2026): a QQQ / SPY setup buys its ATM weekly option, never the ETF's shares
        import us_options as _UO
        try:
            op = _UO.plan(symbol, s)
        except _UO.NoOption as e:
            st["4_exit"] = {"underlying_entry": entry, "underlying_stop": stop, "underlying_target": target}
            return done("skipped", "option: %s" % e)
        return _option_setup(st, done, cfg, usf_acc, symbol, s, op, version, led, v4_fields, mk="USOPT")
    units = min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / entry)
    qty = units if market == "CRYPTO" else int(units)
    cost = None
    if market in ("NSE", "BSE"):
        if qty >= 1:
            o, c = ("sell", "buy") if short else ("buy", "sell")
            cost = (charges(cfg, "NSE", symbol, o, qty * entry) + charges(cfg, "NSE", symbol, c, qty * target)) / (qty * risk)
    else:
        cost = (entry + target) * float(acc.get("fee_pct") or 0) / 100 / risk
    st["4_exit"] = {"entry": entry, "stop": stop, "target": target, "r_multiple": round(abs(target - entry) / risk, 2),
                    "stop_pct": round(risk / entry * 100, 3), "fee_r": round(cost, 3) if cost is not None else None}
    st["5_timemachine"] = v4_timemachine(market, symbol, s, acc, entry, stop, target) or \
        "n/a (these setups are backtested instead: research_v3 / research_smcp / research_abcd)"
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
    if led is None:
        led = load_ledger(cfg)
    args = type("A", (), {"symbol": "%s:%s" % (market, symbol), "stop": str(stop), "target": str(target), "qty": None,
                          "price": None, "note": "scanner %s: %s" % (version, name), "force": False,
                          "side": "short" if short else "long", "setup": s["setup"], "setup_name": name,
                          "scanner": version, "liquidity": s.get("liquidity"),
                          "entry_reason": "found by Scanner %s; entry on the close of the %s candle, planned R:R %.1f" % (
                              version, (s.get("bar_end") or "")[11:16] or "last", abs(target - entry) / risk), **v4_fields})()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            pos = cmd_buy(args, cfg, led)
        save_json(LEDGER, led)
    except PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    st["6-8_budget_risk_broker"] = {"verdict": "PASS, paper %s filled" % ("short" if short else "buy"), "qty": pos["qty"],
                                    "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
                                    "max_loss": round(abs(pos["entry"] - pos["stop"]) * pos["qty"] + pos.get("entry_fee", 0), 2),
                                    "report": buf.getvalue().strip().splitlines()}
    st["9_alerts"] = "live.py checks stop %s / target %s every cycle" % (pos["stop"], pos["target"])
    return done("PAPER SHORT" if short else "PAPER BUY", "%s @ %s, stop %s, target %s (Scanner %s: %s)" % (
        fmt_qty(market, pos["qty"]), pos["entry"], pos["stop"], pos["target"], version, name))
