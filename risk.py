#!/usr/bin/env python3
"""
risk.py - the Risk agent (owner, 20 Nov 2026): the ONE place that validates a proposed paper trade and sizes it.

The Broker (paper.execute_order) fills only an order that carries an approval issued here, for exactly these order
parameters, and only once. Nothing in this module executes anything.

    risk_check(req, cfg, led, now)   -> decision dict (APPROVED / REJECTED / REDUCE_SIZE / NEEDS_REVISION)
    setup_size(...) / setup_gate()   -> the scanner-setup pre-check paper.setup_decision runs before an order exists
    consume(approval, req, cfg)      -> the Broker's check: issued here, these parameters, not used before

The checks, their order and their messages are the ones paper.cmd_buy ran before this split (20 Nov 2026), so the
same orders pass and fail for the same reasons. Thresholds are read from the account config; where the code used a
fixed number, the config key falls back to that same number (nothing changes unless the key is set):
    max_fee_risk_frac  0.5   round-trip charges at the target must stay under this fraction of the risk
    min_fill_frac      0.25  a cash-limited size under this fraction of a normal position is skipped (dust)
    max_fee_r          0.25  scanner setups: charges over this many R are skipped (setup_decision)
    min_net_rr         None  net reward:risk (after charges and slippage) minimum; None = not enforced (research first)
Gross R:R is checked against min_reward_risk as before; the net R:R is always computed and reported.
"""
import hashlib
import itertools
import json
import math

import paper as P

DECISIONS = ("APPROVED", "REJECTED", "REDUCE_SIZE", "NEEDS_REVISION")
BINDING = ("symbol", "side", "order_type", "limit_price", "stop", "target", "qty", "lots", "price", "force",
           "allow_second", "setup_id", "client_order_id")
_ISSUED = {}                      # approval_id -> fingerprint, for approvals issued in this process and not used yet
_SEQ = itertools.count(1)


class RiskRejected(P.PaperError):
    """Risk did not approve: .decision is the Risk agent's full record."""

    def __init__(self, decision):
        super().__init__(decision.get("reason") or decision.get("decision"))
        self.decision = decision


def fingerprint(req, cfg):
    """The order parameters an approval is bound to (symbol resolved to its paper key, the rest as requested)."""
    try:
        m, t = P.parse_symbol(req.get("symbol"), cfg)
        sym = P.key(m, t)
    except P.PaperError:
        sym = str(req.get("symbol"))
    doc = {k: (sym if k == "symbol" else req.get(k)) for k in BINDING}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()


def _decision(verdict, req, now, reason=None, **f):
    d = {"agent": "risk", "decision": verdict, "setup_id": req.get("setup_id"),
         "client_order_id": req.get("client_order_id"), "ts": now.isoformat(),
         "inputs": {k: req.get(k) for k in BINDING}, "reason": reason}
    d.update(f)
    return d


def risk_check(req, cfg, led, now, quote=None, register=True):
    """Validate and size one proposed entry. req: the order request (paper.order_request). quote: the price to use
    (None: req["price"], else the live quote, fetched at the same point as before). Returns the decision dict; an
    APPROVED one carries approval_id + fingerprint (registered for the Broker unless register=False)."""
    try:
        return _check(req, cfg, led, now, quote, register)
    except P.PaperError as e:                  # a malformed request (symbol, stop / target spec): fix it and resend
        return _decision("NEEDS_REVISION", req, now, str(e))


def _check(req, cfg, led, now, quote, register):
    m, t = P.parse_symbol(req["symbol"], cfg)
    k = P.key(m, t)
    acc = P.acct_cfg(cfg, m)
    book = P.book_of(led, m)
    force = bool(req.get("force"))
    short = req.get("side", "long") == "short"
    rej = lambda verdict, msg, **f: _decision(verdict, req, now, msg, market=m, symbol=k,  # noqa: E731
                                               side="short" if short else "long", **f)
    if short and not acc.get("allow_short"):
        return rej("REJECTED", "short selling is not enabled for the %s account (allow_short in config)"
                   % P.account_of(m))
    kind = P.kind_of(m, t)
    lot = P.lot_of(m, t)
    fno_trade = kind != "equity"
    if any(p["key"] == k for p in led["open"]) and not req.get("allow_second"):
        return rej("REJECTED", "%s is already open; sell it first" % k)
    sess = P.session(m, now)
    if sess == "closed" and not force:
        return rej("REJECTED", "%s is closed right now (a paper fill at a stale price teaches nothing). "
                               "--force to do it anyway." % m)
    if acc.get("flat_by") and sess == "open" and P.past_flat_by(m, acc, now) and not force:
        return rej("REJECTED", "past your flat-by time (%s): no new intraday entries" % acc["flat_by"])
    if acc.get("risk_limits", False):   # off while paper testing (owner's decision); on before real money
        lost_today = -sum(c["pnl"] for c in P.today_closed(led, m, now) if c["pnl"] < 0)
        if lost_today >= acc["daily_loss_limit"]:
            return rej("REJECTED", "daily loss limit hit for %s (%s lost today of %s): done for the day"
                       % (P.account_of(m), P.money(m, lost_today), P.money(m, acc["daily_loss_limit"])))
        if len(P.trades_today(led, m, now)) >= acc["max_trades_per_day"]:
            return rej("REJECTED", "max %d trades per day reached for %s"
                       % (acc["max_trades_per_day"], P.account_of(m)))
        try:
            P.rulebook_guards(led, m, acc, now, short)
        except P.PaperError as e:
            return rej("REJECTED", str(e))

    if quote is None:
        if req.get("price") is not None:
            quote = float(req["price"])
        else:
            quote, qt = P.fetch_price(m, t)
            if sess == "open" and (now - qt).total_seconds() > 20 * 60:
                print("Note: the quote is %.0f minutes old (holiday, halt, or lagging data)."
                      % ((now - qt).total_seconds() / 60))
    quote = float(quote)
    slip_pct = float(acc.get("slippage_pct") or 0)
    entry = P.slipped(quote, not short, slip_pct)        # the expected simulated fill
    if req.get("stop") is None:
        return rej("NEEDS_REVISION", "a stop is required (price, a percent like 2%, orb-mid or orb-low)")
    stop = P.round_px(m, P.resolve_stop(req["stop"], entry, t, short), down=not short)
    if not short and stop >= entry:
        return rej("NEEDS_REVISION", "stop %s is not below the entry %s (long position; buy a PE or use --side short "
                                     "for a bearish view)" % (P.money(m, stop), P.money(m, entry)))
    if short and stop <= entry:
        return rej("NEEDS_REVISION", "stop %s is not above the entry %s (short position)"
                   % (P.money(m, stop), P.money(m, entry)))
    target = P.round_px(m, P.resolve_target(req.get("target"), entry, stop, short), down=short)
    if (not short and target <= entry) or (short and target >= entry):
        return rej("NEEDS_REVISION", "target %s is on the wrong side of the entry %s"
                   % (P.money(m, target), P.money(m, entry)))
    risk_ps = abs(entry - stop)
    reward_ps = abs(target - entry)
    rr = reward_ps / risk_ps
    prices = {"quote": quote, "entry": entry, "stop": stop, "target": target, "gross_rr": round(rr, 4)}
    if rr + 1e-9 < acc["min_reward_risk"] and not force:
        return rej("REJECTED", "reward:risk %.2f is under your minimum %.2f" % (rr, acc["min_reward_risk"]), **prices)

    max_loss = acc.get("max_loss_per_trade_fno", acc["max_loss_per_trade"]) if fno_trade else acc["max_loss_per_trade"]
    pos_pct = acc.get("max_position_pct_fno", acc["max_position_pct"]) if fno_trade else acc["max_position_pct"]
    equity = book["cash"] + sum(P.held_value(p) for p in led["open"] if P.account_of(p["market"]) == P.account_of(m))
    lev = P.margin_x(acc, m, kind)
    unit_cost = entry * acc.get("futures_margin_pct", 12) / 100 if kind == "futures" else entry / lev
    open_side, close_side = ("sell", "buy") if short else ("buy", "sell")  # a short sells first (STT), buys back
    fee_unit_stop = (P.charges(cfg, m, t, open_side, entry * lot) + P.charges(cfg, m, t, close_side, stop * lot)) / lot
    fee_unit_tgt = (P.charges(cfg, m, t, open_side, entry * lot) + P.charges(cfg, m, t, close_side, target * lot)) / lot
    slip_stop, slip_tgt = stop * slip_pct / 100.0, target * slip_pct / 100.0   # exits fill slip_pct worse too
    net_rr = (reward_ps - fee_unit_tgt - slip_tgt) / (risk_ps + fee_unit_stop + slip_stop)
    prices.update(net_rr=round(net_rr, 4), fee_unit_stop=fee_unit_stop, fee_unit_tgt=fee_unit_tgt,
                  slippage_pct=slip_pct, max_risk=max_loss)
    frac = float(acc.get("max_fee_risk_frac", 0.5))
    if fee_unit_tgt >= frac * risk_ps and not force:
        return rej("REJECTED", "stop too tight: charges (%s a unit round trip) are %.0f%% of the risk (%s a unit). "
                               "Widen the stop or skip the trade." % (P.money(m, fee_unit_tgt),
                                                                      100 * fee_unit_tgt / risk_ps,
                                                                      P.money(m, risk_ps)), **prices)
    if acc.get("min_net_rr") is not None and net_rr + 1e-9 < float(acc["min_net_rr"]) and not force:
        return rej("REJECTED", "net reward:risk %.2f (after charges and slippage) is under your minimum %.2f"
                   % (net_rr, float(acc["min_net_rr"])), **prices)
    caps = {
        "max loss per trade (%s)" % P.money(m, max_loss): max_loss / (risk_ps + fee_unit_stop),
        "position cap (%g%% of account%s)" % (pos_pct, " in margin" if kind == "futures" or lev > 1 else ""):
            equity * pos_pct / 100 / unit_cost,
        "cash" + (" (futures margin %g%%)" % acc.get("futures_margin_pct", 12) if kind == "futures" else
                  " (intraday margin, %gx)" % lev if lev > 1 else ""):
            book["cash"] / (unit_cost + fee_unit_stop),
    }
    limiter = min(caps, key=caps.get)
    q = caps[limiter]
    want = None
    if req.get("lots"):
        want = float(req["lots"]) * lot
    elif req.get("qty") is not None:
        want = float(req["qty"])
    if want is not None:
        if want > q + 1e-9:
            allowed = (math.floor(q / lot) * lot) if not P.MARKETS[m]["fractional"] else math.floor(q * 1e6) / 1e6
            return rej("REDUCE_SIZE", "%s %s breaks a limit: %s allows %s" % (
                "--lots" if req.get("lots") else "--qty", req["lots"] if req.get("lots") else req["qty"],
                limiter, ("%d lot(s)" % int(q // lot)) if lot > 1 else P.fmt_qty(m, q)), allowed_qty=allowed,
                limiter=limiter, **prices)
        q, limiter = want, "your --lots/--qty"
    q = math.floor(q * 1e6) / 1e6 if P.MARKETS[m]["fractional"] else math.floor(q / lot) * lot
    if q <= 0:
        one = (risk_ps + fee_unit_stop) * lot
        need = unit_cost * lot
        if lot > 1:
            return rej("REJECTED", "0 lots fit: one lot (%d) risks %s at the stop (max loss %s) and ties up %s "
                                   "(cash %s). Skip it, or change max_loss_per_trade_fno." % (
                                       lot, P.money(m, one), P.money(m, max_loss), P.money(m, need),
                                       P.money(m, book["cash"])), **prices)
        if limiter.startswith("cash"):
            return rej("REJECTED", "not enough free cash: %s free in the %s account (open positions tie up the rest)"
                       % (P.money(m, book["cash"]), P.account_of(m)), **prices)
        return rej("REJECTED", "0 units fit: the stop is %s away and your max loss is %s. "
                               "Tighten the stop or skip the trade." % (P.money(m, risk_ps), P.money(m, max_loss)),
                   **prices)
    full = min(v for kk, v in caps.items() if not kk.startswith("cash"))
    if want is None and limiter.startswith("cash") and q < float(acc.get("min_fill_frac", 0.25)) * full:
        # e.g. four open crypto shorts use the whole account: the fifth would be a dust position that only
        # uses up a "trade of the day" (2 Nov: ADA $0.15, HBAR $0.0001 shorts)
        return rej("REJECTED", "not enough free cash: %s free in the %s account buys %s, under a quarter of a normal "
                               "position (%s); skipped until a position closes" % (
                                   P.money(m, book["cash"]), P.account_of(m), P.fmt_qty(m, q),
                                   P.fmt_qty(m, full)), **prices)
    fp = fingerprint(req, cfg)
    aid = "RISK-%s-%d" % (hashlib.sha1(("%s|%s|%s" % (fp, now.isoformat(), id(req))).encode()).hexdigest()[:16],
                          next(_SEQ))
    d = rej("APPROVED", None, qty=q, limiter=limiter, kind=kind, lot=lot, lev=lev, unit_cost=unit_cost,
            margin=round(q * unit_cost, 2) if (kind == "futures" or lev > 1) else None,
            risk_at_stop=round((risk_ps + fee_unit_stop) * q, 6),
            entry_fee=P.charges(cfg, m, t, open_side, q * entry), approval_id=aid, fingerprint=fp, **prices)
    if register:
        _ISSUED[aid] = fp
    return d


def consume(approval, req, cfg):
    """The Broker's check before a fill. Raises PaperError unless the approval is an APPROVED decision issued here,
    bound to exactly these order parameters, and not used before. Marks it used."""
    if not isinstance(approval, dict) or approval.get("agent") != "risk":
        raise P.PaperError("no Risk approval: the Broker never executes an order Risk has not approved")
    if approval.get("decision") != "APPROVED":
        raise P.PaperError("Risk decision is %s, not APPROVED: not executed" % approval.get("decision"))
    aid = approval.get("approval_id")
    if fingerprint(req, cfg) != approval.get("fingerprint"):
        raise P.PaperError("order parameters changed after the Risk approval %s: not executed (revalidate with Risk)"
                           % aid)
    if aid not in _ISSUED:
        raise P.PaperError("Risk approval %s was already used or never issued by Risk: not executed" % aid)
    if _ISSUED[aid] != approval.get("fingerprint"):
        raise P.PaperError("Risk approval %s does not match what Risk issued: not executed" % aid)
    del _ISSUED[aid]


def setup_size(cfg, acc, market, symbol, entry, stop, target, short):
    """Scanner-setup pre-check sizing (paper.setup_decision, before an order exists): (qty, cost in R or None)."""
    risk = (stop - entry) if short else (entry - stop)
    # the position cap counts the intraday margin, like the paper buy: with $1,000 and 4x, a $300 stock fits;
    # without it every US stock above ~$250 was "0 units fit" (owner's audit, 18 Nov 2026)
    units = min(acc["max_loss_per_trade"] / risk,
                acc["capital"] * acc["max_position_pct"] / 100 / (entry / P.margin_x(acc, market)))
    qty = units if market == "CRYPTO" else int(units)
    cost = None
    if market in ("NSE", "BSE"):
        if qty >= 1:
            o, c = ("sell", "buy") if short else ("buy", "sell")
            cost = (P.charges(cfg, "NSE", symbol, o, qty * entry) + P.charges(cfg, "NSE", symbol, c, qty * target)) \
                / (qty * risk)
    else:
        cost = (entry + target) * float(acc.get("fee_pct") or 0) / 100 / risk
    return qty, cost


def setup_gate(acc, market, qty, risk, cost):
    """The pre-check's verdict: None (go on to the order) or the skip reason."""
    if qty <= 0 or (market != "CRYPTO" and qty < 1):
        return "0 units fit: the stop is %s away and the max loss is %s" % (round(risk, 6), acc["max_loss_per_trade"])
    cap = float(acc.get("max_fee_r", 0.25))
    if cost is not None and cost > cap:
        return "fees eat %.2fR of the trade (max %gR)" % (cost, cap)
    return None
