#!/usr/bin/env python3
"""
us_options.py - US F&O (owner, 13 Nov 2026): a Scanner v4 setup on QQQ (Nasdaq-100) or SPY (S&P 500) turned into
the at-the-money option to BUY, paper only: a call for a long setup, a put for a short one. The same idea as
fno_stock.py for India, with Alpaca's options data (paper key, market data only, the free "indicative" feed):

  * the contract: nearest weekly expiry at least MIN_DAYS calendar days away, the strike nearest the ETF price;
  * the premium: the contract's quote midpoint (else its last trade);
  * implied volatility from that premium (Black-Scholes), then
    premium stop   = the option's value with the ETF at the setup's stop,
    premium target = the option's value with the ETF at the setup's target.

Paper key: USOPT:<OCC symbol>, e.g. USOPT:QQQ261120C00500000 (QQQ, 20 Nov 2026, call, strike 500). One contract =
100 shares. Nothing here places an order: paper.py records the paper trade.
"""
import re
from datetime import date, datetime, timedelta, timezone

import fno as F

MIN_DAYS = 2            # calendar days to expiry at least (owner: "India jaisa, ATM, weekly")
MAX_DAYS = 10           # weekly: look no further than this
MULTIPLIER = 100
UNDERLYINGS = ("QQQ", "SPY")
RATE = 0.045            # US risk-free-ish rate for the model
OCC = re.compile(r"^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")


class NoOption(Exception):
    """The setup can not be traded as an option (why in the message)."""


def parse(occ):
    """OCC symbol -> {"underlying", "expiry" (date), "kind" ("CE" call / "PE" put), "strike"}."""
    m = OCC.match((occ or "").upper())
    if not m:
        raise NoOption("not an OCC option symbol: %r (e.g. QQQ261120C00500000)" % occ)
    und, yy, mm, dd, cp, k = m.groups()
    return {"underlying": und, "expiry": date(2000 + int(yy), int(mm), int(dd)), "kind": "CE" if cp == "C" else "PE",
            "strike": int(k) / 1000}


def occ_name(und, expiry, kind, strike):
    return "%s%s%s%08d" % (und.upper(), expiry.strftime("%y%m%d"), "C" if kind == "CE" else "P", round(strike * 1000))


def et_offset(utc):
    import paper as P
    return P.us_offset(utc)


def years_to(expiry, now_utc):
    """Years from now to 16:00 New York time on the expiry day (at least a few minutes)."""
    close = datetime(expiry.year, expiry.month, expiry.day, 16, 0)
    close_utc = (close - et_offset(datetime(expiry.year, expiry.month, expiry.day, 17, tzinfo=timezone.utc))
                 ).replace(tzinfo=timezone.utc)
    return max((close_utc - now_utc).total_seconds(), 600) / (365 * 24 * 3600)


def implied_vol(price, spot, strike, years, kind):
    lo, hi = 0.01, 3.0
    if price <= F.bs(spot, strike, years, lo, kind, RATE)[0]:
        return lo
    for _ in range(60):
        mid = (lo + hi) / 2
        if F.bs(spot, strike, years, mid, kind, RATE)[0] > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def premium_of(rec):
    """The contract's price: the quote midpoint, else the last trade."""
    p = rec.get("mid") or rec.get("last")
    return float(p) if p else None


def price(occ):
    """(premium, time) of one contract from Alpaca, or None."""
    import alpaca as A
    if not A.configured():
        return None
    rec = A.option_snapshots([occ]).get(occ.upper())
    p = premium_of(rec or {})
    if not p:
        return None
    t = rec.get("t")
    return p, datetime.fromtimestamp(t, timezone.utc) if t else datetime.now(timezone.utc)


def plan(symbol, setup, now=None, chain=None):
    """{"name", "kind", "premium", "stop", "target", "lot", "iv", "delta", "expiry", "strike"} for the option of one
    setup on QQQ / SPY, or NoOption."""
    now = now or datetime.now(timezone.utc)
    und = symbol.upper()
    if und not in UNDERLYINGS:
        raise NoOption("US F&O trades only %s" % ", ".join(UNDERLYINGS))
    side = setup["side"]
    kind = "CE" if side == "long" else "PE"
    spot, stop, target = float(setup["price"]), float(setup["stop"]), float(setup.get("target") or setup["target_2r"])
    today = (now + et_offset(now)).date()
    if chain is None:
        import alpaca as A
        if not A.configured():
            raise NoOption("no Alpaca paper key: no US option prices")
        try:
            chain = A.option_chain(und, "call" if kind == "CE" else "put",
                                   (today + timedelta(days=MIN_DAYS)).isoformat(),
                                   (today + timedelta(days=MAX_DAYS)).isoformat(),
                                   round(spot * 0.97, 2), round(spot * 1.03, 2))
        except Exception as e:
            raise NoOption("Alpaca options chain for %s: %s" % (und, str(e)[:160]))
    legs = []
    for rec in chain:
        try:
            c = parse(rec["symbol"])
        except NoOption:
            continue
        days = (c["expiry"] - today).days
        if c["underlying"] == und and c["kind"] == kind and MIN_DAYS <= days <= MAX_DAYS and premium_of(rec):
            legs.append((c, rec))
    if not legs:
        raise NoOption("%s: no priced %s expiring in %d-%d days" % (und, "call" if kind == "CE" else "put",
                                                                    MIN_DAYS, MAX_DAYS))
    exp = min(c["expiry"] for c, _ in legs)
    c, rec = min(((c, r) for c, r in legs if c["expiry"] == exp), key=lambda x: abs(x[0]["strike"] - spot))
    premium = premium_of(rec)
    years = years_to(c["expiry"], now)
    iv = implied_vol(premium, spot, c["strike"], years, kind)
    p_stop = F.bs(stop, c["strike"], years, iv, kind, RATE)[0]
    p_target = F.bs(target, c["strike"], years, iv, kind, RATE)[0]
    delta = F.bs(spot, c["strike"], years, iv, kind, RATE)[1]
    if p_stop >= premium - 0.01 or p_target <= premium + 0.01:
        raise NoOption("%s: the ETF's stop / target move is too small for the option (premium %.2f)" % (rec["symbol"], premium))
    return {"name": rec["symbol"], "kind": kind, "premium": round(premium, 2), "stop": round(max(0.01, p_stop), 2),
            "target": round(p_target, 2), "lot": MULTIPLIER, "iv": round(iv, 4), "delta": round(delta, 3),
            "expiry": c["expiry"].isoformat(), "strike": c["strike"], "bid": rec.get("bid"), "ask": rec.get("ask")}
