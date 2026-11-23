"""Scores BOT_ANSWERS.json against the sealed EXPECTED_RESULTS.json. Only `decidable` items are scored.
    python3 score.py <EXPECTED_RESULTS.json> <BOT_ANSWERS.json> <out_dir>"""
import collections
import json
import os
import sys

E = json.load(open(sys.argv[1]))
Bt = json.load(open(sys.argv[2]))
OUT = sys.argv[3]
bot = {a["scenario_id"]: a for a in Bt["answers"]}
rows, mism = [], []


def num(x):
    return None if x is None else float(x)


def keyset(items, fields, upto=None):
    out = []
    for it in items:
        if upto is not None and it.get("candle", 0) > upto:
            continue
        out.append(tuple(num(it[f]) if f in ("price", "level", "protected", "protected_level") else it[f] for f in fields))
    return out


CATS = [("swings", ("kind", "price", "source_candle", "confirmed_candle")),
        ("bos", ("direction", "candle", "level")),
        ("structure_events", ("type", "candle", "state_after", "level")),
        ("wick_only", ("candle", "protected_level"))]
for sc in E["scenarios"]:
    sid = sc["scenario_id"]
    diff = {"E": "Easy", "M": "Medium", "H": "Hard", "X": "Extreme"}[sid.split("-")[1][0]]
    d, b = sc["decidable"], bot[sid]["decidable"]
    upto = d.get("structure_scored_up_to_candle")
    for cat, f in CATS:
        lim = upto if cat in ("structure_events", "wick_only") else None
        ex = keyset(d[cat], f, lim)
        got = keyset(b[cat], f, lim)
        for it in ex:
            ok = it in got
            rows.append(dict(scenario=sid, difficulty=diff, category=cat, item=str(it), result="PASS" if ok else "FAIL"))
            if not ok:
                mism.append(dict(scenario=sid, category=cat, expected=str(it), bot=str([g for g in got if g[1:2] == it[1:2] or g[0:1] == it[0:1]][:4])))
        extra = [g for g in got if g not in ex]
        rows.append(dict(scenario=sid, difficulty=diff, category=cat + "_no_unexpected", item="no extra %s" % cat,
                         result="PASS" if not extra else "FAIL"))
        if extra:
            mism.append(dict(scenario=sid, category=cat + " (unexpected in bot)", expected="none", bot=str(extra)))
    bcp = {c["candle"]: (c["state"], num(c["protected"])) for c in b["checkpoints"]}
    for c in d["checkpoints"]:
        want = (c["state"], num(c["protected"]))
        ok = bcp.get(c["candle"]) == want
        rows.append(dict(scenario=sid, difficulty=diff, category="checkpoints", item="c%d %s" % (c["candle"], want), result="PASS" if ok else "FAIL"))
        if not ok:
            mism.append(dict(scenario=sid, category="checkpoint c%d" % c["candle"], expected=str(want), bot=str(bcp.get(c["candle"]))))
    h = b["harness"]
    rows.append(dict(scenario=sid, difficulty=diff, category="harness", item="no_lookahead_violations == []", result="PASS" if h["no_lookahead_violations"] == [] else "FAIL"))
    rows.append(dict(scenario=sid, difficulty=diff, category="harness", item="replay_audit ok (batch / stream parity)", result="PASS" if h["replay_audit_ok"] else "FAIL"))

tot = collections.Counter(r["result"] for r in rows)
by = lambda key: {k: dict(collections.Counter(r["result"] for r in rows if r[key] == k)) for k in sorted({r[key] for r in rows})}
prov_events = sum(len(s["provisional_liquidity_events"]) for s in E["scenarios"])
prov_pools = sum(len(s["provisional_pools"]) for s in E["scenarios"])
unres = [dict(scenario=s["scenario_id"], **u) for s in E["scenarios"] for u in s["unresolved"]]
answered_liq = sum(1 for a in Bt["answers"] if a["liquidity"]["events"] != "NOT_IMPLEMENTED")
res = dict(decidable_totals=dict(tot), by_difficulty=by("difficulty"), by_category=by("category"), by_scenario=by("scenario"),
           mismatches=mism, provisional=dict(expected_events=prov_events, expected_pools=prov_pools,
                                             bot_answered_scenarios=answered_liq, bot_status="NOT_IMPLEMENTED for all 20 scenarios",
                                             note="not scored: B0 is not approved"),
           unresolved=unres, expected_sha256=E.get("fixtures_sha256"), bot_fixtures_sha256=Bt["fixtures_sha256"])
os.makedirs(OUT, exist_ok=True)
json.dump(res, open(os.path.join(OUT, "SCORES.json"), "w"), indent=1)
with open(os.path.join(OUT, "SCORE_ITEMS.csv"), "w") as fh:
    fh.write("scenario,difficulty,category,item,result\n")
    for r in rows:
        fh.write('%s,%s,%s,"%s",%s\n' % (r["scenario"], r["difficulty"], r["category"], r["item"].replace('"', "'"), r["result"]))
print(json.dumps(dict(totals=dict(tot), by_difficulty=res["by_difficulty"], by_category=res["by_category"]), indent=1))
print("mismatches:", len(mism))
for m in mism:
    print(" ", m)
