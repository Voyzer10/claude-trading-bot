"""Render clean candlestick PNGs (no labels, no overlays). usage: render.py <build_dir> <charts_out_dir>
Also writes <charts_out_dir>/../geometry.json: the pixel geometry (axes box, x/y data ranges) of every image, so marked
images can be drawn on the same coordinate system. Geometry contains no event information."""
import csv, glob, json, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, FormatStrFormatter

TIER = {"E": "EASY", "M": "MEDIUM", "H": "HARD", "X": "EXTREME"}
W_IN, H_IN, DPI = 18.0, 9.0, 100


def load(p):
    return [(int(r["index"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
            for r in csv.DictReader(open(p))]


def nice_step(span):
    for s in (0.1, 0.2, 0.25, 0.5, 1.0, 2.0):
        if span / s <= 26:
            return s
    return 5.0


def render(rows, out_png, title):
    n = len(rows)
    lo = min(r[3] for r in rows); hi = max(r[2] for r in rows)
    pad = (hi - lo) * 0.06
    fig = plt.figure(figsize=(W_IN, H_IN), dpi=DPI)
    ax = fig.add_axes([0.055, 0.08, 0.93, 0.86])
    for i, o, h, l, c in rows:
        up = c >= o
        col = "#1f8a4c" if up else "#c0392b"
        ax.vlines(i, l, h, color="#333333", linewidth=1.0, zorder=2)
        ax.add_patch(plt.Rectangle((i - 0.32, min(o, c)), 0.64, max(abs(c - o), 0.004), facecolor=col,
                                   edgecolor="#333333", linewidth=0.6, zorder=3))
    ax.set_xlim(-1, n)
    ax.set_ylim(lo - pad, hi + pad)
    ax.xaxis.set_major_locator(MultipleLocator(5))
    ax.xaxis.set_minor_locator(MultipleLocator(1))
    st = nice_step(hi - lo + 2 * pad)
    ax.yaxis.set_major_locator(MultipleLocator(st))
    ax.yaxis.set_minor_locator(MultipleLocator(st / 5))
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.grid(which="major", axis="both", color="#d0d0d0", linewidth=0.7, zorder=0)
    ax.grid(which="minor", axis="x", color="#eeeeee", linewidth=0.5, zorder=0)
    ax.tick_params(axis="x", labelsize=9); ax.tick_params(axis="y", labelsize=9)
    ax.set_xlabel("candle index (zero-based)", fontsize=10)
    ax.set_ylabel("price", fontsize=10)
    ax.set_title(title, fontsize=12, loc="left")
    ax.set_facecolor("white"); fig.patch.set_facecolor("white")
    fig.savefig(out_png, dpi=DPI, metadata={"Software": None})
    # pixel geometry of the axes box (origin top-left), for drawing marks later
    bb = ax.get_window_extent()
    H = H_IN * DPI
    geo = dict(width=int(W_IN * DPI), height=int(H), ax_left=bb.x0, ax_right=bb.x1, ax_top=H - bb.y1,
               ax_bottom=H - bb.y0, xmin=-1, xmax=n, ymin=lo - pad, ymax=hi + pad)
    plt.close(fig)
    return geo


def main():
    build, out = sys.argv[1], sys.argv[2]
    geos = {}
    for p in sorted(glob.glob(build + "/ohlc/*.csv")):
        cid = os.path.basename(p)[:-4]
        d = os.path.join(out, TIER[cid[0]])
        os.makedirs(d, exist_ok=True)
        geos[cid] = render(load(p), os.path.join(d, cid + ".png"), "Chart %s" % cid)
    json.dump(geos, open(os.path.join(build, "geometry.json"), "w"), indent=1, sort_keys=True)
    print("rendered", len(geos))


if __name__ == "__main__":
    main()
