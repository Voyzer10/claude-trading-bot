"""How often does the CURRENT A5 base (the swing immediately before the origin) differ from the pre-leg swing
(last same-kind swing at or before the BOS reference)? Official implementation only; read-only."""
import sys, os, glob, collections
V6_ROOT = os.environ.get("V6_ROOT", "/home/claude/v6_wt"); sys.path.insert(0, V6_ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r1_eval as R
from scanner_v6.structure.choch import analyze_structure
from scanner_v6.data.candle_models import CandleSeries
from scanner_v6.models import SwingKind
from datetime import datetime, timezone
raw = sys.argv[1]
tot = collections.Counter()
for f in sorted(glob.glob(os.path.join(raw, "*.NS_5m.json"))):
    rows, meta, qc = R.load_raw(f)
    for tf in ("5m", "15m", "1h"):
        bars = R.as_bars(rows) if tf == "5m" else R.resample(rows, {"15m": 15, "1h": 60}[tf])
        s = CandleSeries.from_rows([(datetime.fromtimestamp(b["t"], timezone.utc), b["o"], b["h"], b["l"], b["c"], b["v"]) for b in bars])
        r = analyze_structure(s)
        sw = {x.id: x for x in r.swings}
        bidx = {b.id: b for b in r.bos}
        final = {}
        for d in r.diagnostics:
            if d.code in ("ACTIVATED", "NOT_QUALIFIED") and d.swing_id:
                bid = d.detail.rsplit("(", 1)[1].rstrip(")")
                final[bid] = (sw[d.swing_id], d.code)
        for bid, (o, code) in final.items():
            b = bidx[bid]; ref = sw[b.broken_swing_id]
            kind = o.kind
            same = [x for x in r.swings if x.kind is kind and x.confirmed_index <= b.index + 2]
            inleg = [x for x in same if ref.index < x.index < o.index]
            pre = [x for x in same if x.index <= ref.index]
            pre_s = max(pre, key=lambda x: x.index) if pre else None
            ok_pre = pre_s is not None and (o.price > pre_s.price if kind is SwingKind.LOW else o.price < pre_s.price)
            tot[(tf, "legs")] += 1
            if inleg:
                tot[(tf, "legs_with_in_leg_swing_before_origin")] += 1
                if code == "NOT_QUALIFIED" and ok_pre:
                    tot[(tf, "rejected_by_in_leg_base_but_HL_vs_pre_leg")] += 1
            tot[(tf, code)] += 1
for tf in ("5m", "15m", "1h"):
    print(tf, {k[1]: v for k, v in tot.items() if k[0] == tf})
