"""Independent structure oracle written from the spec TEXT (PHASE1_2 D1-D5, A2-A8, SW, BOS-001..005/D4, 17.R SR-1..SR-6).
Extends the struct_audit oracle (incremental, sticky = SR-1) with SR-2 (establishment fallback), SR-3 (confirming BOS
reference must be confirmed at or after the CHoCH candle), SR-5 (opposite BOS during TRANSITION restores the prior
structure; both directions on one candle = ambiguous, no change), SR-6 (establishment rejected when the close is already
beyond the candidate protected level). It does not import scanner_v6.structure. Swings: SW-001..005 (strict L2/R2)."""
from collections import defaultdict


def o_swings(cs, L=2, R=2):
    out = []
    n = len(cs)
    for i in range(L, n - R):
        win = list(range(i - L, i)) + list(range(i + 1, i + R + 1))
        if all(cs[i].high > cs[j].high for j in win):
            out.append(dict(kind="H", idx=i, conf=i + R, price=cs[i].high))
        if all(cs[i].low < cs[j].low for j in win):
            out.append(dict(kind="L", idx=i, conf=i + R, price=cs[i].low))
    return out


def oracle2(cs, R=2):
    sw = o_swings(cs, R=R)
    by_conf = defaultdict(list)
    for s in sw:
        by_conf[s["conf"]].append(s)
    known, latest, used = [], {"H": None, "L": None}, set()
    state = "UNKNOWN"
    active = {"bullish": None, "bearish": None}        # (bos_k, swing) P-B origin
    min_bos = {"bullish": -1, "bearish": -1}
    fallback = {"bullish": None, "bearish": None}      # SR-2
    consumed, pending = set(), []
    choch_k = None
    tl, events, bos_all, roles = [], [], [], []
    sid = lambda s: (s["kind"], s["idx"])

    def prot():
        if state not in ("BULLISH", "BEARISH"):
            return None
        d = state.lower()
        fb = fallback[d]
        if fb is not None and sid(fb) not in consumed:
            return fb
        a = active[d]
        if a is None or a[0] < min_bos[d] or sid(a[1]) in consumed:
            return None
        return a[1]

    for k, c in enumerate(cs):
        pre, p = state, prot()
        bos = []
        for kind, d in (("H", "bullish"), ("L", "bearish")):                    # D5 (1)
            r = latest[kind]
            if r and sid(r) not in used and (c.close > r["price"] if kind == "H" else c.close < r["price"]):
                used.add(sid(r))
                bos.append(dict(dir=d, k=k, ref=r))
        bos_all += bos
        ch = None
        if pre in ("BULLISH", "BEARISH") and p is not None:                     # D5 (2), CHU04 strict
            if pre == "BULLISH" and c.close < p["price"]:
                ch = "bearish"
            elif pre == "BEARISH" and c.close > p["price"]:
                ch = "bullish"
        role = {}
        if ch:                                                                  # D5 (3)
            consumed.add(sid(p))
            for dd in fallback:
                fallback[dd] = None                                             # SR-2.5 any CHoCH ends the fallback
            state = "TRANSITION(%s)" % ch
            choch_k = k
            events.append(("CHOCH", k, ch, p["price"], pre, state))
            for b in bos:
                role[id(b)] = "COUNTER_STRUCTURE" if b["dir"] != pre.lower() else "CONTINUATION"
        elif pre.startswith("TRANSITION"):
            d = pre[11:-1]
            opp = "bearish" if d == "bullish" else "bullish"
            conf_ok = [b for b in bos if b["dir"] == d and b["ref"]["conf"] >= choch_k]          # SR-3
            same_rej = [b for b in bos if b["dir"] == d and b["ref"]["conf"] < choch_k]
            opp_b = [b for b in bos if b["dir"] == opp]
            for b in same_rej:
                role[id(b)] = "TRANSITION_REF_BEFORE_CHOCH"
            if conf_ok and opp_b:                                                                # SR-5.5
                for b in conf_ok + opp_b:
                    role[id(b)] = "TRANSITION_AMBIGUOUS"
            elif conf_ok:
                state = d.upper()
                min_bos[d] = k
                events.append(("REVERSAL_CONFIRMED", k, d, None, pre, state))
                for b in conf_ok:
                    role[id(b)] = "REVERSAL_CONFIRMING"
            elif opp_b:                                                                          # SR-5
                state = opp.upper()
                min_bos[opp] = k
                events.append(("REVERSAL_INVALIDATED", k, opp, None, pre, state))
                for b in opp_b:
                    role[id(b)] = "REVERSAL_INVALIDATING"
        else:
            for b in bos:
                role[id(b)] = "PRE_STRUCTURE" if pre == "UNKNOWN" else \
                    ("CONTINUATION" if b["dir"] == pre.lower() else "COUNTER_STRUCTURE")
        for b in bos:
            roles.append((b["dir"], b["k"], b["ref"]["idx"], role.get(id(b), "?")))
            pending.append(dict(dir=b["dir"], ref=b["ref"]["idx"], k=b["k"], origin=None))
        for s in by_conf[k]:                                                    # D5 (4)
            known.append(s)
            cur = latest[s["kind"]]
            if cur is None or (s["conf"], s["idx"]) > (cur["conf"], cur["idx"]):
                latest[s["kind"]] = s
        keep = []
        for pd in pending:                                                      # D2 P-B, SR-1 sticky
            need = "L" if pd["dir"] == "bullish" else "H"
            cands = [s for s in known if s["kind"] == need and pd["ref"] < s["idx"] <= pd["k"]]
            if cands:
                o = min(cands, key=lambda s: s["price"]) if need == "L" else max(cands, key=lambda s: s["price"])
                if pd["origin"] is None or sid(o) != sid(pd["origin"]):
                    pd["origin"] = o
                    prev = [s for s in known if s["kind"] == need and s["idx"] < o["idx"]]
                    ps = max(prev, key=lambda s: s["idx"]) if prev else None
                    ok = ps is not None and (o["price"] > ps["price"] if need == "L" else o["price"] < ps["price"])
                    cur = active[pd["dir"]]
                    if ok and (cur is None or pd["k"] >= cur[0]):
                        active[pd["dir"]] = (pd["k"], o)
                        if state == pd["dir"].upper() and fallback[pd["dir"]] is not None:
                            fallback[pd["dir"]] = None                          # SR-2.4 permanent replacement
            if k < pd["k"] + R:
                keep.append(pd)
        pending = keep
        if state == "UNKNOWN" and by_conf[k]:                                   # A2-A4 establishment
            hs = sorted((s for s in known if s["kind"] == "H"), key=lambda s: (s["conf"], s["idx"]))
            ls_ = sorted((s for s in known if s["kind"] == "L"), key=lambda s: (s["conf"], s["idx"]))
            if len(hs) >= 2 and len(ls_) >= 2:
                h1, h2, l1, l2 = hs[-2]["price"], hs[-1]["price"], ls_[-2]["price"], ls_[-1]["price"]
                d = "bullish" if h2 > h1 and l2 > l1 else "bearish" if h2 < h1 and l2 < l1 else None
                if d:
                    a = active[d]
                    has_origin = a is not None and a[0] >= min_bos[d] and sid(a[1]) not in consumed
                    cand = a[1] if has_origin else (ls_[-1] if d == "bullish" else hs[-1])           # SR-6.1 / SR-2.2
                    beyond = c.close < cand["price"] if d == "bullish" else c.close > cand["price"]
                    if beyond:
                        events.append(("ESTABLISHMENT_REJECTED", k, d, cand["price"], "UNKNOWN", "UNKNOWN"))
                    else:
                        state = d.upper()
                        min_bos[d] = -1
                        fallback[d] = None if has_origin else cand
                        events.append(("ESTABLISHED", k, d, None, "UNKNOWN", state))
        q = prot()
        tl.append((k, state, q["price"] if q else None, (q["kind"], q["idx"]) if q else None))
    return dict(tl=tl, events=events, bos=bos_all, swings=sw, roles=roles)
