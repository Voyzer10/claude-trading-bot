#!/usr/bin/env python3
"""
agents.py - a Scanner setup taken through the agents (entry, exit, time machine, budget, risk) to the paper broker:
setup_decision returns the decision record for decisions.jsonl. Split out of paper.py on 18 Nov 2026; paper.py
re-exports these names (P.setup_decision etc.), and this file calls paper.<name> (cmd_buy, fetch_price, load_config ...)
at run time, so a test that swaps one of them still reaches this code.
"""
from datetime import datetime, timezone


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
        led = P.load_ledger(cfg)
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
            pos = P.cmd_buy(args, cfg, led)
        P.save_json(P.LEDGER, led)
    except P.PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    if version == "v4" and stop is not None:
        # the v4 plan on the underlying's own chart (owner, 17 Nov 2026): the option also exits when QQQ / Nifty
        # reaches the v4 stop or target, as the engine and the backtests do; the premium stop / target still count
        pos["underlying_plan"] = {"market": "US" if mk == "USOPT" else "NSE", "symbol": symbol, "side": s["side"],
                                  "stop": float(stop), "target": float(target) if target is not None else None}
        P.save_json(P.LEDGER, led)
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


def setup_account(cfg, market, symbol):
    """The account whose switches (scanner version, Trade Manager, budget) decide a Scanner setup on market:symbol:
    an index setup (Nifty / Bank Nifty) is an F&O trade (FNO), a QQQ / SPY / DIA setup a US F&O trade (USFNO), every
    other setup its market's own account."""
    accs = cfg["accounts"]
    acc = accs[P.MARKETS[market]["account"]] if market in P.MARKETS else accs["US"]
    if market in ("NSE", "BSE") and symbol.upper() in INDEX_UNDERLYINGS:
        return accs.get("FNO", acc)
    usf = accs.get("USFNO") or {}
    if market == "US" and symbol.upper() in [u.upper() for u in (usf.get("usopt_underlyings") or [])]:
        return usf
    return acc


def setup_decision(market, symbol, s, news=None, now_iso=None):
    """One of the owner's setups found by the Scanner (v3; smc_playbook.owner_setups dict), taken through the agents
    Entry (the candle close), Exit (stop, 2R or the v3 liquidity target, costs in R), Budget (size from this account's limits), Risk (costs <=
    0.25R, at least one unit), then the Broker: a paper trade at the live price with that stop and 2R target (the
    owner's decision for paper testing, 4 Nov 2026), or LOG ONLY when the account's trade_setups is off.
    Returns the decision record for decisions.jsonl."""
    rec = {"time": now_iso or datetime.now(P.IST).isoformat(), "symbol": "%s:%s" % (market, symbol),
           "setup": s["setup"], "scanner_v2": True, "steps": {}, "result": None}
    st = rec["steps"]
    st["1_scanner"] = {"scanner": s.get("scanner", P.DEFAULT_SCANNER), "setup": s["setup"], "setup_name": s.get("name"),
                       "side": s["side"], "liquidity": s.get("liquidity"), "bar_end": s.get("bar_end"),
                       "price": s["price"], **(s.get("details") or {})}
    st["2_news"] = news if news is not None else "not fetched for stock setups (hundreds a day)"

    def done(result, why):
        if rec.get("flipped_from"):
            why = "flip, closed %s first: %s" % (rec["flipped_from"], why)
        rec["result"], rec["why"] = result, why
        return rec

    # Scanner v3's sweep reversal carries its own target (the opposing liquidity); the older setups use 2R
    cfg = P.load_config()
    acc = setup_account(cfg, market, symbol)
    fno_acc = cfg["accounts"].get("FNO", acc)
    usf_acc = cfg["accounts"].get("USFNO") or {}
    us_opt = market == "US" and symbol.upper() in [u.upper() for u in (usf_acc.get("usopt_underlyings") or [])]
    version = acc.get("scanner_version", P.DEFAULT_SCANNER)
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
        chart = P.key(market, symbol)
        led = P.load_ledger(cfg)
        opened, closed = V4.chart_state(led, chart)
        signal = P._iso(s.get("v4_signal_at"))
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
                        px, _ = P.fetch_price(o["market"], o["symbol"])
                        with contextlib.redirect_stdout(io.StringIO()):
                            done_flip.append(P.close_position(led, cfg, o, px, "v4 flip: today's opposite BOS setup (%s)"
                                                            % s["side"], datetime.now(timezone.utc)))
                        P.save_json(P.LEDGER, led)
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
        exited = P._iso(closed.get("exit_time")) if closed else None
        if signal is None or (not flipped and exited is not None and signal <= exited):
            return done("skipped", "v4: no fresh confirmed signal after the last exit")
        if s["setup"].startswith("v4_secondary_"):
            details = s.get("details") or {}
            primary = P._iso(details.get("primary_at"))
            tap = P._iso(details.get("tapped_at"))
            if (not closed or closed.get("setup") != "v4_primary_" + s["side"]
                    or primary is None or primary != P._iso(closed.get("v4_signal_at"))
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
    # the same caps as cmd_buy: the max loss, and the position cap on the cash a unit ties up (intraday margin)
    units = min(acc["max_loss_per_trade"] / risk,
                acc["capital"] * acc["max_position_pct"] / 100 / (entry / P.margin_x(acc, market)))
    qty = units if market == "CRYPTO" else int(units)
    cost = None
    if market in ("NSE", "BSE"):
        if qty >= 1:
            o, c = ("sell", "buy") if short else ("buy", "sell")
            cost = (P.charges(cfg, "NSE", symbol, o, qty * entry) + P.charges(cfg, "NSE", symbol, c, qty * target)) / (qty * risk)
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
        led = P.load_ledger(cfg)
    args = type("A", (), {"symbol": "%s:%s" % (market, symbol), "stop": str(stop), "target": str(target), "qty": None,
                          "price": None, "note": "scanner %s: %s" % (version, name), "force": False,
                          "side": "short" if short else "long", "setup": s["setup"], "setup_name": name,
                          "scanner": version, "liquidity": s.get("liquidity"),
                          "entry_reason": "found by Scanner %s; entry on the close of the %s candle, planned R:R %.1f" % (
                              version, (s.get("bar_end") or "")[11:16] or "last", abs(target - entry) / risk), **v4_fields})()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            pos = P.cmd_buy(args, cfg, led)
        P.save_json(P.LEDGER, led)
    except P.PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    st["6-8_budget_risk_broker"] = {"verdict": "PASS, paper %s filled" % ("short" if short else "buy"), "qty": pos["qty"],
                                    "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
                                    "max_loss": round(abs(pos["entry"] - pos["stop"]) * pos["qty"] + pos.get("entry_fee", 0), 2),
                                    "report": buf.getvalue().strip().splitlines()}
    st["9_alerts"] = "live.py checks stop %s / target %s every cycle" % (pos["stop"], pos["target"])
    return done("PAPER SHORT" if short else "PAPER BUY", "%s @ %s, stop %s, target %s (Scanner %s: %s)" % (
        P.fmt_qty(market, pos["qty"]), pos["entry"], pos["stop"], pos["target"], version, name))


import paper as P  # noqa: E402  (last: paper imports this module's names at its end)
