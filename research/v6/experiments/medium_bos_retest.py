#!/usr/bin/env python3
"""Blind visual retest of the two Medium-level BOS scenarios (21 Nov 2026). Research only, no orders.

  python research/v6/experiments/medium_bos_retest.py render   # draws the unmarked charts + axis calibration
  python research/v6/experiments/medium_bos_retest.py grade    # reads ONLY the PNGs (+ axis calibration), then grades

render: draws each scenario from the regression fixture (same OHLC, same candle numbers 1..14) into
        research/v6/retest/medium/<id>.png, with NO marking, and writes axis_calibration.json (the pixel rows of two
        price gridlines and the plot's x range: the information a reader takes from the axis labels). Nothing about
        swings or BOS is written there.
grade:  (1) digitises every candle from the PNG pixels alone (colour = direction, body / wick extents = O H L C),
        (2) runs the scanner_v6 swing detector and the approved BOS rules on the digitised candles,
        (3) only then opens research/v6/retest/answer_keys/medium_answer_key.json and compares: reference swing
            validity, BOS / NO BOS, direction, exact break candle and reference price.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "scanner_v6"))
CHARTS = os.path.join(ROOT, "research", "v6", "retest", "medium")
KEYS = os.path.join(ROOT, "research", "v6", "retest", "answer_keys", "medium_answer_key.json")
FIXTURE = os.path.join(ROOT, "tests", "scanner_v6", "fixtures", "regression", "easy_bos.json")
GREEN, RED = "#169C77", "#D94F4F"


def render():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    data = json.load(open(FIXTURE))
    os.makedirs(CHARTS, exist_ok=True)
    cal = {}
    for i, case in enumerate(data["cases"], 1):
        cs = case["candles"]
        fig, ax = plt.subplots(figsize=(8.9, 5.1), dpi=200)
        for x in cs:
            n, o, h, l, c = x["candle"], x["o"], x["h"], x["l"], x["c"]
            colr = GREEN if c >= o else RED
            ax.vlines(n, l, h, color=colr, linewidth=1.6)
            ax.add_patch(plt.Rectangle((n - 0.3, min(o, c)), 0.6, max(abs(c - o), 1e-9), color=colr))
        lo, hi = min(x["l"] for x in cs), max(x["h"] for x in cs)
        ax.set_ylim(lo - 1.5, hi + 1.5)
        ax.set_xlim(0.3, len(cs) + 0.7)
        ax.set_xticks(range(1, len(cs) + 1))
        ax.grid(True, linestyle="--", alpha=0.25)
        ax.set_title("V6 Medium BOS retest %d (unmarked)" % i, loc="left")
        ax.set_xlabel("Candle number")
        ax.set_ylabel("Price")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        fig.tight_layout()
        fig.canvas.draw()
        H = fig.canvas.get_width_height()[1] * 1.0
        yt = [t for t in ax.get_yticks() if lo - 1.5 <= t <= hi + 1.5]
        a, b = yt[0], yt[-1]
        ya = H - ax.transData.transform((1, a))[1]
        yb = H - ax.transData.transform((1, b))[1]
        name = "retest_%d.png" % i
        fig.savefig(os.path.join(CHARTS, name), dpi=200)
        plt.close(fig)
        cal[name] = {"price_a": float(a), "pixel_row_a": float(ya), "price_b": float(b), "pixel_row_b": float(yb),
                     "price_tick": 0.5}
    json.dump(cal, open(os.path.join(CHARTS, "axis_calibration.json"), "w"), indent=1)
    print("rendered", sorted(cal))


def digitise(path, cal):
    """O H L C per candle from pixels only."""
    import numpy as np
    from PIL import Image
    im = np.array(Image.open(path).convert("RGB")).astype(int)
    r, g = im[..., 0], im[..., 1]
    green = (g > r + 40) & (g > 120)
    red = (r > g + 60) & (r > 150)
    col = green | red
    xs = np.where(col.sum(axis=0) > 10)[0]
    groups, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] > 2:
            groups.append(cur)
            cur = [x]
        else:
            cur.append(x)
    groups.append(cur)
    groups = [gr for gr in groups if len(gr) > 15]                                # candle bodies
    a = (cal["pixel_row_b"] - cal["pixel_row_a"]) / (cal["price_b"] - cal["price_a"])
    to_price = lambda row: cal["price_a"] + (row - cal["pixel_row_a"]) / a        # noqa: E731
    q = lambda p: round(round(p / cal["price_tick"]) * cal["price_tick"], 4)     # noqa: E731
    out = []
    for gr in groups:
        cx = int(round((gr[0] + gr[-1]) / 2))
        body_x = gr[0] + 2
        wick = np.where(col[:, cx])[0]
        body = np.where(col[:, body_x])[0]
        up = green[body[len(body) // 2], body_x]
        top, bot = q(to_price(body.min())), q(to_price(body.max()))
        h, l = q(to_price(wick.min())), q(to_price(wick.max()))
        o, c = (bot, top) if up else (top, bot)
        out.append((o, h, l, c))
    return out


def grade():
    from scanner_v6.data.candle_models import CandleSeries
    from scanner_v6.structure.swings import detect_swings, unresolved_equal_levels
    from test_regression_medium_bos import approved_bos
    cal = json.load(open(os.path.join(CHARTS, "axis_calibration.json")))
    t0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
    answers = {}
    for name in sorted(cal):
        ohlc = digitise(os.path.join(CHARTS, name), cal[name])
        s = CandleSeries.from_rows([(t0 + timedelta(minutes=5 * i), *r, 0) for i, r in enumerate(ohlc)])
        sw = detect_swings(s)
        bos = approved_bos(s, lambda k, f=sw: [e for e in f if e.confirmed_index <= k])
        answers[name] = {
            "candles_read": len(ohlc),
            "swings": [[e.kind.value, e.index + 1, e.confirmed_index + 1, e.price] for e in sw],
            "equal_levels_rejected": sorted({(x.kind.value, x.price) for x in unresolved_equal_levels(s)}),
            "bos": [[b["direction"], b["break_index"] + 1, b["reference_price"], b["reference_index"] + 1]
                    for b in bos]}
    # only now: the answer key
    key = json.load(open(KEYS))
    ok = True
    for name, want in key["charts"].items():
        got = answers[name]
        rows = [("candles", got["candles_read"], want["candles"]),
                ("swings", got["swings"], want["swings"]),
                ("equal levels (not swings)", [list(x) for x in got["equal_levels_rejected"]], want["equal_levels_rejected"]),
                ("BOS [dir, break candle, ref price, ref candle]", got["bos"], want["bos"])]
        for what, g, w in rows:
            res = "PASS" if g == w else "FAIL"
            ok &= res == "PASS"
            print("%-14s %-48s %s  got %s  key %s" % (name, what, res, g, w))
    print("\nRETEST: %s" % ("ALL PASS" if ok else "FAILURES"))
    return 0 if ok else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "render":
        render()
    elif cmd == "grade":
        sys.exit(grade())
    else:
        print(__doc__)
