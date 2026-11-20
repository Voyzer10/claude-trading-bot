"""Every difference between the baseline and the new code's replay (fields the new code only ADDS are listed
separately, not as differences)."""
import json, sys
NEW_POS = {"order_id", "trade_id", "risk", "setup_id"}          # order_id differs by process id in every run
NEW_ORD = {"order_id", "setup_id", "risk_approval_id", "risk_decision", "trade_id"}
def diff(a, b, path, out, ignore=()):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in ignore:
                continue
            if k not in b:
                out.append("%s.%s removed" % (path, k))
            elif k not in a:
                out.append("%s.%s added = %r" % (path, k, b[k]))
            else:
                diff(a[k], b[k], "%s.%s" % (path, k), out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append("%s: %d vs %d items" % (path, len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, "%s[%d]" % (path, i), out)
    elif isinstance(a, float) and isinstance(b, float):
        if abs(a - b) > 1e-9 * max(1, abs(a)):
            out.append("%s: %r -> %r" % (path, a, b))
    elif a != b:
        out.append("%s: %r -> %r" % (path, a, b))
for v in ("default", "risk_on"):
    a, b = json.load(open("base_%s.json" % v)), json.load(open("new_%s.json" % v))
    out = []
    da = [{k: x for k, x in d.items() if k != "setup_id"} for d in a["decisions"]]
    db = [{k: x for k, x in d.items() if k != "setup_id"} for d in b["decisions"]]
    diff(da, db, "decisions", out)
    for part in ("closed", "open"):
        diff([{k: x for k, x in p.items() if k not in NEW_POS} for p in a[part]],
             [{k: x for k, x in p.items() if k not in NEW_POS} for p in b[part]], part, out)
    diff(a["accounts"], b["accounts"], "accounts", out)
    diff([{k: x for k, x in o.items() if k not in NEW_ORD} for o in a["orders"]],
         [{k: x for k, x in o.items() if k not in NEW_ORD} for o in b["orders"]], "orders", out)
    diff(a["errors"], b["errors"], "errors", out)
    filled = [d for d in b["decisions"] if d["result"] in ("PAPER BUY", "PAPER SHORT")]
    print("== %s: decisions %d, trades %d, orders %d; differences: %d" % (
        v, len(b["decisions"]), len(b["closed"]), len(b["orders"]), len(out)))
    for line in out[:60]:
        print("   ", line)
    ids = [p.get("setup_id") for p in b["closed"]]
    print("   new fields: every decision has setup_id: %s; every trade has setup_id + trade_id + risk approval: %s; "
          "every order journal line has a trade/approval link: %s" % (
              all(d.get("setup_id") for d in b["decisions"]),
              all(p.get("setup_id") and p.get("trade_id") and (p.get("risk") or {}).get("approval_id") for p in b["closed"]),
              all(o.get("risk_approval_id") if (o["intent"] == "ENTRY" and o["status"] == "PAPER_FILLED") else
                  (o.get("trade_id") if o["intent"] == "EXIT" else True) for o in b["orders"])))
