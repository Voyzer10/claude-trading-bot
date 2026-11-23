"""Sealed ground truth from the approved rules, computed by the INDEPENDENT spec-text oracles (oracle2.py for structure,
the register-text liquidity oracle below, and a CK-17 / OQ-5 / MB-1..4 / D5 setup-link oracle). No scanner_v6 import.
usage: gt.py <build_dir> <out_dir>"""
import csv, glob, json, os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from oracle2 import oracle2


class C:
    __slots__ = ("index", "open", "high", "low", "close")

    def __init__(self, i, o, h, l, c):
        self.index, self.open, self.high, self.low, self.close = i, o, h, l, c


def load(p):
    return [C(int(r["index"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
            for r in csv.DictReader(open(p))]


def swid(s):
    return "swing:%s:%d:fixed-window-strict:L2R2" % ("high" if s["kind"] == "H" else "low", s["idx"])


def liquidity(cs, swings):
    """LQ-01/04/06/08/09/14/15/16, LS-S02, G-1, G-5, OQ-4: one pool per swing, from conf+1; BSL close>P TAKEN, high>P
    sweep (SSL mirrored); ACTIVE->SWEPT (SWEEP) -> REPEAT_SWEEP -> TAKEN."""
    pools, events = [], []
    for s in swings:
        side = "BSL" if s["kind"] == "H" else "SSL"
        pid = "pool:" + swid(s)
        P, state, hist = s["price"], "ACTIVE", []
        for k in range(s["conf"] + 1, len(cs)):
            c = cs[k]
            beyond = c.close > P if side == "BSL" else c.close < P
            wick = c.high > P if side == "BSL" else c.low < P
            if beyond:
                events.append(dict(type="TAKEN", side=side, index=k, level=P, pool_id=pid, state_before=state,
                                   state_after="TAKEN", group_id=None))
                hist.append((k, "TAKEN")); state = "TAKEN"
                break
            if wick:
                t = "SWEEP" if state == "ACTIVE" else "REPEAT_SWEEP"
                events.append(dict(type=t, side=side, index=k, level=P, pool_id=pid, state_before=state,
                                   state_after="SWEPT", group_id="sweep:%s:%d" % (side, k) if t == "SWEEP" else None))
                hist.append((k, t)); state = "SWEPT"
        pools.append(dict(pool_id=pid, side=side, swing_index=s["idx"], level=P, created_index=s["conf"],
                          evaluated_from=s["conf"] + 1, final_state=state, lifecycle=hist))
    groups = defaultdict(list)
    for e in events:
        if e["type"] == "SWEEP":
            groups[(e["side"], e["index"])].append(e["pool_id"])
    grp = [dict(group_id="sweep:%s:%d" % k, side=k[0], index=k[1], pool_ids=sorted(v)) for k, v in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0] != "BSL"))]
    return pools, sorted(events, key=lambda e: (e["index"], e["pool_id"], e["type"])), grp


def setup_link(o, groups):
    """CK-17 / SR-4 / MB-1..4 / OQ-5 / CK-18 / D5 terminator (no Module C closers): per REVERSAL_CONFIRMING BOS at j,
    eligible until the first close with an opposite BOS or opposite CHoCH; the first required-side group with
    j < k < end starts the candidate (groups at the terminating close come after the structure, so excluded)."""
    sw = {(s["kind"], s["idx"]): s for s in o["swings"]}
    bos = [dict(dir=d, k=k, ref=r, role=role) for d, k, r, role in o["roles"]]
    choch = [e for e in o["events"] if e[0] == "CHOCH"]
    out = []
    for b in [x for x in bos if x["role"] == "REVERSAL_CONFIRMING"]:
        j, d = b["k"], b["dir"]
        opp = "bearish" if d == "bullish" else "bullish"
        ends = sorted({x["k"] for x in bos if x["dir"] == opp and x["k"] > j} | {e[1] for e in choch if e[2] == opp and e[1] > j})
        end = ends[0] if ends else None
        need = "SSL" if d == "bullish" else "BSL"
        g = [x for x in groups if x["side"] == need and x["index"] > j and (end is None or x["index"] < end)]
        bos_id = "bos:%s:%s" % (d, swid(sw[("H" if d == "bullish" else "L", b["ref"])]))
        term = None
        if end is not None:
            ob = [x for x in bos if x["dir"] == opp and x["k"] == end]
            if ob:
                term = "bos:%s:%s" % (opp, swid(sw[("H" if opp == "bullish" else "L", ob[0]["ref"])]))
            else:
                ce = [e for e in choch if e[2] == opp and e[1] == end][0]
                ps = [s for s in o["swings"] if s["price"] == ce[3] and s["kind"] == ("L" if opp == "bearish" else "H") and s["conf"] < end]
                term = "choch:%s:%s" % (opp, swid(ps[-1])) if ps else "choch:%s:?" % opp
        if g:
            out.append(dict(bos_id=bos_id, bos_index=j, setup_side="BUY" if d == "bullish" else "SELL", sweep_side=need,
                            group_id=g[0]["group_id"], index=g[0]["index"],
                            status="INVALIDATED" if end is not None else "PENDING", closed_index=end, closed_by=term))
    return out


def build(cs):
    o = oracle2(cs)
    sw = o["swings"]
    by = {(s["kind"], s["idx"]): s for s in sw}
    ev = []
    for s in sw:
        ev.append(dict(type="SWING_HIGH" if s["kind"] == "H" else "SWING_LOW", index=s["idx"], level=s["price"],
                       id=swid(s), confirmation_index=s["conf"]))
    for d, k, ref, role in o["roles"]:
        r = by[("H" if d == "bullish" else "L", ref)]
        ev.append(dict(type="BOS", direction=d, index=k, level=r["price"], id="bos:%s:%s" % (d, swid(r)),
                       related_swing=swid(r), confirmation_index=k, role=role))
    for e in o["events"]:
        if e[0] == "CHOCH":
            prot = [s for s in sw if s["price"] == e[3] and s["kind"] == ("L" if e[2] == "bearish" else "H") and s["conf"] < e[1]]
            ev.append(dict(type="CHOCH", direction=e[2], index=e[1], level=e[3], id="choch:%s:%s" % (e[2], swid(prot[-1])),
                           related_swing=swid(prot[-1]), confirmation_index=e[1], state_before=e[4], state_after=e[5]))
        else:
            ev.append(dict(type="STATE_" + e[0], direction=e[2], index=e[1], level=e[3], state_before=e[4], state_after=e[5],
                           confirmation_index=e[1]))
    pools, lev, groups = liquidity(cs, sw)
    for p in pools:
        ev.append(dict(type="POOL_" + p["side"], index=p["swing_index"], level=p["level"], id=p["pool_id"],
                       confirmation_index=p["created_index"], lifecycle_state=p["final_state"], lifecycle=p["lifecycle"]))
    for e in lev:
        ev.append(dict(type=e["type"] + "_" + e["side"], index=e["index"], level=e["level"],
                       id="liquidity:%s:%s:%d" % (e["pool_id"], e["type"], e["index"]), related_pool=e["pool_id"],
                       confirmation_index=e["index"], state_before=e["state_before"], state_after=e["state_after"],
                       group_id=e["group_id"]))
    for g in groups:
        ev.append(dict(type="SWEEP_GROUP_" + g["side"], index=g["index"], id=g["group_id"], pools=g["pool_ids"],
                       confirmation_index=g["index"]))
    setups = setup_link(o, groups)
    # unscored / ambiguous zones (documented, never forced)
    uns = []
    n = len(cs)
    for i in range(n):
        for j in range(max(0, i - 4), i):
            if cs[i].high == cs[j].high and all(cs[x].high <= cs[i].high for x in range(j, i + 1)):
                uns.append(dict(kind="EQUAL_HIGHS", indices=[j, i], level=cs[i].high, rule="LQ-03 OPEN (equal-level pools); "
                                "SW-003: equal extremes are not L2/R2 swings, so no pool in GT", scope="pool scoring"))
            if cs[i].low == cs[j].low and all(cs[x].low >= cs[i].low for x in range(j, i + 1)):
                uns.append(dict(kind="EQUAL_LOWS", indices=[j, i], level=cs[i].low, rule="LQ-03 OPEN (equal-level pools); "
                                "SW-003: equal extremes are not L2/R2 swings, so no pool in GT", scope="pool scoring"))
    levels = {s["price"] for s in sw}
    for i, c in enumerate(cs):
        if c.close in levels:
            uns.append(dict(kind="CLOSE_EQUALS_SWING_LEVEL", indices=[i], level=c.close,
                            rule="BOS-006 / C1 tick epsilon OPEN; strict comparison applied (no BOS / no CHoCH / no TAKEN)",
                            scope="BOS, CHoCH, TAKEN"))
    for e in o["events"]:
        if e[0] == "ESTABLISHMENT_REJECTED":
            uns.append(dict(kind="ESTABLISHMENT_REJECTED_SR6", indices=[e[1]], level=e[3], rule="SR-6 (approved)", scope="note"))
    uns.append(dict(kind="OQ12_GROUP_MEMBERSHIP", indices=[], rule="OQ-12 OPEN: REPEAT_SWEEP / TAKEN carry no group",
                    scope="group membership of REPEAT_SWEEP / TAKEN not scored"))
    return dict(events=sorted(ev, key=lambda e: (e["index"], e["type"])), setup_candidates=setups, unscored=uns,
                timeline=[dict(index=t[0], state=t[1], protected_level=t[2],
                               protected_swing=None if t[3] is None else swid(by[t[3]])) for t in o["tl"]])


def main():
    build_dir, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    meta = {m["chart_id"]: m for m in json.load(open(build_dir + "/scenarios.json"))}
    rows = []
    for p in sorted(glob.glob(build_dir + "/ohlc/*.csv")):
        cid = os.path.basename(p)[:-4]
        g = build(load(p))
        m = meta[cid]
        g.update(chart_id=cid, tier=m["tier"], scenario_id=m["scenario_id"], variant=m["variant"],
                 mirror_of=m["mirror_of"], candles=m["candles"], generator="oracle2 + liquidity + setup-link oracles "
                 "(spec text; no scanner_v6 import)", index_base="zero-based")
        json.dump(g, open("%s/%s.json" % (out, cid), "w"), indent=1)
        for e in g["events"]:
            rows.append([cid, m["tier"], e["type"], e.get("direction", e.get("type").split("_")[-1] if e["type"].endswith(("BSL", "SSL")) else ""),
                         e["index"], e.get("level", ""), e.get("id", ""), e.get("related_swing", e.get("related_pool", "")),
                         e.get("confirmation_index", ""), e.get("lifecycle_state", e.get("state_after", "")), e.get("role", "")])
    with open(out + "/ground_truth_events.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["chart_id", "tier", "event_type", "direction_or_side", "candle_index", "level", "event_id",
                    "related_swing_or_pool", "confirmation_index", "lifecycle_or_state_after", "bos_role"])
        w.writerows(rows)
    print("ground truth written for", len(meta), "charts,", len(rows), "event rows")


if __name__ == "__main__":
    main()
