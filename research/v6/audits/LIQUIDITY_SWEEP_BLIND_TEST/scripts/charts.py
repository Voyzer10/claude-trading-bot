"""Chart images: blind (OHLC + candle numbers only) and marked (after scoring). Research only."""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

FX, EXP, BOT, OUT = sys.argv[1:5]
F = {s["scenario_id"]: s for s in json.load(open(FX))["scenarios"]}
E = {s["scenario_id"]: s for s in json.load(open(EXP))["scenarios"]} if EXP != "-" else {}
B = {a["scenario_id"]: a for a in json.load(open(BOT))["answers"]} if BOT != "-" else {}
os.makedirs(os.path.join(OUT, "blind"), exist_ok=True)
os.makedirs(os.path.join(OUT, "marked"), exist_ok=True)
UP, DN = "#2e7d5b", "#b23b3b"


def candles(ax, cs):
    for c in cs:
        x = c["candle"]
        col = UP if c["c"] >= c["o"] else DN
        ax.plot([x, x], [c["l"], c["h"]], color=col, lw=1)
        lo, hi = min(c["o"], c["c"]), max(c["o"], c["c"])
        ax.add_patch(Rectangle((x - 0.32, lo), 0.64, max(hi - lo, 0.06), color=col))
    ax.set_xlim(0.2, len(cs) + 0.8)
    ax.set_xticks(range(1, len(cs) + 1))
    ax.tick_params(axis="x", labelsize=7)
    ax.grid(axis="y", alpha=0.25)
    ax.set_xlabel("candle (1-based)")
    ax.set_ylabel("price")


for sid, s in F.items():
    cs = s["candles"]
    fig, ax = plt.subplots(figsize=(11, 4.6))
    candles(ax, cs)
    ax.set_title("%s (%s) - BLIND: OHLC only" % (sid, s["difficulty"]), fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "blind", "%s_blind.png" % sid), dpi=130)
    plt.close(fig)
    if not E:
        continue
    e, b = E[sid], B[sid]
    fig, ax = plt.subplots(figsize=(12, 5.4))
    candles(ax, cs)
    n = len(cs)
    for p in e["provisional_pools"]:
        col = "#3b6fb2" if p["side"] == "BSL" else "#b2753b"
        end = n + 0.5
        for ev in e["provisional_liquidity_events"]:
            if ev["pool_id"] == p["pool_id"] and ev["state_after"] == "TAKEN":
                end = ev["candle"]
        ax.plot([p["active_from"] - 0.5, end], [p["level"]] * 2, ls="--", lw=0.9, color=col, alpha=0.8)
        ax.text(p["active_from"] - 0.45, p["level"], " %s" % p["pool_id"], fontsize=6, color=col, va="bottom")
    for ev in e["provisional_liquidity_events"]:
        if ev["candle"] is None:
            continue
        c = cs[ev["candle"] - 1]
        ev = dict(ev, level=float(ev["pool_id"].split("@")[1].split("(")[0]))
        y = c["h"] if ev["side"] == "BSL" else c["l"]
        lab = ev["event"].split(" ")[0]
        mk = "v" if ev["side"] == "BSL" else "^"
        ax.plot(ev["candle"], y + (0.6 if ev["side"] == "BSL" else -0.6), marker=mk, color="#6b3bb2", ms=7)
        ax.text(ev["candle"] + 0.15, y + (1.1 if ev["side"] == "BSL" else -1.4), "%s %s" % (lab, ev["level"]), fontsize=6.5, color="#6b3bb2")
    for bo in b["decidable"]["bos"]:
        ax.annotate("BOS %s %s" % ("up" if bo["direction"] == "bullish" else "dn", bo["level"]), (bo["candle"], bo["level"]),
                    fontsize=6.5, color="black", xytext=(-30, 12), textcoords="offset points", arrowprops=dict(arrowstyle="-", lw=0.5))
    for ev in b["decidable"]["structure_events"]:
        if ev["type"] in ("CHOCH", "REVERSAL_CONFIRMED", "ESTABLISHED"):
            ax.axvline(ev["candle"], color="grey", lw=0.6, ls=":")
            ax.text(ev["candle"] + 0.1, ax.get_ylim()[1] - 0.8, "%s -> %s" % (ev["type"], ev["state_after"]), fontsize=6, rotation=90, va="top")
    for w in b["decidable"]["wick_only"]:
        ax.text(w["candle"] - 0.3, cs[w["candle"] - 1]["l"] - 2.2 if w["protected_level"] < cs[w["candle"] - 1]["c"] else cs[w["candle"] - 1]["h"] + 1.6,
                "WICK_ONLY", fontsize=5.5, color="#555")
    for u in e["unresolved"]:
        ax.text(u["candle"] + 0.1, ax.get_ylim()[0] + 0.6, "UNRESOLVED", fontsize=6, color="#c0392b", rotation=90)
    ax.set_title("%s (%s) - MARKED after scoring: pools / sweeps = expected B0 (PROVISIONAL); BOS / CHoCH / WICK_ONLY = V6 bot" % (sid, s["difficulty"]), fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "marked", "%s_marked.png" % sid), dpi=130)
    plt.close(fig)
print("charts written")
