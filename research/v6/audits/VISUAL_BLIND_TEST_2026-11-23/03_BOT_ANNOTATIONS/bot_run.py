"""Phase 5: run V6 (scanner_v6, the bot) on the OHLC fixtures (never on images or annotations) and export annotations.
cwd = repo. usage: bot_run.py <build_dir> <out_dir> <charts_dir>
Writes <out_dir>/<chart>.json, bot_events.csv, marked/<chart>_bot.png, replay_checks.json."""
import csv, glob, json, os, sys
from datetime import datetime
sys.path.insert(0, os.getcwd())
from scanner_v6.data.candle_models import CandleSeries
from scanner_v6.liquidity.setup_sweep import SetupSweepStream, analyze_setup_sweeps
from scanner_v6.liquidity.sweep import analyze_liquidity, LiquidityStream
from scanner_v6.structure.choch import analyze_structure, CHoCHBreak, StructureStateChange, StructureStream

TIER = {"E": "EASY", "M": "MEDIUM", "H": "HARD", "X": "EXTREME"}


def load(p):
    rows = list(csv.DictReader(open(p)))
    return CandleSeries.from_rows([(datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")), float(r["open"]),
                                    float(r["high"]), float(r["low"]), float(r["close"])) for r in rows],
                                  os.path.basename(p)[:-4], "5m")


def events(cs):
    st = analyze_structure(cs)
    lq = analyze_liquidity(cs)
    su = analyze_setup_sweeps(cs)
    sw = {s.id: s for s in st.swings}
    ev = []
    for s in st.swings:
        ev.append(dict(type="SWING_HIGH" if s.kind.value == "high" else "SWING_LOW", index=s.index, level=s.price,
                       id=s.id, confirmation_index=s.confirmed_index))
    for b in st.bos:
        ev.append(dict(type="BOS", direction=b.direction.value, index=b.index, level=b.level, id=b.id,
                       related_swing=b.broken_swing_id, confirmation_index=b.index, role=st.bos_roles[b.id]))
    for e in st.events:
        if isinstance(e, CHoCHBreak):
            ev.append(dict(type="CHOCH", direction=e.direction.value, index=e.index, level=e.level, id=e.id,
                           related_swing=[r for r in e.related if r.startswith("swing:")][0], confirmation_index=e.index,
                           state_before=e.state_before, state_after=e.state_after))
        elif isinstance(e, StructureStateChange) and e.cause in ("ESTABLISHED", "REVERSAL_CONFIRMED", "REVERSAL_INVALIDATED"):
            ev.append(dict(type="STATE_" + e.cause, direction=e.state_after.lower(), index=e.index, state_before=e.state_before,
                           state_after=e.state_after, confirmation_index=e.index))
    final = lq.final_state
    hist = {}
    for e in lq.events:
        hist.setdefault(e.pool_id, []).append([e.index, e.event_type])
    for p in lq.pools:
        side = "BSL" if p.side.value == "above" else "SSL"
        ev.append(dict(type="POOL_" + side, index=sw[p.related[0]].index, level=p.price, id=p.id,
                       confirmation_index=p.stamp.confirmed_index if hasattr(p.stamp, "confirmed_index") else sw[p.related[0]].confirmed_index,
                       lifecycle_state=final[p.id], lifecycle=hist.get(p.id, [])))
    for e in lq.events:
        ev.append(dict(type="%s_%s" % (e.event_type, e.side), index=e.index, level=e.level, id=e.id, related_pool=e.pool_id,
                       confirmation_index=e.index, state_before=e.state_before, state_after=e.state_after, group_id=e.group_id))
    for g in lq.groups:
        ev.append(dict(type="SWEEP_GROUP_" + g.side, index=g.index, id=g.id, pools=sorted(g.pool_ids), confirmation_index=g.index))
    setups = [dict(bos_id=c.bos_id, bos_index=c.bos_index, setup_side=c.setup_side, sweep_side=c.sweep_side,
                   group_id=c.group_id, index=c.index, status=c.status, closed_index=c.closed_index, closed_by=c.closed_by)
              for c in su.candidates]
    tl = [dict(index=x.index, state=x.state, protected_level=x.protected_price, protected_swing=x.protected_swing_id)
          for x in st.timeline]
    return dict(events=sorted(ev, key=lambda e: (e["index"], e["type"])), setup_candidates=setups, timeline=tl,
                diagnostics=[dict(index=d.index, code=d.code, detail=d.detail) for d in st.diagnostics] +
                            [dict(index=d.index, code=d.code, detail=d.detail) for d in su.diagnostics])


def replay(cs):
    """prefix replay / no-look-ahead: the state after candle k of the full run equals a run on candles 0..k only;
    stream == batch."""
    full_s = analyze_setup_sweeps(cs)
    full_l = analyze_liquidity(cs)
    full_t = analyze_structure(cs).timeline
    bad = []
    for k in range(len(cs)):
        p = cs.upto(k)
        if analyze_setup_sweeps(p).snapshots[-1] != full_s.snapshots[k]:
            bad.append((k, "setup snapshot"))
        pl = analyze_liquidity(p)
        if pl.timeline[-1] != full_l.timeline[k] or [e.id for e in pl.events] != [e.id for e in full_l.events if e.index <= k]:
            bad.append((k, "liquidity"))
        if analyze_structure(p).timeline[-1] != full_t[k]:
            bad.append((k, "structure timeline"))
    st = SetupSweepStream()
    for c in cs:
        st.on_candle(c)
    parity = st.candidates == full_s.candidates and st.diagnostics == full_s.diagnostics
    return dict(prefix_mismatches=bad, stream_batch_parity=parity, candles=len(cs))


def draw(png_in, png_out, geo, ev):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(png_in).convert("RGB")
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 11)
    except Exception:
        f = ImageFont.load_default()
    X = lambda i: geo["ax_left"] + (i - geo["xmin"]) / (geo["xmax"] - geo["xmin"]) * (geo["ax_right"] - geo["ax_left"])
    Y = lambda p: geo["ax_top"] + (geo["ymax"] - p) / (geo["ymax"] - geo["ymin"]) * (geo["ax_bottom"] - geo["ax_top"])
    for e in ev:
        t = e["type"]
        if t in ("POOL_BSL", "POOL_SSL"):
            col = (230, 126, 34) if t == "POOL_BSL" else (22, 160, 133)
            d.line([X(e["index"]) - 6, Y(e["level"]), X(e["index"]) + 14, Y(e["level"])], fill=col, width=2)
    for e in ev:
        t = e["type"]
        if t in ("BOS", "CHOCH"):
            col = (41, 98, 255) if t == "BOS" else (142, 68, 173)
            src = [x for x in ev if x.get("id") == e.get("related_swing")]
            x0 = X(src[0]["index"]) if src else X(e["index"]) - 30
            d.line([x0, Y(e["level"]), X(e["index"]), Y(e["level"])], fill=col, width=2)
            lab = ("BOS" if t == "BOS" else "CHoCH") + ("↑" if e["direction"] == "bullish" else "↓")
            d.text((X(e["index"]) + 3, Y(e["level"]) - (16 if e["direction"] == "bullish" else -4)), lab, fill=col, font=f)
        elif t.startswith(("SWEEP_BSL", "SWEEP_SSL", "REPEAT_SWEEP")):
            side = t[-3:]
            y = Y(e["level"])
            d.ellipse([X(e["index"]) - 5, y - 5, X(e["index"]) + 5, y + 5], outline=(211, 84, 0) if side == "BSL" else (0, 128, 128), width=2)
            d.text((X(e["index"]) - 14, y + (-18 if side == "BSL" else 7)), ("SW-" if t.startswith("SWEEP") else "RS-") + side, fill=(80, 80, 80), font=f)
        elif t.startswith("TAKEN"):
            d.text((X(e["index"]) - 4, Y(e["level"]) - 6), "x", fill=(120, 120, 120), font=f)
    d.text((geo["ax_left"] + 8, geo["ax_top"] + 6), "V6 bot (OHLC-based) annotations", fill=(0, 0, 0), font=f)
    im.save(png_out)


def main():
    build, out, charts = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out + "/marked", exist_ok=True)
    geo = json.load(open(build + "/geometry.json"))
    rows, rep = [], {}
    for p in sorted(glob.glob(build + "/ohlc/*.csv")):
        cid = os.path.basename(p)[:-4]
        cs = load(p)
        r = events(cs)
        r.update(chart_id=cid, source="V6 scanner_v6 on OHLC CSV (no image input)")
        json.dump(r, open("%s/%s.json" % (out, cid), "w"), indent=1)
        rep[cid] = replay(cs)
        draw("%s/%s/%s.png" % (charts, TIER[cid[0]], cid), "%s/marked/%s_bot.png" % (out, cid), geo[cid], r["events"])
        for e in r["events"]:
            rows.append([cid, e["type"], e.get("direction", ""), e["index"], e.get("level", ""), e.get("id", ""),
                         e.get("related_swing", e.get("related_pool", "")), e.get("confirmation_index", ""),
                         e.get("lifecycle_state", e.get("state_after", "")), e.get("role", "")])
    with open(out + "/bot_events.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["chart_id", "event_type", "direction", "candle_index", "level", "event_id", "related_swing_or_pool",
                    "confirmation_index", "lifecycle_or_state_after", "bos_role"])
        w.writerows(rows)
    json.dump(rep, open(out + "/replay_checks.json", "w"), indent=1)
    print("bot exported", len(rep), "charts; prefix mismatches:", sum(len(v["prefix_mismatches"]) for v in rep.values()),
          "; stream/batch parity:", all(v["stream_batch_parity"] for v in rep.values()))


if __name__ == "__main__":
    main()
