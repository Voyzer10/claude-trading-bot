import glob, os, sys
S = "/tmp/claude-0/-home-claude/68bdf1fe-91d1-59e2-8fe7-bdfe79e88346/scratchpad"
sys.path.insert(0, S + "/vbt/tools")
from coverage import load
from oracle2 import oracle2
from scanner_v6.structure.choch import analyze_structure
tot = dict(charts=0, ev=0, tl=0, roles=0)
paths = sorted(glob.glob(sys.argv[1] + "/ohlc/*.csv")) if sys.argv[1] != "corpus" else None
def v6n(cs):
    st = analyze_structure(cs)
    sw = {s.id: s for s in st.swings}
    tl = [(x.index, x.state, x.protected_price, (sw[x.protected_swing_id].kind.value[0].upper(), sw[x.protected_swing_id].index)
           if x.protected_swing_id else None) for x in st.timeline]
    ev = []
    for e in st.events:
        n = type(e).__name__
        if n == "CHoCHBreak": ev.append(("CHOCH", e.index, e.direction.value))
        elif n == "StructureStateChange" and e.cause in ("REVERSAL_CONFIRMED", "ESTABLISHED", "REVERSAL_INVALIDATED"):
            ev.append((e.cause, e.index, e.state_after.lower()))
    roles = sorted((b.direction.value, b.index, sw[b.broken_swing_id].index, st.bos_roles[b.id]) for b in st.bos)
    return ev, tl, roles
def items():
    if paths is not None:
        for p in paths: yield os.path.basename(p)[:-4], load(p)
    else:
        src = open(S + "/struct_audit/tools/audit.py").read().replace("\nmain()\n", "\n")
        g = {}; sys.argv = [sys.argv[0], "/dev/null"]; exec(compile(src, "audit.py", "exec"), g)
        for corp, cid, cs in g["corpus"](): yield corp + "/" + cid, cs
for cid, cs in items():
    ev, tl, roles = v6n(cs)
    o = oracle2(cs)
    oev = [(e[0], e[1], e[2]) for e in o["events"] if e[0] != "ESTABLISHMENT_REJECTED"]
    tld = [(a, b) for a, b in zip(tl, o["tl"]) if a != b]
    rok = roles == sorted(o["roles"])
    tot["charts"] += 1; tot["ev"] += ev != oev; tot["tl"] += bool(tld); tot["roles"] += not rok
    if ev != oev or tld or not rok:
        print(cid, "events", ev == oev, "tl_diff", len(tld), "roles", rok)
        if ev != oev: print("   v6", ev, "\n   o2", oev)
        if tld: print("   tl", tld[:2])
        if not rok: print("   roles", [x for x in roles if x not in o["roles"]][:4], [x for x in sorted(o["roles"]) if x not in roles][:4])
print("mismatching charts:", tot)
