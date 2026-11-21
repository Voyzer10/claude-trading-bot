#!/usr/bin/env python3
"""No daily trade-COUNT limit on any paper account (owner, 21 Nov 2026). Offline.

  1. Config: max_trades_per_day is gone from every account (defaults, Settings fields, and an old config file
     that still has it is cleaned once on load).
  2. More than 50 entries in one day on CRYPTO with risk limits ON: every one fills, trades_today counts them all.
  3. Every account (INDIA, FNO, US, USFNO, CRYPTO): 200 entries already today does not block the next entry.
  4. The other guards still block (risk limits ON): the daily loss limit, the open-position cap per side
     (max_same_side), a second open position on the same symbol, free cash, a stop on the wrong side, the minimum
     reward:risk, a stop too tight for the fees, short selling where it is off.
  5. A burst of entries in one cycle (back to back on one ledger) cannot get past the cash, the same-symbol or the
     daily loss checks: each entry sees the ones before it.
  6. auto_us gives the US skill pack no trade / order count limit (0 = off in trader-risk/check.py).

    python tests/test_no_daily_trade_cap.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def buy(P, cfg, led, symbol, price, stop, target, side="long", force=True):
    a = type("A", (), {"symbol": symbol, "stop": str(stop), "target": str(target), "qty": None, "price": price,
                       "note": "test", "force": force, "side": side})()
    return P.cmd_buy(a, cfg, led)


def sell(P, cfg, led, symbol, price):
    a = type("A", (), {"symbol": symbol, "price": price})()
    P.cmd_sell(a, cfg, led)


def blocked(fn):
    try:
        fn()
    except Exception as e:     # PaperError
        return str(e)
    return None


def fake_trades(P, m, n, now, pnl=0.0):
    """n closed trades of market m entered and closed today (no loss unless pnl < 0)."""
    d = P.local_now(m, now).date().isoformat()
    return [{"key": "%s:FAKE%d" % (m, i), "market": m, "symbol": "FAKE%d" % i, "qty": 1, "entry": 1.0, "stop": 0.9,
             "target": 1.2, "entry_time": now.isoformat(), "entry_date": d, "exit_time": now.isoformat(),
             "exit_date": d, "pnl": pnl, "side": "long", "exit": 1.0, "reason": "test"} for i in range(n)]


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    os.chdir(tmp)
    import paper as P
    import api._ops as OPS

    # ---------------------------------------------------------------- 1. config
    check("1. DEFAULT_CONFIG: no max_trades_per_day in any account",
          all("max_trades_per_day" not in a for a in P.DEFAULT_CONFIG["accounts"].values()))
    check("   Settings > Risk limits: max_trades_per_day is not an editable field any more",
          "max_trades_per_day" not in OPS.RISK_FIELDS)
    os.makedirs(os.path.dirname(P.CONFIG), exist_ok=True)
    old = json.loads(json.dumps(P.DEFAULT_CONFIG))
    for acc in old["accounts"].values():
        acc["max_trades_per_day"] = 5
    with open(P.CONFIG, "w") as fh:
        json.dump(old, fh)
    cfg = P.load_config()
    with open(P.CONFIG) as fh:
        disk = json.load(fh)
    check("   an old config with max_trades_per_day 5 everywhere: the key is removed once, in memory and on disk",
          all("max_trades_per_day" not in a for a in cfg["accounts"].values())
          and all("max_trades_per_day" not in a for a in disk["accounts"].values()) and disk.get("_no_trade_cap_1121"))
    check("   the other limits are untouched by the clean-up (daily loss, max loss per trade, leverage)",
          all(cfg["accounts"][n]["daily_loss_limit"] == old["accounts"][n]["daily_loss_limit"]
              and cfg["accounts"][n]["max_loss_per_trade"] == old["accounts"][n]["max_loss_per_trade"]
              and cfg["accounts"][n].get("intraday_leverage") == old["accounts"][n].get("intraday_leverage")
              for n in old["accounts"]))
    for acc in cfg["accounts"].values():
        acc["risk_limits"] = True                 # every guard ON for the rest of the test
        acc["cooldown_losses"] = 0                # (the cooldown is tested on its own below)
    now = datetime.now(timezone.utc)

    # ---------------------------------------------------------------- 2. > 50 entries in one day
    led = P.load_ledger(cfg)
    led["open"], led["closed"] = [], []
    ok_n, errs = 0, []
    for i in range(60):
        try:
            buy(P, cfg, led, "CRYPTO:BTC", 100.0, 99.0, 102.0)
            sell(P, cfg, led, "CRYPTO:BTC", 100.5)       # a small win each time: the daily loss limit stays clear
            ok_n += 1
        except Exception as e:
            errs.append(str(e))
    check("2. CRYPTO, risk limits ON: 60 entries in one day all fill (was max 10 / 50 a day)", ok_n == 60, errs[:2])
    check("   trades_today still counts them: 60 entries today", len(P.trades_today(led, "CRYPTO", now)) == 60,
          len(P.trades_today(led, "CRYPTO", now)))

    # ---------------------------------------------------------------- 3. every account, 200 trades already today
    cases = [("NSE", "NSE:TCS", 2000.0, 1990.0, 2030.0), ("US", "US:AAPL", 200.0, 199.0, 202.0),
             ("CRYPTO", "CRYPTO:ETH", 100.0, 99.0, 102.0),
             ("NFO", "NFO:NIFTY-20261126-24000-CE", 100.0, 90.0, 130.0),
             ("USOPT", "USOPT:QQQ261127C00500000", 4.0, 3.85, 4.5)]
    for m, sym, px, st, tg in cases:
        led = P.load_ledger(cfg)
        led["open"], led["closed"] = [], fake_trades(P, m, 200, now)
        n0 = len(P.trades_today(led, m, now))
        why = blocked(lambda: buy(P, cfg, led, sym, px, st, tg))
        check("3. %s (%s account): 200 trades today, the next entry is not blocked by a count" % (
            m, P.account_of(m)), why is None or "per day" not in why, why)
        check("   %s: no count limit message, and the entry filled (counter %d -> %d)" % (
            m, n0, len(P.trades_today(led, m, now))), why is None and len(P.trades_today(led, m, now)) == n0 + 1, why)

    # ---------------------------------------------------------------- 4. the other guards still block
    c = cfg["accounts"]["CRYPTO"]
    led = P.load_ledger(cfg)
    led["open"], led["closed"] = [], fake_trades(P, "CRYPTO", 3, now, pnl=-c["daily_loss_limit"] / 3 - 0.01)
    why = blocked(lambda: buy(P, cfg, led, "CRYPTO:SOL", 100.0, 99.0, 102.0))
    check("4. daily loss limit: losses over the limit today -> the entry is blocked", why and "daily loss limit" in why,
          why)
    led["closed"] = fake_trades(P, "CRYPTO", 3, now, pnl=-1.0)
    check("   under the daily loss limit -> it fills", blocked(lambda: buy(P, cfg, led, "CRYPTO:SOL", 100.0, 99.0,
                                                                          102.0)) is None)
    led = P.load_ledger(cfg)
    led["open"], led["closed"] = [], []
    c["max_same_side"] = 2
    for s in ("CRYPTO:A1", "CRYPTO:A2"):
        buy(P, cfg, led, s, 10.0, 9.9, 10.2)
    why = blocked(lambda: buy(P, cfg, led, "CRYPTO:A3", 10.0, 9.9, 10.2))
    check("   open-position cap (max_same_side 2): a third open long is blocked", why and "open long positions" in why,
          why)
    check("   ... a short on the other side still fills", blocked(lambda: buy(P, cfg, led, "CRYPTO:A4", 10.0, 10.1,
                                                                          9.8, side="short")) is None)
    c["max_same_side"] = 0
    why = blocked(lambda: buy(P, cfg, led, "CRYPTO:A1", 10.0, 9.9, 10.2))
    check("   duplicate position: a second open CRYPTO:A1 is blocked", why and "already open" in why, why)
    check("   stop on the wrong side is refused", "not below the entry" in (blocked(
        lambda: buy(P, cfg, led, "CRYPTO:B1", 10.0, 10.1, 10.5)) or ""))
    check("   target on the wrong side is refused", "wrong side" in (blocked(
        lambda: buy(P, cfg, led, "CRYPTO:B2", 10.0, 9.9, 9.95)) or ""))
    check("   reward:risk under the minimum is refused (no --force)", "reward:risk" in (blocked(
        lambda: buy(P, cfg, led, "CRYPTO:B3", 10.0, 9.9, 10.05, force=False)) or ""))
    check("   a stop too tight for the fees is refused (no --force)", "stop too tight" in (blocked(
        lambda: buy(P, cfg, led, "CRYPTO:B4", 10.0, 9.9999, 10.01, force=False)) or ""))
    fno_short = cfg["accounts"]["FNO"].get("allow_short")
    check("   short selling stays off where allow_short is off (FNO)", not fno_short and "short selling is not enabled"
          in (blocked(lambda: buy(P, cfg, led, "NFO:NIFTY-20261126-24000-CE", 100.0, 110.0, 80.0, side="short")) or ""))
    c["cooldown_losses"] = 2
    led2 = P.load_ledger(cfg)
    led2["open"], led2["closed"] = [], fake_trades(P, "CRYPTO", 2, now, pnl=-1.0)
    check("   cooldown after 2 losses in a row still blocks", "cooldown" in (blocked(
        lambda: buy(P, cfg, led2, "CRYPTO:C1", 10.0, 9.9, 10.2)) or ""))
    c["cooldown_losses"] = 0
    pos = buy(P, cfg, led, "CRYPTO:S1", 100.0, 99.0, 102.0)
    check("   sizing unchanged: the loss at the stop (with fees) stays within max_loss_per_trade",
          (pos["entry"] - pos["stop"]) * pos["qty"] <= c["max_loss_per_trade"] + 1e-6, pos["qty"])

    # ---------------------------------------------------------------- 5. a burst of entries in one cycle
    led = P.load_ledger(cfg)
    led["open"], led["closed"] = [], []
    filled, why_cash = 0, None
    for i in range(40):                             # tight stops -> position-cap sized (25% each): cash runs out first
        why = blocked(lambda: buy(P, cfg, led, "CRYPTO:Z%d" % i, 10.0, 9.9, 10.2))
        if why:
            why_cash = why
            break
        filled += 1
    cash = P.book_of(led, "CRYPTO")["cash"]
    check("5. burst: entries stop when free cash runs out (cash never negative)", why_cash and "cash" in why_cash
          and cash >= 0 and filled < 40, (filled, why_cash, cash))
    led = P.load_ledger(cfg)
    led["open"], led["closed"] = [], []
    r = [blocked(lambda: buy(P, cfg, led, "CRYPTO:DUP", 10.0, 9.9, 10.2)) for _ in range(3)]
    check("   burst on one symbol: the first fills, the next two are refused as already open",
          r[0] is None and all(x and "already open" in x for x in r[1:]), r)
    led["closed"] = fake_trades(P, "CRYPTO", 1, now, pnl=-c["daily_loss_limit"])
    r = [blocked(lambda: buy(P, cfg, led, "CRYPTO:L%d" % i, 10.0, 9.9, 10.2)) for i in range(5)]
    check("   burst after the daily loss limit: every entry of the burst is blocked",
          all(x and "daily loss limit" in x for x in r), r)

    # ---------------------------------------------------------------- 6. US skill pack
    import auto_us as AU
    AU.US = os.path.join(tmp, "us")
    AU.sync_pack_config()
    with open(os.path.join(tmp, "us", "trader", "config.json")) as fh:
        pack = json.load(fh)
    check("6. auto_us -> trader-risk config: max_trades_per_day 0 and max_orders_per_day 0 (off); daily loss kept",
          pack.get("max_trades_per_day") == 0 and pack.get("max_orders_per_day") == 0
          and pack.get("max_daily_loss_usd") == cfg["accounts"]["US"]["daily_loss_limit"], pack)

    print("\n%d failed" % len(FAILS) if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
