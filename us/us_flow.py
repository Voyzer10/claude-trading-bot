#!/usr/bin/env python3
"""
us_flow.py - run the 11 day-trader agents on LIVE US data, one command per step,
and (only after you type yes) record a PAPER trade in ..\\paper.py.

Run it from this folder (D:\\trader\\us):

    python us_flow.py scan                 # 1 scanner: opening-range breakouts so far (after 9:50 AM ET = 7:20 PM IST)
    python us_flow.py scan --daily         #   or the pre-market daily setups
    python us_flow.py trade TSLA           # 2-9 for one ticker: news, entry, exit, time machine, budget, risk, ticket,
                                           #   asks yes/no for a PAPER buy, then sets the alerts
    python us_flow.py alerts               # 9 check the alerts (stop / target / flat by 3:55 PM ET)
    python us_flow.py analyst TSLA         # 10 earnings from SEC (needs sec_user_agent in trader\\config.json)
    python us_flow.py pelosi               # 11 Congress trade disclosures (House Clerk)

Every agent is the original pack's own script (trader-*/ in this folder); their files land in
trader\\ here. Paper money only: nothing is sent to a broker. Not financial advice.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)            # D:\trader, where paper.py and its ledger live
PY = sys.executable
T = os.path.join(HERE, "trader")


def run(step, args, check=False):
    print("\n" + "=" * 70)
    print(step)
    print("=" * 70, flush=True)
    r = subprocess.run([PY] + args, cwd=HERE)
    if check and r.returncode not in (0, 1):
        print("(%s exited with code %d)" % (args[0], r.returncode))
    return r.returncode


def script(folder, name):
    return os.path.join(HERE, folder, name)


def load(path):
    try:
        with open(os.path.join(HERE, path), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def sec_ready():
    cfg = load("trader/config.json") or {}
    ua = os.environ.get("SEC_USER_AGENT") or cfg.get("sec_user_agent", "")
    return bool(ua) and "you@example.com" not in ua


def cmd_scan(argv):
    if not os.path.exists(os.path.join(T, "universe.txt")):
        run("1 SCANNER: building the US stock list (once)", [script("trader-scanner", "scan.py"), "universe"])
    mode = "daily" if "--daily" in argv else "orb"
    extra = [a for a in argv if a != "--daily"]
    run("1 SCANNER (%s)" % mode, [script("trader-scanner", "scan.py"), mode] + extra)
    print("\nPick ONE ticker from the list, then: python us_flow.py trade TICKER")


def cmd_trade(argv):
    if not argv:
        print("usage: python us_flow.py trade TICKER")
        return
    tk = argv[0].upper()
    news = [script("trader-news", "news.py"), "--tickers", tk, "--hours", "12"]
    if not sec_ready():
        news.append("--no-sec")
    run("2 NEWS for %s%s" % (tk, "" if sec_ready() else " (SEC filings skipped: no sec_user_agent set)"), news)

    run("3 ENTRY: has %s broken its opening range?" % tk,
        [script("trader-entry", "entry.py"), "check", tk, "--setup", "orb", "--write"])
    e = load("trader/entry.json") or {}
    if e.get("symbol") != tk or e.get("status") != "triggered":
        print("\nNo entry: status is %r. Nothing planned, nothing bought." % e.get("status"))
        print("Watch it bar by bar instead: python trader-entry\\entry.py watch %s --every 30" % tk)
        return

    run("4 EXIT: stop and target before the entry",
        [script("trader-exit", "exit.py"), "plan", "--stop", "or-mid", "--target", "2R", "--write"])
    if (load("trader/plan.json") or {}).get("symbol") != tk:
        print("\nThe exit planner refused this one (see above). Stopping here.")
        return

    run("5 TIME MACHINE: 10,000 replays + every past time the setup fired",
        [script("trader-timemachine", "timemachine.py"), "run", "--write"])
    run("6 BUDGET: size it to your max loss", [script("trader-budget", "size.py"), "--write"])
    run("7 RISK: check every limit", [script("trader-risk", "check.py")])

    risk = load("trader/state/risk.json") or {}
    res = [r for r in risk.get("results", []) if r.get("symbol") == tk and r.get("kind") == "entry"]
    if not res or res[-1].get("verdict") != "PASS":
        print("\nRisk did not PASS this order. Nothing bought.")
        return
    r = res[-1]
    orders = (load("trader/orders.json") or {}).get("orders", [])
    o = next((x for x in orders if x.get("symbol") == tk), None)
    if not o:
        print("\nNo order for %s in trader\\orders.json. Nothing bought." % tk)
        return

    run("8 BROKER: the ticket", [script("trader-broker", "ticket.py"), "show"])
    print("\nThis would be a PAPER trade in ..\\paper.py (US account), not a real order.")
    reply = input("Type yes to paper-buy %s %s (stop %s, target %s), anything else to skip: "
                  % (o["qty"], tk, o["stop_loss_stop_price"], o["take_profit_limit_price"])).strip()
    if reply.lower() != "yes":
        print("Skipped. Nothing bought.")
        return
    rc = subprocess.run([PY, os.path.join(ROOT, "paper.py"), "buy", "US:" + tk,
                         "--qty", str(o["qty"]), "--price", str(r["entry_ref"]),
                         "--stop", str(o["stop_loss_stop_price"]),
                         "--target", str(o["take_profit_limit_price"]),
                         "--note", "us_flow: %s orb" % tk], cwd=ROOT).returncode
    if rc != 0:
        print("paper.py refused it (see above).")
        return
    run("9 ALERTS: stop, target, flat by 3:55 PM ET", [script("trader-alerts", "alerts.py"), "add", "--from-plan"])
    print("\nKeep an eye on it: python us_flow.py alerts   (and ..\\paper.py check closes it on paper)")


def cmd_alerts(argv):
    run("9 ALERTS", [script("trader-alerts", "alerts.py"), "check"])
    subprocess.run([PY, os.path.join(ROOT, "paper.py"), "check"], cwd=ROOT)


def cmd_analyst(argv):
    if not sec_ready():
        print("Put your name and email in trader\\config.json as \"sec_user_agent\": \"Your Name you@mail.com\" "
              "(SEC asks every caller to identify itself), then rerun.")
        return
    run("10 ANALYST", [script("trader-analyst", "facts.py")] + (argv or ["TSLA"]))


def cmd_pelosi(argv):
    run("11 PELOSI TRACKER", [script("trader-pelosi", "ptr.py"), "index", "--member", "pelosi"] + argv)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("scan", "trade", "alerts", "analyst", "pelosi"):
        print(__doc__)
        return 1
    {"scan": cmd_scan, "trade": cmd_trade, "alerts": cmd_alerts, "analyst": cmd_analyst,
     "pelosi": cmd_pelosi}[sys.argv[1]](sys.argv[2:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
