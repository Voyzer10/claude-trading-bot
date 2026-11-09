#!/usr/bin/env python3
"""
fno_stock.py - a Scanner setup on an F&O stock, turned into the at-the-money option to BUY (paper only):
a call for a long setup, a put for a short one. Same idea as research_fno_sv4.py (the backtest), with real
Zerodha data instead of the model:

  * the contract: nearest expiry at least MIN_DAYS away, the strike nearest the stock price (Kite's own lists);
  * the premium: Zerodha's live price for that contract;
  * implied volatility from that premium (Black-Scholes, solved), then
    premium stop   = the option's value with the stock at the setup's stop,
    premium target = the option's value with the stock at the setup's target.

Needs Zerodha connected today. Nothing here places an order: paper.py records the paper trade.
"""
from datetime import datetime, timezone

import fno as F

MIN_DAYS = 3


class NoOption(Exception):
    """The setup can not be traded as an option (why in the message)."""


def implied_vol(price, spot, strike, years, kind):
    lo, hi = 0.01, 3.0
    if price <= F.bs(spot, strike, years, lo, kind)[0]:
        return lo
    for _ in range(60):
        mid = (lo + hi) / 2
        if F.bs(spot, strike, years, mid, kind)[0] > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def plan(symbol, setup, now=None, kite=None):
    """{"name", "kind", "premium", "stop", "target", "lot", "iv", "delta", "expiry", "strike"} for the option of
    one setup on `symbol` (an NSE stock), or NoOption."""
    now = now or datetime.now(timezone.utc)
    if kite is None:
        try:
            import kite as K
            kite = K if K.connected() else None
        except Exception:
            kite = None
    if kite is None:
        raise NoOption("Zerodha is not connected today: no stock option prices")
    und = symbol.upper()
    if und not in kite.fno_underlyings():
        raise NoOption("%s has no F&O on NSE" % und)
    side = setup["side"]
    kind = "CE" if side == "long" else "PE"
    spot, stop, target = float(setup["price"]), float(setup["stop"]), float(setup.get("target") or setup["target_2r"])
    today = now.astimezone(F.IST).date()
    chain = [c for c in kite.fno_chain(und) if c["type"] == kind]
    exps = sorted({c["expiry"] for c in chain if (datetime.fromisoformat(c["expiry"]).date() - today).days >= MIN_DAYS})
    if not exps:
        raise NoOption("%s: no option expiry %d+ days away" % (und, MIN_DAYS))
    legs = [c for c in chain if c["expiry"] == exps[0]]
    leg = min(legs, key=lambda c: abs(c["strike"] - spot))
    name = kite.paper_name(leg, und)
    key = "NFO:" + name
    q = kite.quotes([key]).get(key)
    if not q:
        raise NoOption("no Zerodha price for %s" % name)
    tick = kite.tick_price(key)
    premium = float(tick[0] if tick else q[0])
    expiry = datetime.fromisoformat(leg["expiry"]).date()
    years = F.years_to(expiry, now)
    iv = implied_vol(premium, spot, leg["strike"], years, kind)
    p_stop = F.bs(stop, leg["strike"], years, iv, kind)[0]
    p_target = F.bs(target, leg["strike"], years, iv, kind)[0]
    delta = F.bs(spot, leg["strike"], years, iv, kind)[1]
    if p_stop >= premium - 0.05 or p_target <= premium + 0.05:
        raise NoOption("%s: the stock's stop / target move is too small for the option (premium %.2f)" % (name, premium))
    return {"name": name, "kind": kind, "premium": round(premium, 2), "stop": round(max(0.05, p_stop), 2),
            "target": round(p_target, 2), "lot": leg["lot"], "iv": round(iv, 4), "delta": round(delta, 3),
            "expiry": leg["expiry"], "strike": leg["strike"]}
