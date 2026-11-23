import sys, json
import os as _os
V6_ROOT = _os.environ.get("V6_ROOT", "/home/claude/v6_wt")
sys.path.insert(0, V6_ROOT); sys.path.insert(0, _os.path.join(V6_ROOT, "tests", "scanner_v6"))
from s1_options import run, OPTIONS
import test_defect_fixes as T
base = T.case_rows(T.CASES["CHD01"])[:16]
V = {
 "V1_base_lowlow_on_BOS_candle": [(107.5,110,107.5,109),(109,111,108,110),(110,117,104,116.5),(116.5,118,104.5,117),(117,119,106,118),(118,118.5,105,105.5)],
 "V2_late_low_on_k_minus_1": [(107.5,110,107.5,109),(109,111,108,110),(110,112,104,111),(111,117,105,116.5),(116.5,118,105.5,117),(117,119,106,118),(118,118.5,105,105.5)],
 "V3_late_low_below_pre_leg_low": [(107.5,110,107.5,109),(109,111,108,110),(110,117,100,116.5),(116.5,118,100.5,117),(117,119,102,118),(118,118.5,101.5,102)],
 "V4_next_continuation_BOS": [(107.5,110,107.5,109),(109,111,108,110),(110,117,104,116.5),(116.5,118,104.5,117),(117,119,106,118),(118,118.5,115,116),(116,117,114,115),(115,116,112,113),(113,121,113,120.5),(120.5,121.5,114,115),(115,116,110,111)],
 "V5_close_between_late_and_active": [(107.5,110,107.5,109),(109,111,108,110),(110,117,104,116.5),(116.5,118,104.5,117),(117,119,106,118),(118,118.5,105,105.5)],
 "V6_close_below_late_low": [(107.5,110,107.5,109),(109,111,108,110),(110,117,104,116.5),(116.5,118,104.5,117),(117,119,106,118),(118,118.5,103,103.5)],
}
out = {}
for name, ext in V.items():
    rows = base + ext
    for mir in (False, True):
        r = T.mirror(rows) if mir else rows
        s = T.series_rows(r)
        for opt in OPTIONS:
            st, ev = run(s, opt)
            prot = [(t.index+1, t.state, t.protected_price) for t in st.timeline[15:]]
            out[(name, mir, opt)] = dict(
                bos=[(b.direction.value, b.index+1, b.level) for b in st.bos_events],
                events=[(type(e).__name__, e.index+1, getattr(e,'state_after',None), getattr(e,'level',None)) for e in ev if type(e).__name__!="StructureStateChange" or e.cause!="CHOCH"],
                notes=[(n.index+1, n.code, n.swing_id.split(":")[2] if n.swing_id else None) for n in st.tracker.notes if n.index>=15],
                s1=[(k+1, d, old, new, oa, ok) for k, _, d, old, new, oa, ok in st.tracker.s1_events],
                timeline=prot)
for name in V:
    print("=====", name)
    for mir in (False, True):
        for opt in OPTIONS:
            o = out[(name, mir, opt)]
            print(" %-6s %-22s events=%s" % ("MIRROR" if mir else "bull", opt, o["events"]))
            if not mir:
                print("        protected c16.. =", [(c, p) for c, s_, p in o["timeline"]], "| final", o["timeline"][-1][1])
                print("        notes =", o["notes"], "| s1 =", o["s1"])
json.dump({"|".join([k[0], "mirror" if k[1] else "bull", k[2]]): v for k, v in out.items()}, open("s1_variants_out.json", "w"), indent=1, default=str)
