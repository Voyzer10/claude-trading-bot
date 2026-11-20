#!/usr/bin/env python3
"""The Risk agent (risk.py) and mandatory Risk approval at the paper Broker (paper.execute_order), owner 20 Nov 2026.
Offline: every network call is blocked and recorded.

  approval binding        an APPROVED decision is bound to its exact order parameters; the fill carries its ids
  duplicate approvals     an approval executes once; a second approval for the same order id does not fill twice
  rejected approvals      REJECTED / REDUCE_SIZE / NEEDS_REVISION, a forged approval or none: never executed
  modified parameters     any change (stop, target, qty, side, symbol, setup id) after approval: not executed
  fill-price revalidation a different fill price must pass Risk again at the approved size, else not executed
  simulator failures      malformed ledger / journal down: nothing executed, ledger unchanged
  decisions               gross and net R:R, REDUCE_SIZE / NEEDS_REVISION, configurable thresholds with the old
                          numbers as defaults, the setup id format, the pre-check messages unchanged

    python tests/test_risk_gate.py
"""
import copy
import os
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


socket.socket.connect = _blocked
socket.create_connection = _blocked
urllib.request.urlopen = _blocked


def args(**kw):
    base = {"symbol": "CRYPTO:BTC", "price": 50000.0, "stop": "49500", "target": "51000", "qty": None, "lots": None,
            "force": False, "side": "long", "note": "test", "setup_id": "CRYPTO:BTC:long:2026-11-20T09:00:00+00:00:"
            "2026-11-20T09:30:00+00:00"}
    base.update(kw)
    return type("A", (), base)()


def refused(fn):
    try:
        fn()
        return None
    except P.PaperError as e:
        return str(e) or type(e).__name__


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    os.chdir(tmp)
    os.environ.pop("TRADER_EXECUTION_MODE", None)
    import paper as P
    import risk as R
    cfg = P.load_config()
    led = P.load_ledger(cfg)
    now = datetime.now(timezone.utc)

    # approval binding
    req = P.order_request(args(), cid="t-1")
    d = R.risk_check(req, cfg, led, now)
    check("approval: APPROVED with an approval id, fingerprint, size, gross and net R:R, fees and max risk",
          d["decision"] == "APPROVED" and d["approval_id"].startswith("RISK-") and len(d["fingerprint"]) == 64
          and d["qty"] > 0 and d["gross_rr"] == 2.0 and d["net_rr"] < d["gross_rr"] and d["entry_fee"] > 0
          and d["max_risk"] == cfg["accounts"]["CRYPTO"]["max_loss_per_trade"] and d["setup_id"] == req["setup_id"]
          and d["risk_at_stop"] <= d["max_risk"] + 1e-9, d)
    pos = P.execute_order(req, d, cfg, led, now)
    o = P.read_orders()[-1]
    check("   the Broker fills exactly the approved order: qty, entry, stop, target; ids carried to the position "
          "and the journal (setup id, trade id = order id, approval id)",
          pos["qty"] == d["qty"] and pos["entry"] == d["entry"] and pos["stop"] == d["stop"]
          and pos["target"] == d["target"] and pos["setup_id"] == req["setup_id"] and pos["trade_id"] == o["order_id"]
          and pos["risk"]["approval_id"] == d["approval_id"] and o["risk_approval_id"] == d["approval_id"]
          and o["setup_id"] == req["setup_id"] and o["status"] == "PAPER_FILLED", (pos, o))
    rec = P.close_position(led, cfg, pos, 50500.0, "test", now)
    o = P.read_orders()[-1]
    check("   the exit carries the same trade id and setup id",
          o["intent"] == "EXIT" and o["trade_id"] == pos["trade_id"] and o["setup_id"] == req["setup_id"]
          and rec["trade_id"] == pos["trade_id"], o)

    # duplicate approvals
    snap = copy.deepcopy(led)
    got = refused(lambda: P.execute_order(req, d, cfg, led, now))
    check("duplicate: the same approval a second time is refused (used), nothing filled",
          got and ("already used" in got or "duplicate" in got) and led == snap, got)
    req2 = P.order_request(args(symbol="CRYPTO:ETH", price=3000.0, stop="2950", target="3100"), cid="t-2")
    d2a, d2b = R.risk_check(req2, cfg, led, now), R.risk_check(req2, cfg, led, now)
    P.execute_order(req2, d2a, cfg, led, now)
    n = len(led["open"])
    got = refused(lambda: P.execute_order(req2, d2b, cfg, led, now))
    check("   two approvals for the same client order id: the second is refused as a duplicate order",
          got and "duplicate" in got and len(led["open"]) == n, got)

    # rejected approvals
    snap = copy.deepcopy(led)
    bad = P.order_request(args(symbol="CRYPTO:SOL", price=150.0, stop="149", target="150.4"), cid="t-3")
    dr = R.risk_check(bad, cfg, led, now)
    got = refused(lambda: P.execute_order(bad, dr, cfg, led, now))
    check("rejected: a REJECTED decision (reward:risk) is never executed",
          dr["decision"] == "REJECTED" and "reward:risk" in dr["reason"] and got and led == snap, (dr, got))
    big = P.order_request(args(symbol="CRYPTO:SOL", price=150.0, stop="147", target="156", qty=1000), cid="t-4")
    dz = R.risk_check(big, cfg, led, now)
    got = refused(lambda: P.execute_order(big, dz, cfg, led, now))
    check("   REDUCE_SIZE (asked 1000, the limits allow less) is never executed, and Risk never sizes up",
          dz["decision"] == "REDUCE_SIZE" and 0 < dz["allowed_qty"] < 1000 and got and led == snap, (dz, got))
    nostop = P.order_request(args(symbol="CRYPTO:SOL", price=150.0, stop=None, target="156"), cid="t-5")
    dn = R.risk_check(nostop, cfg, led, now)
    check("   NEEDS_REVISION (no stop) is never executed",
          dn["decision"] == "NEEDS_REVISION" and refused(lambda: P.execute_order(nostop, dn, cfg, led, now))
          and led == snap, dn)
    good = P.order_request(args(symbol="CRYPTO:SOL", price=150.0, stop="147", target="156"), cid="t-6")
    forged = dict(R.risk_check(good, cfg, led, now, register=False), approval_id="RISK-forged-1")
    check("   a forged approval (looks APPROVED, never issued by Risk) is refused",
          "never issued" in (refused(lambda: P.execute_order(good, forged, cfg, led, now)) or "") and led == snap)
    check("   no approval at all is refused",
          "no Risk approval" in (refused(lambda: P.execute_order(good, None, cfg, led, now)) or "") and led == snap)
    fake = R.risk_check(good, cfg, led, now)
    fake["decision"] = "REJECTED"
    check("   an issued approval whose decision was edited is refused",
          refused(lambda: P.execute_order(good, fake, cfg, led, now)) and led == snap)

    # modified order parameters
    d6 = R.risk_check(good, cfg, led, now)
    for field, val in (("stop", "140"), ("target", "170"), ("qty", 1), ("side", "short"), ("symbol", "CRYPTO:ADA"),
                       ("setup_id", "other"), ("price", 151.0), ("force", True)):
        mod = dict(good, **{field: val})
        got = refused(lambda: P.execute_order(mod, d6, cfg, led, now))
        check("modified after approval: %s changed -> not executed" % field,
              got and "changed after the Risk approval" in got and led == snap, got)
    P.execute_order(good, d6, cfg, led, now)
    check("   the unmodified order still fills with its approval (a refused modified copy does not use it up)",
          any(p.get("client_order_id") == "t-6" for p in led["open"]))

    # fill-price revalidation
    r1 = P.order_request(args(symbol="CRYPTO:ADA", price=1.0, stop="0.97", target="1.06"), cid="t-7")
    a1 = R.risk_check(r1, cfg, led, now)
    p1 = P.execute_order(r1, a1, cfg, led, now, fill_quote=0.999)
    check("fill price 0.999 vs approved 1.000: Risk re-validates, it fills at 0.999 with the APPROVED size",
          p1["entry"] == 0.999 and p1["qty"] == a1["qty"] and p1["stop"] == a1["stop"], p1)
    snap = copy.deepcopy(led)
    r2 = P.order_request(args(symbol="CRYPTO:XRP", price=2.0, stop="1.9", target="2.3"), cid="t-8")
    a2 = R.risk_check(r2, cfg, led, now)
    got = refused(lambda: P.execute_order(r2, a2, cfg, led, now, fill_quote=1.85))
    check("   fill price beyond the stop (1.85 < stop 1.90): Risk says NEEDS_REVISION, not executed",
          got and "fill price" in got and led == snap, got)
    r3 = P.order_request(args(symbol="CRYPTO:XRP", price=2.0, stop="1.9", target="2.3"), cid="t-9")
    a3 = R.risk_check(r3, cfg, led, now)
    got = refused(lambda: P.execute_order(r3, a3, cfg, led, now, fill_quote=2.06))
    check("   fill price 2.06 (risk per unit up 60%): the approved size breaks the max loss, not executed",
          got and "under the approved" in got and led == snap, got)
    r4 = P.order_request(args(symbol="CRYPTO:XRP", price=2.0, stop="1.9", target="2.12"), cid="t-10")
    a4 = R.risk_check(r4, cfg, led, now)
    got = refused(lambda: P.execute_order(r4, a4, cfg, led, now, fill_quote=2.03))
    check("   fill price 2.03 drops reward:risk under the minimum: not executed",
          a4["decision"] == "APPROVED" and got and "reward:risk" in got and led == snap, (a4["decision"], got))

    # simulator failures
    r5 = P.order_request(args(symbol="CRYPTO:DOGE", price=0.2, stop="0.19", target="0.23"), cid="t-11")
    a5 = R.risk_check(r5, cfg, led, now)
    got = refused(lambda: P.execute_order(r5, a5, cfg, {"open": None}, now))
    check("simulator: malformed ledger at the Broker: refused (fail closed)", got and "unavailable" in got, got)
    real = P.journal_order
    P.journal_order = lambda rec: (_ for _ in ()).throw(OSError("disk full"))
    got = refused(lambda: P.execute_order(r5, a5, cfg, led, now))
    P.journal_order = real
    check("   journal down at the fill: refused, the ledger untouched", got and "journal" in got and led == snap, got)
    os.environ["TRADER_EXECUTION_MODE"] = "LIVE"
    r6 = P.order_request(args(symbol="CRYPTO:DOGE", price=0.2, stop="0.19", target="0.23"), cid="t-12")
    a6 = R.risk_check(r6, cfg, led, now)
    got = refused(lambda: P.execute_order(r6, a6, cfg, led, now))
    os.environ.pop("TRADER_EXECUTION_MODE")
    check("   TRADER_EXECUTION_MODE=LIVE at the Broker, even with a valid approval: refused",
          got and "PAPER" in got and led == snap, got)
    live_req = dict(r6, mode="LIVE")
    got = refused(lambda: P.execute_order(live_req, R.risk_check(live_req, cfg, led, now), cfg, led, now))
    check("   an order asking for LIVE execution, even with an approval: refused", got and led == snap, got)

    # decisions, thresholds, ids
    cfg2 = copy.deepcopy(cfg)
    cfg2["accounts"]["CRYPTO"]["min_net_rr"] = 1.99
    dd = R.risk_check(P.order_request(args(symbol="CRYPTO:LTC", price=100.0, stop="98", target="104"), cid="x"),
                      cfg2, led, now)
    check("thresholds: min_net_rr (unset by default) set to 1.99: gross 2.0 passes, net under 1.99 is REJECTED",
          dd["decision"] == "REJECTED" and "net reward:risk" in dd["reason"] and dd["gross_rr"] == 2.0, dd)
    dflt = R.risk_check(P.order_request(args(symbol="CRYPTO:LTC", price=100.0, stop="98", target="104"), cid="y"),
                        cfg, led, now, register=False)
    check("   min_net_rr unset (default): the same trade is APPROVED, as before", dflt["decision"] == "APPROVED", dflt)
    cfg3 = copy.deepcopy(cfg)
    cfg3["accounts"]["CRYPTO"]["max_fee_risk_frac"] = 0.01
    df = R.risk_check(P.order_request(args(symbol="CRYPTO:LTC", price=100.0, stop="98", target="104"), cid="z"),
                      cfg3, led, now, register=False)
    check("   max_fee_risk_frac (default 0.5, the old fixed number) is read from the config",
          df["decision"] == "REJECTED" and "stop too tight" in df["reason"], df)
    acc = cfg["accounts"]["NSE" if "NSE" in cfg["accounts"] else "INDIA"]
    check("   pre-check messages unchanged: fees over 0.25R, 0 units",
          R.setup_gate(acc, "NSE", 10, 1.0, 0.3) == "fees eat 0.30R of the trade (max 0.25R)"
          and R.setup_gate(acc, "NSE", 0, 1.5, 0.1).startswith("0 units fit: the stop is 1.5 away")
          and R.setup_gate(acc, "NSE", 10, 1.0, 0.25) is None)
    s = {"side": "long", "v4_signal_at": "2026-11-20T09:30:00+00:00", "details": {"BOS_at": "2026-11-20T09:00:00+00:00"}}
    check("   setup id = chart : side : BOS time : signal time",
          P.setup_id_of("CRYPTO", "BTC", s) == "CRYPTO:BTC:long:2026-11-20T09:00:00+00:00:2026-11-20T09:30:00+00:00")
    snap = copy.deepcopy(led)
    try:
        P.cmd_buy(args(symbol="CRYPTO:SOL", price=150.0, stop="149", target="150.4", client_order_id="t-13"), cfg, led)
        e = None
    except R.RiskRejected as x:
        e = x
    o = P.read_orders()[-1]
    check("   cmd_buy (Risk then Broker): a Risk rejection raises RiskRejected with the decision, journals "
          "PAPER_REJECTED with the setup id and the Risk verdict, nothing filled",
          e is not None and e.decision["decision"] == "REJECTED" and o["status"] == "PAPER_REJECTED"
          and o["risk_decision"] == "REJECTED" and o["setup_id"] and led == snap, (e, o))
    check("no network call at all", not NET, NET)

    os.chdir(ROOT)
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("all checks passed")
