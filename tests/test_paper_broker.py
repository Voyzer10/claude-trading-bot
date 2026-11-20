#!/usr/bin/env python3
"""The paper broker is PAPER ONLY (owner, 20 Nov 2026). Offline: every network call is blocked and recorded.

  1. an approved order -> a paper order fills (PAPER_FILLED, journalled, a simulated position)
  2. a risk-rejected order -> nothing fills (PAPER_REJECTED, ledger unchanged)
  3. a live-mode request (order, environment, config, US ticket config) -> rejected, nothing fills
  4. the paper simulator unavailable (ledger, journal) -> fail closed, nothing fills
  5. a duplicate order -> not filled twice
  6. an exit -> closes only that simulated position (and only one that is in the ledger)
  7. no broker order endpoint is ever called: no network at all during 1-6; the data clients refuse order endpoints;
     no module builds an order request

    python tests/test_paper_broker.py
"""
import copy
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []
NET = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def _blocked(*a, **k):
    NET.append(repr(a)[:200])
    raise OSError("network blocked in this test")


socket.socket.connect = _blocked                 # every TCP connection, whatever library opens it
socket.create_connection = _blocked
urllib.request.urlopen = _blocked


def order(**kw):
    base = {"symbol": "CRYPTO:BTC", "price": 50000.0, "stop": "49500", "target": "51000", "qty": None, "lots": None,
            "force": False, "side": "long", "note": "test"}
    base.update(kw)
    return type("A", (), base)()


def orders():
    return P.read_orders(1000)


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    os.chdir(tmp)
    os.environ.pop("TRADER_EXECUTION_MODE", None)
    import paper as P
    cfg = P.load_config()
    led = P.load_ledger(cfg)
    cash0 = led["accounts"]["CRYPTO"]["cash"]

    # 1. approved order
    pos = P.cmd_buy(order(), cfg, led)
    o = orders()[-1]
    check("1. approved order: a paper fill (PAPER_FILLED, mode PAPER, journalled, simulated position)",
          o["status"] == "PAPER_FILLED" and o["mode"] == "PAPER" and o["intent"] == "ENTRY" and o["side"] == "BUY"
          and o["qty"] == pos["qty"] > 0 and o["fill_price"] == 50000.0 and o["order_type"] == "MARKET"
          and o["fees"] > 0 and "ts" in o and pos["execution_mode"] == "PAPER" and pos["order_id"] == o["order_id"]
          and len(led["open"]) == 1 and led["accounts"]["CRYPTO"]["cash"] < cash0, (o, pos))

    # 2. risk-rejected orders
    snap = copy.deepcopy(led)
    n0 = len(orders())
    try:
        P.cmd_buy(order(symbol="CRYPTO:ETH", price=3000.0, stop="2990", target="3004"), cfg, led)
        rej = None
    except P.PaperError as e:
        rej = str(e)
    o = orders()[-1]
    check("2. risk-rejected (reward:risk under the minimum): PAPER_REJECTED, nothing filled, ledger unchanged",
          rej and "reward:risk" in rej and o["status"] == "PAPER_REJECTED" and o["fill_price"] is None
          and len(orders()) == n0 + 1 and led == snap, (rej, o))
    cfg2 = copy.deepcopy(cfg)
    cfg2["accounts"]["CRYPTO"].update(risk_limits=True, daily_loss_limit=10)
    led["closed"].append({"key": "CRYPTO:SOL", "market": "CRYPTO", "pnl": -50.0, "r": -1.0,
                          "exit_time": datetime.now(timezone.utc).isoformat(),
                          "exit_date": datetime.now(timezone.utc).date().isoformat()})
    snap = copy.deepcopy(led)
    try:
        P.cmd_buy(order(symbol="CRYPTO:ETH", price=3000.0, stop="2950", target="3100"), cfg2, led)
        rej = None
    except P.PaperError as e:
        rej = str(e)
    check("   risk-rejected (daily loss limit hit): PAPER_REJECTED, nothing filled",
          rej and "daily loss limit" in rej and orders()[-1]["status"] == "PAPER_REJECTED" and led == snap, rej)
    led["closed"].pop()

    # 3. live-mode requests
    snap = copy.deepcopy(led)
    for label, kw in (("order mode LIVE", {"mode": "LIVE"}), ("order execution_mode live", {"execution_mode": "live"}),
                      ("order mode REAL", {"mode": "real"})):
        try:
            P.cmd_buy(order(symbol="CRYPTO:ETH", price=3000.0, stop="2950", target="3100", **kw), cfg, led)
            got = None
        except P.PaperModeError as e:
            got = str(e)
        check("3. live-mode request (%s): rejected, nothing filled" % label,
              got and orders()[-1]["status"] == "PAPER_REJECTED" and led == snap, got)
    os.environ["TRADER_EXECUTION_MODE"] = "LIVE"
    try:
        P.cmd_buy(order(symbol="CRYPTO:ETH", price=3000.0, stop="2950", target="3100"), cfg, led)
        got = None
    except P.PaperModeError as e:
        got = str(e)
    try:
        P.close_position(led, cfg, led["open"][0], 50500.0, "test", datetime.now(timezone.utc))
        got_exit = None
    except P.PaperModeError as e:
        got_exit = str(e)
    os.environ.pop("TRADER_EXECUTION_MODE")
    check("   TRADER_EXECUTION_MODE=LIVE: every order refused, entries and exits (fail closed)",
          got and got_exit and led == snap, (got, got_exit))
    cfg3 = dict(cfg, execution_mode="live")
    try:
        P.cmd_buy(order(symbol="CRYPTO:ETH", price=3000.0, stop="2950", target="3100"), cfg3, led)
        got = None
    except P.PaperModeError as e:
        got = str(e)
    check("   config execution_mode=live: refused", got and led == snap, got)
    sys.path.insert(0, os.path.join(ROOT, "us", "trader-broker"))
    import ticket as TK
    with open("broker_cfg.json", "w") as fh:
        json.dump({"paper": False, "broker": "alpaca"}, fh)
    try:
        TK.paper_config("broker_cfg.json")
        got = None
    except TK.TicketError as e:
        got = str(e)
    with open("broker_cfg.json", "w") as fh:
        json.dump({"paper": True}, fh)
    check("   US trader-broker ticket config \"paper\": false: refused; \"paper\": true: allowed",
          got and "live trading is not allowed" in got and TK.paper_config("broker_cfg.json")["paper"] is True, got)

    # 4. the simulator unavailable
    try:
        P.cmd_buy(order(symbol="CRYPTO:ETH", price=3000.0, stop="2950", target="3100"), cfg, {"open": None})
        got = None
    except P.PaperModeError as e:
        got = str(e)
    check("4. paper simulator unavailable (malformed ledger): fail closed", got and "unavailable" in got, got)
    keep = P.ORDERS
    open("not_a_dir", "w").close()
    P.ORDERS = os.path.join("not_a_dir", "orders.jsonl")      # the journal can not be written
    try:
        P.cmd_buy(order(symbol="CRYPTO:ETH", price=3000.0, stop="2950", target="3100"), cfg, led)
        got = None
    except P.PaperModeError as e:
        got = str(e)
    P.ORDERS = keep
    check("   order journal not writable: fail closed, nothing filled", got and led == snap, got)
    real = P.journal_order

    def broken(rec):
        if rec["status"] == "PAPER_FILLED":
            raise OSError("disk full")
        return real(rec)
    P.journal_order = broken
    try:
        P.cmd_buy(order(symbol="CRYPTO:ETH", price=3000.0, stop="2950", target="3100"), cfg, led)
        got = None
    except P.PaperModeError as e:
        got = str(e)
    P.journal_order = real
    check("   the fill's journal line fails: the ledger is not touched (journal first, then the ledger)",
          got and led == snap, got)

    # 5. duplicates
    a = order(symbol="CRYPTO:ETH", price=3000.0, stop="2950", target="3100", client_order_id="agent-1:ETH:0930")
    P.cmd_buy(a, cfg, led)
    n_open = len(led["open"])
    try:
        P.cmd_buy(a, cfg, led)
        got = None
    except P.PaperError as e:
        got = str(e)
    check("5. duplicate order (same client_order_id): not filled twice",
          got and "duplicate" in got and len(led["open"]) == n_open
          and sum(1 for o in orders() if o.get("client_order_id") == "agent-1:ETH:0930"
                  and o["status"] == "PAPER_FILLED") == 1, got)
    v4 = dict(symbol="CRYPTO:SOL", price=150.0, stop="147", target="156", v4_chart="CRYPTO:SOL",
              v4_signal_at="2026-11-20T10:05:00+00:00")
    P.cmd_buy(order(**v4), cfg, led)
    try:
        P.cmd_buy(order(allow_second=True, **v4), cfg, led)
        got = None
    except P.PaperError as e:
        got = str(e)
    check("   duplicate scanner trade (same chart, side, signal candle; even with allow_second): not filled twice",
          got and "duplicate" in got and sum(1 for p in led["open"] if p["symbol"] == "SOL") == 1, got)

    # 6. exits
    btc = next(p for p in led["open"] if p["symbol"] == "BTC")
    others = [copy.deepcopy(p) for p in led["open"] if p is not btc]
    cash = led["accounts"]["CRYPTO"]["cash"]
    rec = P.close_position(led, cfg, btc, 50500.0, "test exit", datetime.now(timezone.utc))
    o = orders()[-1]
    check("6. exit: closes only the simulated BTC position (PAPER_FILLED SELL), the others untouched",
          o["status"] == "PAPER_FILLED" and o["intent"] == "EXIT" and o["side"] == "SELL" and o["mode"] == "PAPER"
          and o["symbol"] == "CRYPTO:BTC" and all(p["symbol"] != "BTC" for p in led["open"])
          and led["open"] == others and rec["exit"] == 50500.0 and led["accounts"]["CRYPTO"]["cash"] > cash, o)
    try:
        P.close_position(led, cfg, btc, 50500.0, "again", datetime.now(timezone.utc))
        got = None
    except P.PaperError as e:
        got = str(e)
    fake = dict(others[0], key="CRYPTO:DOGE", symbol="DOGE")
    try:
        P.close_position(led, cfg, fake, 0.1, "not ours", datetime.now(timezone.utc))
        got2 = None
    except P.PaperError as e:
        got2 = str(e)
    check("   a second exit of the same position, or a position not in the paper ledger: refused, nothing closed",
          got and got2 and led["open"] == others, (got, got2))
    cfg4 = copy.deepcopy(cfg)
    cfg4["accounts"]["CRYPTO"]["slippage_pct"] = 0.1
    p2 = P.cmd_buy(order(symbol="CRYPTO:ADA", price=1.0, stop="0.97", target="1.06"), cfg4, led)
    o = orders()[-1]
    check("   slippage_pct 0.1: the buy fills 0.1% above the quote and the journal shows it",
          abs(p2["entry"] - 1.001) < 1e-9 and o["quote"] == 1.0 and o["slippage"] > 0, o)
    try:
        P.cmd_buy(order(symbol="CRYPTO:XRP", price=2.0, stop="1.9", target="2.3", order_type="limit",
                        limit_price=1.95), cfg, led)
        got = None
    except P.PaperCancelled as e:
        got = str(e)
    check("   limit order above the market (buy limit 1.95, quote 2.00): PAPER_CANCELLED, nothing filled",
          got and orders()[-1]["status"] == "PAPER_CANCELLED" and not any(p["symbol"] == "XRP" for p in led["open"]),
          got)
    p3 = P.cmd_buy(order(symbol="CRYPTO:XRP", price=2.0, stop="1.9", target="2.3", order_type="limit",
                         limit_price=2.05), cfg, led)
    check("   marketable limit order: PAPER_FILLED in full at the quote",
          orders()[-1]["status"] == "PAPER_FILLED" and orders()[-1]["order_type"] == "LIMIT" and p3["entry"] == 2.0)

    # 7. no broker order endpoint
    check("7. no network call at all during 1-6 (every socket blocked)", not NET, NET)
    import kite
    import alpaca
    import coinbase
    refused = (not kite._allowed("POST", "/orders/regular") and not kite._allowed("PUT", "/orders/regular/1")
               and not kite._allowed("DELETE", "/orders/regular/1")
               and not alpaca.allowed("https://paper-api.alpaca.markets/v2/orders", "POST")
               and not alpaca.allowed("https://api.alpaca.markets/v2/orders", "POST")
               and not alpaca.allowed("https://data.alpaca.markets/v2/orders", "POST")
               and not coinbase.allowed("https://api.exchange.coinbase.com/orders", "POST"))
    check("   the broker / data clients refuse every order endpoint (Kite, Alpaca live and paper, Coinbase)", refused)
    pat = re.compile(r"place_order|create_order|modify_order|submit_order|/v2/orders|/orders/regular|"
                     r"exchange/v1/orders|api\.binance|api\.coindcx\.com/exchange/v1/orders")
    hits = []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in ("node_modules", ".next", ".git", "tests", "__pycache__")]
        for f in files:
            if f.endswith(".py"):
                with open(os.path.join(d, f), encoding="utf-8", errors="ignore") as fh:
                    for n, line in enumerate(fh, 1):
                        if pat.search(line):
                            hits.append("%s:%d" % (os.path.relpath(os.path.join(d, f), ROOT), n))
    check("   no Python module builds a broker order request (place/create/modify/submit order, order paths)",
          not hits, hits)
    with open(os.path.join(ROOT, "us", "trader-broker", "ticket.py"), encoding="utf-8") as fh:
        src = fh.read()
    check("   the US ticket tool has no network code (it only writes tickets and logs)",
          not re.search(r"^\s*(import|from)\s+(urllib|http|requests|socket)", src, re.M))
    import dashboard_push as DP
    shown = DP._paper_orders()
    check("   the dashboard snapshot gets the journal: every order labelled mode PAPER",
          shown and all(o["mode"] == "PAPER" and o["status"] in P.ORDER_STATUSES for o in shown))

    os.chdir(ROOT)
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("all checks passed")
