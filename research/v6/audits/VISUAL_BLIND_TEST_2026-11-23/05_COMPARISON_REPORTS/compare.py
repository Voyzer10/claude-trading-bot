"""Phase 5 comparisons. usage: compare.py <build_dir> <gt_dir> <bot_dir> <agents_dir> <out_dir>
(1) bot vs sealed rule-based GT (exact, every field) (2) each agent vs GT (3) bot vs adjudicated visual annotations.
Scored visual types: BOS, CHOCH (with direction), POOL_BSL, POOL_SSL, SWEEP_BSL, SWEEP_SSL (a sweep candle = any SWEEP
or REPEAT_SWEEP of that side on that candle), TAKEN_BSL, TAKEN_SSL (optional for agents).
Detection match: same chart, type (and direction), |candle index difference| <= TOL (1), one-to-one, nearest first.
Exact-index accuracy = matches with difference 0 / matches. Level error = |price - GT level| (sweeps / taken: the
nearest swept pool level on that candle). Predictions that fall only on documented unscored zones are not counted."""
import csv, glob, json, os, statistics, sys
from collections import Counter, defaultdict

TOL = 1
VTYPES = ["BOS", "CHOCH", "POOL_BSL", "POOL_SSL", "SWEEP_BSL", "SWEEP_SSL", "TAKEN_BSL", "TAKEN_SSL"]
TIERS = ["EASY", "MEDIUM", "HARD", "EXTREME"]
TIER = {"E": "EASY", "M": "MEDIUM", "H": "HARD", "X": "EXTREME"}


def load_ohlc(p):
    return [(float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])) for r in csv.DictReader(open(p))]


def visual_view(events):
    """GT/bot full events -> {key: [(index, [levels])]} with key = type or type|direction."""
    v = defaultdict(lambda: defaultdict(list))
    for e in events:
        t = e["type"]
        if t in ("BOS", "CHOCH"):
            v["%s|%s" % (t, e["direction"])][e["index"]].append(e["level"])
        elif t in ("POOL_BSL", "POOL_SSL"):
            v[t][e["index"]].append(e["level"])
        elif t in ("SWEEP_BSL", "SWEEP_SSL", "REPEAT_SWEEP_BSL", "REPEAT_SWEEP_SSL"):
            v["SWEEP_" + t[-3:]][e["index"]].append(e["level"])
        elif t in ("TAKEN_BSL", "TAKEN_SSL"):
            v[t][e["index"]].append(e["level"])
    return {k: sorted((i, lv) for i, lv in d.items()) for k, d in v.items()}


def key_of(a):
    t = a["type"].upper()
    if t in ("BOS", "CHOCH"):
        return "%s|%s" % (t, str(a.get("direction", "")).lower())
    return t


def match(pred, truth, tol=TOL):
    """pred [(idx, price, payload)], truth [(idx, [levels])] -> (pairs[(p, t)], unmatched_p, unmatched_t)"""
    cand = []
    for pi, p in enumerate(pred):
        for ti, t in enumerate(truth):
            di = abs(p[0] - t[0])
            if di <= tol:
                le = min(abs(p[1] - x) for x in t[1]) if p[1] is not None else 0.0
                cand.append((di, le, pi, ti))
    cand.sort()
    up, ut, pairs = set(range(len(pred))), set(range(len(truth))), []
    for di, le, pi, ti in cand:
        if pi in up and ti in ut:
            up.discard(pi); ut.discard(ti)
            pairs.append((pred[pi], truth[ti], di, le))
    return pairs, [pred[i] for i in sorted(up)], [truth[i] for i in sorted(ut)]


def unscored_hit(key, p, unscored, ohlc):
    """True if an unmatched prediction lies on a documented unscored zone."""
    idx, price = p[0], p[1]
    for u in unscored:
        if u["kind"] in ("EQUAL_HIGHS", "EQUAL_LOWS"):
            side = "BSL" if u["kind"] == "EQUAL_HIGHS" else "SSL"
            if key == "POOL_" + side and any(abs(idx - i) <= TOL for i in u["indices"]):
                return u["kind"]
            if key in ("SWEEP_" + side, "TAKEN_" + side) and idx > max(u["indices"]) and 0 <= idx < len(ohlc):
                o, h, l, c = ohlc[idx]
                if (side == "BSL" and h > u["level"]) or (side == "SSL" and l < u["level"]):
                    return u["kind"] + "_SWEPT"
        elif u["kind"] == "CLOSE_EQUALS_SWING_LEVEL" and key.split("|")[0] in ("BOS", "CHOCH", "TAKEN_BSL", "TAKEN_SSL"):
            if any(abs(idx - i) <= TOL for i in u["indices"]):
                return u["kind"]
    return None


def score(pred_by_chart, truth_by_chart, unscored_by_chart, ohlc_by_chart, rng_by_chart, keys=None, tol=TOL):
    """returns per (tier, base type) counters + per chart details"""
    agg = defaultdict(lambda: dict(tp=0, fp=0, fn=0, uns=0, exact=0, lerr=[], lerr_pct=[]))
    detail = []
    for cid in sorted(truth_by_chart):
        tier = TIER[cid[0]]
        truth = truth_by_chart[cid]
        pred = pred_by_chart.get(cid, {})
        for key in sorted(set(truth) | set(pred)):
            if keys and key.split("|")[0] not in keys:
                continue
            base = key.split("|")[0]
            pairs, fp, fn = match(pred.get(key, []), truth.get(key, []), tol)
            fp_s = []
            for p in fp:
                z = unscored_hit(key, p, unscored_by_chart.get(cid, []), ohlc_by_chart.get(cid, []))
                if z:
                    agg[(tier, base)]["uns"] += 1
                    detail.append(dict(chart=cid, key=key, kind="UNSCORED", index=p[0], price=p[1], zone=z))
                else:
                    fp_s.append(p)
            a = agg[(tier, base)]
            a["tp"] += len(pairs); a["fp"] += len(fp_s); a["fn"] += len(fn)
            a["exact"] += sum(1 for x in pairs if x[2] == 0)
            for x in pairs:
                if x[0][1] is not None:
                    a["lerr"].append(x[3]); a["lerr_pct"].append(100 * x[3] / rng_by_chart[cid])
            for p in fp_s:
                detail.append(dict(chart=cid, key=key, kind="FP", index=p[0], price=p[1]))
            for t in fn:
                detail.append(dict(chart=cid, key=key, kind="FN", index=t[0], levels=t[1]))
            for x in pairs:
                if x[2] or (x[0][1] is not None and x[3] > 0.25):
                    detail.append(dict(chart=cid, key=key, kind="TP_offset", index=x[0][0], gt_index=x[1][0], price=x[0][1],
                                       level_error=round(x[3], 3)))
    return agg, detail


def table(agg, types):
    rows = []
    for tier in TIERS + ["ALL"]:
        for t in types + ["ALL"]:
            if tier == "ALL" and t == "ALL":
                ks = list(agg)
            elif tier == "ALL":
                ks = [k for k in agg if k[1] == t]
            elif t == "ALL":
                ks = [k for k in agg if k[0] == tier]
            else:
                ks = [(tier, t)]
            tp = sum(agg[k]["tp"] for k in ks if k in agg); fp = sum(agg[k]["fp"] for k in ks if k in agg)
            fn = sum(agg[k]["fn"] for k in ks if k in agg); un = sum(agg[k]["uns"] for k in ks if k in agg)
            ex = sum(agg[k]["exact"] for k in ks if k in agg)
            le = [x for k in ks if k in agg for x in agg[k]["lerr"]]
            lp = [x for k in ks if k in agg for x in agg[k]["lerr_pct"]]
            if tp + fp + fn == 0:
                continue
            P = tp / (tp + fp) if tp + fp else None
            Rr = tp / (tp + fn) if tp + fn else None
            F = 2 * P * Rr / (P + Rr) if P and Rr else 0.0 if (P is not None and Rr is not None) else None
            rows.append(dict(tier=tier, type=t, gt=tp + fn, predicted=tp + fp, tp=tp, fp=fp, fn=fn, unscored=un,
                             precision=None if P is None else round(P, 3), recall=None if Rr is None else round(Rr, 3),
                             f1=None if F is None else round(F, 3), exact_index_acc=round(ex / tp, 3) if tp else None,
                             level_err_mean=round(statistics.mean(le), 3) if le else None,
                             level_err_median=round(statistics.median(le), 3) if le else None,
                             level_err_pct_range_mean=round(statistics.mean(lp), 2) if lp else None))
    return rows


def write_csv(rows, path):
    if not rows:
        open(path, "w").write("")
        return
    with open(path, "w", newline="") as f:
        keys = []
        for r in rows:
            keys += [k for k in r if k not in keys]
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader(); w.writerows(rows)


def agent_preds(path_dir):
    out, bad = {}, []
    for f in sorted(glob.glob(path_dir + "/*.json")):
        try:
            d = json.load(open(f))
        except Exception as ex:
            bad.append((os.path.basename(f), str(ex))); continue
        if not isinstance(d, dict) or "events" not in d:
            continue
        cid = d.get("chart_id") or os.path.basename(f)[:-5]
        by = defaultdict(list)
        for a in d["events"]:
            try:
                k = key_of(a)
                base = k.split("|")[0]
                if base not in VTYPES:
                    continue
                pr = a.get("price")
                by[k].append((int(a["candle_index"]), float(pr) if pr is not None else None, a))
            except Exception as ex:
                bad.append((cid, "event %r: %s" % (a, ex)))
        out[cid] = dict(by)
    return out, bad


def adjudicate(agents):
    """cluster the three agents' events: same chart / key, indices within TOL, one event per agent per cluster."""
    clusters = []
    charts = sorted(set(c for a in agents.values() for c in a))
    for cid in charts:
        keys = sorted(set(k for a in agents.values() for k in a.get(cid, {})))
        for key in keys:
            pts = sorted(((p[0], p[1], ag) for ag, a in agents.items() for p in a.get(cid, {}).get(key, [])), key=lambda x: (x[0], x[2]))
            used = [False] * len(pts)
            for i, p in enumerate(pts):
                if used[i]:
                    continue
                members = [p]; used[i] = True; seen = {p[2]}
                for j in range(i + 1, len(pts)):
                    q = pts[j]
                    if used[j] or q[2] in seen:
                        continue
                    if abs(q[0] - p[0]) <= TOL:
                        members.append(q); used[j] = True; seen.add(q[2])
                idxs = sorted(m[0] for m in members)
                prs = [m[1] for m in members if m[1] is not None]
                sup = len(seen)
                clusters.append(dict(chart=cid, key=key, index=idxs[len(idxs) // 2], price=round(statistics.median(prs), 2) if prs else None,
                                     agents=sorted(seen), support=sup, indices=idxs,
                                     status="UNANIMOUS" if sup == 3 else "DISPUTED",
                                     adjudication="ACCEPTED_MAJORITY" if sup == 3 or sup == 2 else "REJECTED_MINORITY"))
    return clusters


def main():
    build, gtd, botd, agd, out = sys.argv[1:6]
    os.makedirs(out, exist_ok=True)
    gt = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(gtd + "/*-*.json")}
    bot = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(botd + "/*-*.json")}
    ohlc = {c: load_ohlc("%s/ohlc/%s.csv" % (build, c)) for c in gt}
    rng = {c: max(r[1] for r in v) - min(r[2] for r in v) for c, v in ohlc.items()}
    uns = {c: g["unscored"] for c, g in gt.items()}
    gtv = {c: visual_view(g["events"]) for c, g in gt.items()}
    botv = {c: {k: [(i, lv[0], None) for i, lv in v] for k, v in visual_view(b["events"]).items()} for c, b in bot.items()}
    res = {}

    # (1) bot vs GT: exact field-level equality on every event, setup candidate and timeline row
    FIELDS = ["type", "direction", "index", "level", "id", "related_swing", "related_pool", "confirmation_index", "role",
              "state_before", "state_after", "lifecycle_state", "lifecycle", "group_id", "pools"]
    norm = lambda e: tuple((f, json.dumps(e.get(f), sort_keys=True)) for f in FIELDS)
    exact = Counter(); diffs = []
    for c in sorted(gt):
        g = Counter(norm(e) for e in gt[c]["events"]); b = Counter(norm(e) for e in bot[c]["events"])
        exact["gt_events"] += sum(g.values()); exact["bot_events"] += sum(b.values())
        exact["identical_events"] += sum((g & b).values())
        for e in (g - b).elements():
            diffs.append(dict(chart=c, side="GT_only", event=dict(e)))
        for e in (b - g).elements():
            diffs.append(dict(chart=c, side="BOT_only", event=dict(e)))
        exact["setup_identical_charts"] += gt[c]["setup_candidates"] == bot[c]["setup_candidates"]
        exact["timeline_identical_charts"] += gt[c]["timeline"] == bot[c]["timeline"]
        exact["charts"] += 1
    by_type = Counter((e["type"]) for c in gt for e in gt[c]["events"])
    res["bot_vs_gt_exact"] = dict(exact, gt_events_by_type=dict(by_type), differences=diffs)
    agg, det = score(botv, gtv, uns, ohlc, rng, tol=0)
    res["bot_vs_gt_visual_types"] = table(agg, VTYPES)
    write_csv(res["bot_vs_gt_visual_types"], out + "/bot_vs_gt_metrics.csv")
    json.dump(diffs, open(out + "/bot_vs_gt_differences.json", "w"), indent=1)

    # (2) agents vs GT
    agents, bad = {}, {}
    for ad in sorted(glob.glob(agd + "/AGENT_*")):
        name = os.path.basename(ad)
        agents[name], bad[name] = agent_preds(ad)
    res["agent_parse_errors"] = bad
    res["agents_vs_gt"] = {}
    for name, pr in agents.items():
        agg, det = score(pr, gtv, uns, ohlc, rng)
        rows = table(agg, VTYPES)
        res["agents_vs_gt"][name] = dict(charts_annotated=sorted(pr), metrics=rows)
        write_csv(rows, "%s/%s_vs_gt_metrics.csv" % (out, name))
        write_csv(det, "%s/%s_vs_gt_details.csv" % (out, name))

    # (3) adjudication + bot vs adjudicated visual annotations
    cl = adjudicate(agents)
    write_csv(cl, out + "/adjudication_clusters.csv")
    for x in cl:                                         # rule-data note for disputed clusters (separate from the vote)
        t = gtv.get(x["chart"], {}).get(x["key"], [])
        x["gt_supported"] = any(abs(i - x["index"]) <= TOL for i, _ in t)
    write_csv(cl, out + "/adjudication_clusters.csv")
    adj = defaultdict(lambda: defaultdict(list))
    for x in cl:
        if x["adjudication"] == "ACCEPTED_MAJORITY":
            adj[x["chart"]][x["key"]].append((x["index"], [x["price"]] if x["price"] is not None else [0.0]))
    adjv = {c: dict(v) for c, v in adj.items()}
    for c in gt:
        adjv.setdefault(c, {})
    agg, det = score(botv, adjv, {}, ohlc, rng)
    res["bot_vs_adjudicated_visual"] = table(agg, VTYPES)
    write_csv(res["bot_vs_adjudicated_visual"], out + "/bot_vs_adjudicated_visual_metrics.csv")
    write_csv(det, out + "/bot_vs_adjudicated_visual_details.csv")
    agg, det = score({c: {k: [(i, lv[0], None) for i, lv in v] for k, v in adjv[c].items()} for c in adjv}, gtv, uns, ohlc, rng)
    res["adjudicated_visual_vs_gt"] = table(agg, VTYPES)
    write_csv(res["adjudicated_visual_vs_gt"], out + "/adjudicated_visual_vs_gt_metrics.csv")
    res["adjudication_summary"] = dict(Counter((x["status"], x["support"]) for x in cl).items()) and \
        {"%s_support%d" % k: v for k, v in Counter((x["status"], x["support"]) for x in cl).items()}
    res["disputed_gt_support"] = {"%s|support%d|gt_supported=%s" % k: v for k, v in
                                  Counter((x["key"].split("|")[0], x["support"], x["gt_supported"]) for x in cl if x["status"] == "DISPUTED").items()}
    # pairwise agent agreement (F1 of A against B as reference)
    pw = {}
    names = sorted(agents)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = agents[names[i]], agents[names[j]]
            ref = {c: {k: [(p[0], [p[1] if p[1] is not None else 0.0]) for p in v] for k, v in b.get(c, {}).items()} for c in gt}
            agg, _ = score(a, ref, {}, ohlc, rng)
            allrow = [r for r in table(agg, VTYPES) if r["tier"] == "ALL"]
            pw["%s~%s" % (names[i], names[j])] = {r["type"]: r["f1"] for r in allrow}
    res["pairwise_agent_f1"] = pw
    json.dump(res, open(out + "/comparison_results.json", "w"), indent=1, default=str)
    print(json.dumps(dict(bot_vs_gt=dict(exact), agents=list(agents), parse_errors={k: len(v) for k, v in bad.items()},
                          adjudication=res["adjudication_summary"]), indent=1, default=str))


if __name__ == "__main__":
    main()
