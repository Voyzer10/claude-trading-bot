"""V6 visual blind test: deterministic synthetic OHLC generator (PAPER / RESEARCH ONLY).

Each scenario = fixed seed + waypoint legs (+ optional engineered candles). A mirror chart is the exact price mirror
p' = 200 - p (high <-> low), so every bullish case has a bearish twin with identical geometry. Prices are rounded to 2
decimals; random.Random(seed) only (no numpy RNG) so regeneration is bit-identical across machines.

usage: python3 -I gen.py <out_dir>      -> <out_dir>/ohlc/<chart>.csv + <out_dir>/scenarios.json
"""
import csv, json, os, random, sys
from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
BAR = timedelta(minutes=5)

# (scenario_id, tier, seed, n_target, base_vol, wick_vol, legs[(bars, target)], injections{k: kind}, description)
SCENARIOS = [
    ("S-E1", "EASY", 51101, 0.10, 0.18,
     [(8, 102), (5, 100.8), (8, 104), (5, 102.6), (8, 106), (5, 104.6), (8, 108), (7, 104), (5, 105.6), (8, 101.5),
      (5, 103), (8, 99)], {},
     "clean uptrend with pullbacks, then reversal (CHoCH, confirming BOS) and downtrend"),
    ("S-E2", "EASY", 51102, 0.12, 0.20,
     [(6, 98.5), (6, 101.5), (5, 100.2), (7, 103.5), (5, 102), (7, 105.5), (5, 104), (6, 107), (6, 103.4),
      (6, 104.8), (6, 101.2), (5, 102.4), (8, 98.6)], {},
     "trend with a clear top, protected-low break, lower highs"),
    ("S-M1", "MEDIUM", 52201, 0.16, 0.26,
     [(8, 101), (6, 99.4), (6, 101.2), (6, 99.3), (7, 101.4), (5, 99.6), (8, 104), (5, 102.4), (7, 105.4),
      (6, 103.2), (7, 106.4), (6, 103.6), (5, 104.8), (8, 100.8), (6, 102.2), (8, 99.0)], {},
     "range with false breaks (sweeps of range highs/lows), breakout trend, reversal"),
    ("S-M2", "MEDIUM", 52202, 0.15, 0.30,
     [(7, 103), (6, 101.4), (7, 104.6), (6, 102.8), (7, 106.2), (6, 104.4), (6, 106.4), (7, 103.6), (6, 105.0),
      (7, 101.8), (5, 103.2), (6, 100.6), (6, 102.0), (8, 104.4), (8, 100.4)], {"wick_up@61": "sweep_last_high"},
     "double-top style sweep of a swing high, then breakdown; pool swept then taken"),
    ("S-H1", "HARD", 53301, 0.20, 0.34,
     [(7, 102), (6, 100.6), (7, 103.4), (6, 101.8), (6, 103.4), (6, 101.6), (7, 105), (6, 103.2), (6, 105.0),
      (7, 102.6), (6, 104.2), (7, 101.0), (6, 102.6), (6, 100.2), (7, 102.8), (8, 99.6), (7, 101.6)],
     {"outside@40": "outside", "equal@24": "equal_high", "wick_up@70": "sweep_last_high", "wick_dn@84": "sweep_last_low"},
     "choppy structure: equal highs, outside candle, repeat sweeps, several transitions"),
    ("S-H2", "HARD", 53302, 0.22, 0.36,
     [(6, 98.6), (6, 100.4), (6, 99.0), (7, 101.6), (6, 100.0), (7, 102.6), (6, 100.6), (6, 102.8), (7, 99.8),
      (6, 101.4), (6, 99.0), (7, 101.8), (6, 103.4), (6, 101.6), (8, 104.6), (8, 101.0)],
     {"equal@50": "equal_low", "outside@66": "outside", "wick_dn@78": "sweep_last_low"},
     "failed breaks, equal lows, outside candle, reversal and re-reversal"),
    ("S-X1", "EXTREME", 54401, 0.30, 0.50,
     [(5, 102), (4, 100.2), (5, 103), (4, 100.8), (5, 103.8), (4, 101.0), (6, 104.4), (5, 101.4), (5, 104.6),
      (5, 100.6), (5, 103.2), (6, 99.4), (5, 102.4), (5, 98.8), (6, 102.8), (5, 99.6), (6, 103.6), (6, 100.0),
      (5, 102.6), (6, 98.4)],
     {"outside@44": "outside_big", "outside@77": "outside_big", "wick_up@60": "sweep_last_high",
      "wick_dn@92": "sweep_last_low", "equal@30": "equal_high"},
     "volatile whipsaw: multi-pool outside candles, same-candle events, fast transitions"),
    ("S-X2", "EXTREME", 54402, 0.32, 0.55,
     [(5, 97.8), (5, 100.6), (4, 98.8), (6, 102.2), (4, 99.8), (5, 103.0), (5, 100.2), (5, 103.4), (6, 99.0),
      (4, 101.4), (5, 97.6), (5, 100.8), (5, 98.2), (6, 102.6), (5, 99.4), (6, 103.8), (5, 100.6), (6, 104.2),
      (6, 99.8), (5, 102.0)],
     {"outside@36": "outside_big", "outside@70": "outside_big", "wick_dn@54": "sweep_last_low",
      "wick_up@88": "sweep_last_high", "equal@100": "equal_low"},
     "volatile ranges, deep false breaks both sides, multi-pool sweeps"),
]


def r2(x):
    return round(x + 0.0, 2)


def base_path(seed, vol, wv, legs):
    rnd = random.Random(seed)
    rows, c = [], 100.0
    for bars, tgt in legs:
        for j in range(bars):
            o = c + rnd.gauss(0, vol * 0.15)
            step = (tgt - c) / (bars - j)
            c2 = c + step + rnd.gauss(0, vol)
            h = max(o, c2) + abs(rnd.gauss(0, wv))
            l = min(o, c2) - abs(rnd.gauss(0, wv))
            rows.append([r2(o), r2(h), r2(l), r2(c2)])
            c = c2
    return rows


def l2r2_swings(rows, upto):
    """strict L2/R2 swings confirmed at or before `upto` (only used to aim engineered candles)."""
    out = []
    for i in range(2, upto - 1):
        if i + 2 > upto:
            break
        w = [i - 2, i - 1, i + 1, i + 2]
        if all(rows[i][1] > rows[j][1] for j in w):
            out.append(("H", i, rows[i][1]))
        if all(rows[i][2] < rows[j][2] for j in w):
            out.append(("L", i, rows[i][2]))
    return out


def inject(rows, injections, seed):
    rnd = random.Random(seed * 7 + 1)
    for key, kind in sorted(injections.items(), key=lambda kv: int(kv[0].split("@")[1])):
        k = int(key.split("@")[1])
        if k >= len(rows) - 3:
            continue
        o, h, l, c = rows[k]
        prev = rows[k - 1]
        if kind in ("outside", "outside_big"):
            span = 4 if kind == "outside" else 8
            hi = max(r[1] for r in rows[k - span:k]); lo = min(r[2] for r in rows[k - span:k])
            pad = 0.15 + abs(rnd.gauss(0, 0.1))
            o2 = prev[3]
            c2 = r2(o2 + rnd.uniform(-0.15, 0.15))
            rows[k] = [r2(o2), r2(hi + pad), r2(lo - pad), r2(min(max(c2, lo + 0.05), hi - 0.05))]
        elif kind in ("equal_high", "equal_low"):
            # make candle k's extreme exactly equal to candle k-2's and both above / below their neighbours
            if kind == "equal_high":
                lvl = r2(max(rows[k - 2][1], rows[k][1], rows[k - 1][1] + 0.2))
                rows[k - 2][1] = lvl; rows[k][1] = lvl
                rows[k - 1][1] = r2(min(rows[k - 1][1], lvl - 0.25)); rows[k - 1][0] = min(rows[k - 1][0], rows[k - 1][1]); rows[k - 1][3] = min(rows[k - 1][3], rows[k - 1][1])
                for j in (k - 2, k):
                    rows[j][0] = min(rows[j][0], lvl); rows[j][3] = min(rows[j][3], lvl)
            else:
                lvl = r2(min(rows[k - 2][2], rows[k][2], rows[k - 1][2] - 0.2))
                rows[k - 2][2] = lvl; rows[k][2] = lvl
                rows[k - 1][2] = r2(max(rows[k - 1][2], lvl + 0.25)); rows[k - 1][0] = max(rows[k - 1][0], rows[k - 1][2]); rows[k - 1][3] = max(rows[k - 1][3], rows[k - 1][2])
                for j in (k - 2, k):
                    rows[j][0] = max(rows[j][0], lvl); rows[j][3] = max(rows[j][3], lvl)
        elif kind in ("sweep_last_high", "sweep_last_low"):
            sw = [s for s in l2r2_swings(rows, k - 1) if s[0] == ("H" if kind == "sweep_last_high" else "L")]
            if not sw:
                continue
            lvl = sw[-1][2]
            if kind == "sweep_last_high":
                rows[k] = [r2(min(o, lvl - 0.1)), r2(lvl + 0.12 + abs(rnd.gauss(0, 0.08))), r2(min(l, lvl - 0.4)),
                           r2(lvl - 0.08 - abs(rnd.gauss(0, 0.1)))]
            else:
                rows[k] = [r2(max(o, lvl + 0.1)), r2(max(h, lvl + 0.4)), r2(lvl - 0.12 - abs(rnd.gauss(0, 0.08))),
                           r2(lvl + 0.08 + abs(rnd.gauss(0, 0.1)))]
        # keep OHLC consistent
        o, h, l, c = rows[k]
        rows[k] = [o, r2(max(h, o, c)), r2(min(l, o, c)), c]
    for i, (o, h, l, c) in enumerate(rows):
        rows[i] = [o, r2(max(h, o, c)), r2(min(l, o, c)), c]
    return rows


def mirror(rows):
    return [[r2(200 - o), r2(200 - l), r2(200 - h), r2(200 - c)] for o, h, l, c in rows]


def build():
    charts = []
    for sid, tier, seed, vol, wv, legs, inj, desc in SCENARIOS:
        rows = inject(base_path(seed, vol, wv, legs), inj, seed)
        for variant, rr in (("A", rows), ("B", mirror(rows))):
            charts.append(dict(scenario_id=sid, variant=variant, tier=tier, seed=seed, rows=rr, description=desc,
                               mirror_of=None if variant == "A" else "%s-A" % sid, injections=inj, legs=legs,
                               base_vol=vol, wick_vol=wv))
    # neutral public chart ids: shuffled deterministically within each tier so twins are not adjacent
    rnd = random.Random(20261123)
    tiers = {}
    for ch in charts:
        tiers.setdefault(ch["tier"], []).append(ch)
    for tier, lst in tiers.items():
        order = list(range(len(lst)))
        rnd.shuffle(order)
        for pos, i in enumerate(order, 1):
            lst[i]["chart_id"] = "%s-%02d" % ({"EASY": "E", "MEDIUM": "M", "HARD": "H", "EXTREME": "X"}[tier], pos)
    return charts


def main():
    out = sys.argv[1]
    os.makedirs(out + "/ohlc", exist_ok=True)
    meta = []
    for ch in build():
        p = "%s/ohlc/%s.csv" % (out, ch["chart_id"])
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["index", "timestamp", "open", "high", "low", "close"])
            for i, (o, h, l, c) in enumerate(ch["rows"]):
                w.writerow([i, (T0 + i * BAR).strftime("%Y-%m-%dT%H:%M:%SZ"), "%.2f" % o, "%.2f" % h, "%.2f" % l, "%.2f" % c])
        m = {k: v for k, v in ch.items() if k != "rows"}
        m["candles"] = len(ch["rows"])
        meta.append(m)
    json.dump(sorted(meta, key=lambda m: m["chart_id"]), open(out + "/scenarios.json", "w"), indent=1)
    print("generated", len(meta), "charts")


if __name__ == "__main__":
    main()
