"""Parity replay: the LIVE paper pipeline (paper.setup_decision -> cmd_buy -> check_position / close_position) over
historical 5-minute candles, with the clock and the quotes taken from those candles. Same candles and the same
Scanner v4 candidates for every code version (prep.py). Nothing else is mocked but:
  fetch_price -> the candle's close at the clock; first_trigger -> the candidate's own candle (no late-trigger
  lookups); v4_timemachine -> None (display only, network).
python harness.py REPO DATA.pkl VARIANT OUT.json      VARIANT: default | risk_on"""
import contextlib, io, json, os, pickle, sys, tempfile
from datetime import datetime, timedelta, timezone
repo, data_path, variant, out = sys.argv[1:5]
out = os.path.abspath(out)
sys.path.insert(0, repo)
data = pickle.load(open(data_path, "rb"))
os.chdir(tempfile.mkdtemp())
os.environ.pop("TRADER_EXECUTION_MODE", None)
import paper as P
CLOCK = [None]
REAL = datetime


class FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        c = CLOCK[0]
        return c.astimezone(tz) if tz else c.replace(tzinfo=None)


def patch_clock():
    for name, mod in list(sys.modules.items()):
        if mod is not None and getattr(mod, "__file__", "") and os.path.dirname(os.path.abspath(mod.__file__)) == \
                os.path.abspath(repo) and getattr(mod, "datetime", None) is REAL:
            mod.datetime = FakeDT


PRICE = {}
P.fetch_price = lambda m, t: (PRICE[(m, t)], CLOCK[0])
P.first_trigger = lambda chart, side, signal, bar_end, path=None: bar_end
P.v4_timemachine = lambda *a, **k: None
cfg = P.load_config()
for name, acc in cfg["accounts"].items():
    acc["scanner_version"] = "v4"
    if variant == "risk_on":
        acc["risk_limits"] = True
P.save_json(P.CONFIG, cfg)
patch_clock()
quiet = io.StringIO()
res = {"decisions": [], "errors": []}
for mk in ("CRYPTO", "US", "NSE"):
    syms = {s: d for (m, s), d in data.items() if m == mk}
    times = {}
    for s, d in syms.items():
        for k, r in enumerate(d["rows"]):
            times.setdefault(r[0], []).append((s, k))
    cand_at = {}
    for s, d in syms.items():
        for c in d["cands"]:
            cand_at.setdefault((s, c["i"]), []).append(c["s"])
    for t in sorted(times):
        CLOCK[0] = t + timedelta(minutes=5)
        patch_clock()
        for s, k in times[t]:
            PRICE[(mk, s)] = syms[s]["rows"][k][4]
        cfg = P.load_config()
        led = P.load_ledger(cfg)
        for pos in list(led["open"]):
            if pos["market"] != mk or pos["symbol"] not in syms:
                continue
            hit = [k for s, k in times[t] if s == pos["symbol"]]
            if not hit or P._iso(pos["entry_time"]) >= CLOCK[0]:
                continue
            r = syms[pos["symbol"]]["rows"][hit[0]]
            try:
                with contextlib.redirect_stdout(quiet):
                    P.check_position(cfg, led, pos, r[4], [tuple(r[:5])], CLOCK[0])
            except Exception as e:
                res["errors"].append([CLOCK[0].isoformat(), pos["key"], "exit: %s" % e])
        P.save_json(P.LEDGER, led)
        for s, k in times[t]:
            for c in cand_at.get((s, k), []):
                try:
                    with contextlib.redirect_stdout(quiet):
                        rec = P.setup_decision(mk, s, c, now_iso=CLOCK[0].isoformat())
                except Exception as e:
                    res["errors"].append([CLOCK[0].isoformat(), s, "entry: %s: %s" % (type(e).__name__, e)])
                    continue
                st = rec["steps"]
                res["decisions"].append({"t": CLOCK[0].isoformat(), "symbol": rec["symbol"], "setup": rec["setup"],
                                         "result": rec["result"], "why": rec.get("why"),
                                         "flipped_from": rec.get("flipped_from"),
                                         "step4": st.get("4_exit"), "step68": st.get("6-8_budget_risk_broker"),
                                         "setup_id": rec.get("setup_id")})
led = P.load_ledger(P.load_config())
res["closed"] = led["closed"]
res["open"] = led["open"]
res["accounts"] = led["accounts"]
res["orders"] = P.read_orders(100000)
json.dump(res, open(out, "w"), default=str, indent=0)
print("decisions", len(res["decisions"]), "closed", len(res["closed"]), "open", len(res["open"]),
      "orders", len(res["orders"]), "errors", len(res["errors"]))
