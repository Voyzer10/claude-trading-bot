"""EXPECTED RESULTS (answer key) for the blind liquidity examination. Written BY HAND from the approved rules
(SW-001..005, BOS-001..005, Option A, D1-D5, A1-A10, D2 P-B, A5) and, for liquidity, from the NOT-approved B0 proposal
(labelled PROVISIONAL) or marked UNRESOLVED. Mirrors are derived mechanically (p -> 200 - p). The key reads candle
values from the fixtures only to quote evidence; it never runs any detector."""
import hashlib
import json
import sys

FIX = json.load(open(sys.argv[1]))
CANDLES = {s["scenario_id"]: s["candles"] for s in FIX["scenarios"]}
MIRROR_OF = {s["scenario_id"]: s["mirror_of"] for s in FIX["scenarios"]}

BASE_SWINGS = [("L", 98, 4, 6), ("H", 109, 7, 9), ("L", 101, 10, 12), ("H", 116, 14, 16)]
BASE_BOS = [("bullish", 12, 109)]
BASE_EVENTS = [("ESTABLISHED", 16, "BULLISH", 101)]
# B0 pools of the base (PROVISIONAL): (side, level, source candle, active_from)
BASE_POOLS = [("SSL", 98, 4, 7), ("BSL", 109, 7, 10), ("SSL", 101, 10, 13), ("BSL", 116, 14, 17)]
BASE_LIQ = [dict(side="BSL", level=109, src=7, event="TAKEN", candle=12, before="ACTIVE", after="TAKEN", by="close",
                 inter=[("BOS", "bullish", 109)], refs="B0: LS-S02 close beyond -> TAKEN; LP-12")]

B = "BULLISH"
TB = "TRANSITION(bearish)"
# ------------------------------------------------------------------ bullish scenarios (hand-derived)
K = {
 "E1": dict(swings=[("L", 106, 16, 18), ("H", 117, 17, 19)], bos=[], events=[], wick=[],
            cp={17: (B, 101), 18: (B, 101), 19: (B, 101)},
            pools=[("SSL", 106, 16, 19), ("BSL", 117, 17, 20)],
            liq=[dict(side="BSL", level=116, src=14, event="SWEEP", candle=17, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[("NO_BOS", "bullish", 116)], refs="B0: LQ-08 S-wick, LQ-09 d=0, LQ-06")]),
 "E2": dict(swings=[("L", 100, 17, 19)], bos=[], events=[], wick=[(17, 101)],
            cp={17: (B, 101), 18: (B, 101), 19: (B, 101)},
            pools=[("SSL", 100, 17, 20)],
            liq=[dict(side="SSL", level=101, src=10, event="SWEEP", candle=17, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[("WICK_ONLY", "protected", 101), ("NO_STATE_CHANGE", "", None)], refs="B0: LQ-08, LQ-09, LQ-22")]),
 "E4": dict(swings=[("L", 106, 16, 18)], bos=[("bullish", 17, 116)], events=[], wick=[],
            cp={17: (B, 101), 18: (B, 106)},
            pools=[("SSL", 106, 16, 19)],
            liq=[dict(side="BSL", level=116, src=14, event="TAKEN", candle=17, before="ACTIVE", after="TAKEN", by="close",
                      inter=[("BOS", "bullish", 116)], refs="B0: LS-S02; LP-12 (BOS consumption is a separate rule)")]),
 "M1": dict(swings=[("L", 100, 17, 19)], bos=[], events=[], wick=[(17, 101), (18, 101)],
            cp={17: (B, 101), 18: (B, 101), 19: (B, 101), 20: (B, 101)},
            pools=[("SSL", 100, 17, 20)],
            liq=[dict(side="SSL", level=101, src=10, event="SWEEP", candle=17, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[("WICK_ONLY", "protected", 101)], refs="B0: LQ-08, LQ-09"),
                 dict(side="SSL", level=101, src=10, event="REPEAT_SWEEP (diagnostic)", candle=18, before="SWEPT", after="SWEPT", by="wick",
                      inter=[("WICK_ONLY", "protected", 101)], refs="B0: LQ-15, LQ-06")]),
 "M2": dict(swings=[], bos=[("bearish", 18, 101)], events=[("CHOCH", 18, TB, 101)], wick=[(17, 101)],
            cp={17: (B, 101), 18: (TB, None)},
            pools=[],
            liq=[dict(side="SSL", level=101, src=10, event="SWEEP", candle=17, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[("WICK_ONLY", "protected", 101)], refs="B0: LQ-08, LQ-09"),
                 dict(side="SSL", level=101, src=10, event="TAKEN", candle=18, before="SWEPT", after="TAKEN", by="close",
                      inter=[("BOS", "bearish", 101), ("CHOCH", "bearish", 101)], refs="B0: LQ-06 lifecycle, LS-S02")]),
 "M3": dict(swings=[("L", 97, 17, 19)], bos=[], events=[], wick=[(17, 101)],
            cp={17: (B, 101), 18: (B, 101), 19: (B, 101)},
            pools=[("SSL", 97, 17, 20)],
            liq=[dict(side="SSL", level=101, src=10, event="SWEEP", candle=17, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[("WICK_ONLY", "protected", 101), ("SAME_CANDLE_GROUP", "", None)], refs="B0: LQ-08, LQ-14"),
                 dict(side="SSL", level=98, src=4, event="SWEEP", candle=17, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[("SAME_CANDLE_GROUP", "", None)], refs="B0: LQ-08, LQ-14")]),
 "H1": dict(swings=[("L", 100.5, 17, 19)], bos=[("bullish", 17, 116)], events=[], wick=[(17, 101)],
            cp={17: (B, 101), 18: (B, 101), 19: (B, 101)},
            pools=[("SSL", 100.5, 17, 20)],
            liq=[dict(side="SSL", level=101, src=10, event="SWEEP", candle=17, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[("WICK_ONLY", "protected", 101), ("BOS", "bullish", 116)], refs="B0: LQ-08, LS-S11"),
                 dict(side="BSL", level=116, src=14, event="TAKEN", candle=17, before="ACTIVE", after="TAKEN", by="close",
                      inter=[("BOS", "bullish", 116)], refs="B0: LS-S02, LS-S11")]),
 "H3": dict(swings=[("L", 106, 16, 18), ("H", 118.5, 19, 21), ("L", 105.5, 19, 21)], bos=[("bullish", 17, 116)], events=[],
            wick=[(19, 106)], cp={17: (B, 101), 18: (B, 106), 19: (B, 106), 20: (B, 106), 21: (B, 106)},
            pools=[("SSL", 106, 16, 19), ("BSL", 118.5, 19, 22), ("SSL", 105.5, 19, 22)],
            liq=[dict(side="BSL", level=116, src=14, event="TAKEN", candle=17, before="ACTIVE", after="TAKEN", by="close",
                      inter=[("BOS", "bullish", 116)], refs="B0: LS-S02"),
                 dict(side="SSL", level=106, src=16, event="SWEEP", candle=19, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[("WICK_ONLY", "protected", 106)], refs="B0: LQ-08; pool active from conf+1 = c19 (D5 step 4)")]),
 "H4": dict(swings=[("L", 102, 17, 19), ("L", 103, 20, 22)], bos=[], events=[], wick=[],
            cp={k: (B, 101) for k in range(17, 24)},
            pools=[("SSL", 102, 17, 20), ("SSL", 103, 20, 23)],
            liq=[dict(side="SSL", level=103, src=20, event="NO_EVENT (pool not yet formed; no back-dating)", candle=17, before="NONE",
                      after="NONE", by="wick", inter=[], refs="approved swing timing + LQ-21; c17 low 102 < 103 is ignored"),
                 dict(side="SSL", level=103, src=20, event="SWEEP", candle=23, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[], refs="B0: LQ-08; active from c23")]),
 "X1": dict(swings=[("L", 100, 17, 19)], bos=[], events=None, wick=None, cp={},
            pools=[("SSL", 100, 17, 20)], liq=[],
            unresolved=[(17, "structure state / CHoCH at c17: close == protected 101 (CHU04)"),
                        (17, "SSL 101 sweep vs no-sweep when close == level (LQ-08 / CHU04 / LQ-09)"),
                        (18, "state at c18-c19 depends on the c17 decision (CHU04)")]),
 "X2": dict(swings=[("L", 106, 16, 18), ("H", 116, 18, 20), ("L", 108, 20, 22)], bos=[], events=[], wick=[],
            cp={k: (B, 101) for k in range(17, 23)},
            pools=[("SSL", 106, 16, 19), ("SSL", 108, 20, 23)], liq=[],
            unresolved=[(18, "c18 high == 116 exactly (touch, not beyond): sweep depth / equality (LQ-09)"),
                        (18, "a second swing high at 116: separated equal highs as one pool or two (LQ-03)"),
                        (21, "c21 high 117 / close 115 pierces both 116 levels: one or two sweeps (LQ-03, LQ-14)")]),
 "X3": dict(swings=[("L", 99.5, 17, 19)], bos=[("bearish", 17, 101)], events=[("CHOCH", 17, TB, 101)], wick=[],
            cp={17: (TB, None)}, pools=[("SSL", 99.5, 17, 20)],
            liq=[dict(side="SSL", level=101, src=10, event="TAKEN", candle=17, before="ACTIVE", after="TAKEN", by="close",
                      inter=[("BOS", "bearish", 101), ("CHOCH", "bearish", 101)], refs="B0: LS-S02")],
            unresolved=[(18, "close back above the taken / consumed 101: reclaim (LQ-12) and failed CHoCH (O4)"),
                        (18, "state at c18-c19 (O4 unresolved)")]),
 "X4": dict(swings=[("L", 96, 21, 23)], bos=[("bearish", 19, 101), ("bearish", 24, 96)],
            events=[("CHOCH", 19, TB, 101), ("REVERSAL_CONFIRMED", 24, "BEARISH", None)], wick=[(17, 101), (18, 101)],
            cp={17: (B, 101), 18: (B, 101), 19: (TB, None), 20: (TB, None), 21: (TB, None), 22: (TB, None), 23: (TB, None), 24: ("BEARISH", None)},
            pools=[("SSL", 96, 21, 24)],
            liq=[dict(side="SSL", level=101, src=10, event="SWEEP", candle=17, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[("WICK_ONLY", "protected", 101)], refs="B0: LQ-08"),
                 dict(side="SSL", level=101, src=10, event="REPEAT_SWEEP (diagnostic)", candle=18, before="SWEPT", after="SWEPT", by="wick",
                      inter=[("WICK_ONLY", "protected", 101)], refs="B0: LQ-15"),
                 dict(side="SSL", level=101, src=10, event="TAKEN", candle=19, before="SWEPT", after="TAKEN", by="close",
                      inter=[("BOS", "bearish", 101), ("CHOCH", "bearish", 101)], refs="B0: LQ-06, LS-S02"),
                 dict(side="SSL", level=98, src=4, event="SWEEP", candle=20, before="ACTIVE", after="SWEPT", by="wick",
                      inter=[("NO_BOS_D4", "bearish", 98)], refs="B0: LQ-08; approved D4: no BOS, latest reference 101 already used"),
                 dict(side="SSL", level=98, src=4, event="TAKEN", candle=21, before="SWEPT", after="TAKEN", by="close",
                      inter=[("NO_BOS_D4", "bearish", 98)], refs="B0: LS-S02; approved D4: no BOS on an older unbroken swing"),
                 dict(side="SSL", level=96, src=21, event="TAKEN", candle=24, before="ACTIVE", after="TAKEN", by="close",
                      inter=[("BOS", "bearish", 96), ("REVERSAL_CONFIRMED", "bearish", None)], refs="B0: LS-S02; pool active from c24")]),
}
FLIP = {"bullish": "bearish", "bearish": "bullish", "BULLISH": "BEARISH", "BEARISH": "BULLISH", TB: "TRANSITION(bullish)",
        "TRANSITION(bullish)": TB, "L": "H", "H": "L", "SSL": "BSL", "BSL": "SSL"}
fp = lambda p: None if p is None else 200 - p
fl = lambda x: FLIP.get(x, x)


def mirror_key(k):
    m = dict(swings=[(fl(a), fp(b), c, d) for a, b, c, d in k["swings"]],
             bos=[(fl(a), b, fp(c)) for a, b, c in k["bos"]],
             events=None if k["events"] is None else [(a, b, fl(c), fp(d)) for a, b, c, d in k["events"]],
             wick=None if k["wick"] is None else [(a, fp(b)) for a, b in k["wick"]],
             cp={c: (fl(s), fp(p)) for c, (s, p) in k["cp"].items()},
             pools=[(fl(a), fp(b), c, d) for a, b, c, d in k["pools"]],
             liq=[dict(e, side=fl(e["side"]), level=fp(e["level"]),
                       inter=[(a, fl(b), fp(c)) for a, b, c in e["inter"]]) for e in k["liq"]],
             unresolved=[(c, r.replace("101", "99").replace("116", "84").replace("117", "83").replace("115", "85")
                          .replace("high", "LOW").replace("low", "high").replace("LOW", "low").replace("above", "BELOW")
                          .replace("below", "above").replace("BELOW", "below")) for c, r in k.get("unresolved", [])])
    return m


def evidence(sid, e):
    if e["candle"] is None:
        return None
    c = CANDLES[sid][e["candle"] - 1]
    lvl = e["level"]
    if e["side"] == "BSL":
        return "high %s %s %s, close %s %s %s" % (c["h"], ">" if c["h"] > lvl else "<=", lvl, c["c"], ">" if c["c"] > lvl else "<=", lvl)
    return "low %s %s %s, close %s %s %s" % (c["l"], "<" if c["l"] < lvl else ">=", lvl, c["c"], "<" if c["c"] < lvl else ">=", lvl)


def render(sid, k):
    def all_swings():
        bs = BASE_SWINGS if not MIRROR_OF[sid] else [(fl(a), fp(b), c, d) for a, b, c, d in BASE_SWINGS]
        return sorted(bs + k["swings"], key=lambda x: (x[3], x[2], x[0]))
    mir = bool(MIRROR_OF[sid])
    bb = BASE_BOS if not mir else [(fl(a), b, fp(c)) for a, b, c in BASE_BOS]
    be = BASE_EVENTS if not mir else [(a, b, fl(c), fp(d)) for a, b, c, d in BASE_EVENTS]
    bp = BASE_POOLS if not mir else [(fl(a), fp(b), c, d) for a, b, c, d in BASE_POOLS]
    bl = BASE_LIQ if not mir else [dict(e, side=fl(e["side"]), level=fp(e["level"]), inter=[(a, fl(b), fp(c)) for a, b, c in e["inter"]]) for e in BASE_LIQ]
    dec = dict(
        swings=[dict(kind={"L": "low", "H": "high"}[a], price=b, source_candle=c, confirmed_candle=d,
                     status="APPROVED (SW-001..005 L2/R2 strict)") for a, b, c, d in all_swings()],
        bos=[dict(direction=a, candle=b, level=c, status="APPROVED (BOS-001..005, D4, D5)") for a, b, c in sorted(bb + k["bos"], key=lambda x: x[1])],
        structure_events=[dict(type=a, candle=b, state_after=c, level=d, status="APPROVED (A2-A10, D1-D3)")
                          for a, b, c, d in sorted(be + (k["events"] or []), key=lambda x: x[1])],
        wick_only=[dict(candle=a, protected_level=b, status="APPROVED (A6 wick-only = NO_CHOCH)") for a, b in (k["wick"] or [])],
        structure_scored_up_to_candle=16 if k["events"] is None else None,
        checkpoints=[dict(candle=c, state=s, protected=p, status="APPROVED (state + D2 P-B protected in force after the close)")
                     for c, (s, p) in sorted(k["cp"].items())],
        harness=dict(no_lookahead_violations=[], replay_audit_ok=True, status="APPROVED (engine harness)"))
    pools = []
    for side, lvl, src, act in bp + k["pools"]:
        pools.append(dict(pool_id="%s@%s(c%d)" % (side, lvl, src), side=side, level=lvl, source_candle=src, active_from=act,
                          status="PROVISIONAL (B0 LQ-01: every confirmed swing is a pool, active from confirmation + 1; NOT approved)"))
    liq = []
    for e in bl + k["liq"]:
        liq.append(dict(pool_id="%s@%s(c%d)" % (e["side"], e["level"], e["src"]), side=e["side"], event=e["event"], candle=e["candle"],
                        state_before=e["before"], state_after=e["after"], evidence=evidence(sid, e),
                        bos_choch_interaction=["%s %s %s" % (a, b, "" if c is None else c) for a, b, c in e["inter"]] or ["none"],
                        status="PROVISIONAL (%s)" % e["refs"]))
    unres = [dict(candle=c, item=r, status="UNRESOLVED") for c, r in k.get("unresolved", [])]
    return dict(scenario_id=sid, decidable=dec, provisional_pools=pools, provisional_liquidity_events=liq, unresolved=unres)


out = []
for s in FIX["scenarios"]:
    sid = s["scenario_id"]
    short = sid.split("-")[1]
    k = mirror_key(K[MIRROR_OF[sid].split("-")[1]]) if MIRROR_OF[sid] else K[short]
    out.append(render(sid, k))
doc = dict(spec="EXPECTED RESULTS: V6 Liquidity Sweep blind examination (answer key, hand-derived)",
           fixtures_sha256=hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest(),
           scoring="Only `decidable` items are scored. `provisional_*` depend on the NOT-approved B0 proposal; `unresolved` items are never scored.",
           scenarios=out)
s = json.dumps(doc, indent=1, default=str)
open(sys.argv[2], "w").write(s)
print("sealed key", sys.argv[2], "sha256", hashlib.sha256(s.encode()).hexdigest())
