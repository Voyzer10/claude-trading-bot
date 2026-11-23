"""Builds the 20 BLIND liquidity-sweep scenarios (OHLC only, no answers). Research only.
Base for every scenario: CHD01 candles c1-c16 (research/v6/specs/choch_v0_9/choch_fixtures.draft.json).
Mirrors: p -> 200 - p (open/close mirrored, high <-> low)."""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone

BASE = [(104, 105, 102, 103), (103, 104, 101, 102), (102, 103, 100, 101), (101, 102, 98, 99), (99, 103, 99, 102),
        (102, 106, 101, 105), (105, 109, 104, 108), (108, 108, 104, 105), (105, 106, 102, 103), (103, 104, 101, 102),
        (102, 107, 102, 106), (106, 111, 105, 110), (110, 114, 109, 113), (113, 116, 112, 115), (115, 115, 110, 111),
        (111, 112, 106, 107)]
T = {
    "E1": [(107, 117, 106.5, 108), (108, 109, 107, 108.5), (108.5, 110, 107.5, 109.5)],
    "E2": [(107, 108, 100, 104), (104, 106, 103, 105.5), (105.5, 107, 104.5, 106.5)],
    "E4": [(107, 117.5, 106.5, 117), (117, 118, 116, 117.5)],
    "M1": [(107, 108, 100, 104), (104, 105, 100.5, 103.5), (103.5, 106, 103, 105.5), (105.5, 107, 104.5, 106.5)],
    "M2": [(107, 108, 100, 104), (104, 104.5, 99, 99.5)],
    "M3": [(107, 108, 97, 103), (103, 105, 102, 104.5), (104.5, 106, 103.5, 105.5)],
    "H1": [(107, 117, 100.5, 116.5), (116.5, 118, 115, 117.5), (117.5, 119, 116, 118.5)],
    "H3": [(107, 117.5, 106.5, 117), (117, 118, 116, 117.5), (117.5, 118.5, 105.5, 108), (108, 109, 107, 108.5), (108.5, 110, 107.5, 109)],
    "H4": [(107, 108, 102, 104), (104, 106, 103.5, 105.5), (105.5, 107, 104, 106), (106, 106.5, 103, 104), (104, 105.5, 103.5, 105),
           (105, 107, 104.5, 106.5), (106.5, 106.8, 102.5, 105.5)],
    "X1": [(107, 108, 100, 101), (101, 104, 100.5, 103.5), (103.5, 105, 103, 104.5)],
    "X2": [(107, 113, 106.5, 112), (112, 116, 111, 114), (114, 115, 110, 111), (111, 112, 108, 109), (109, 117, 108.5, 115), (115, 116, 110, 112)],
    "X3": [(107, 107.5, 99.5, 100), (100, 104, 99.8, 103.5), (103.5, 105, 103, 104.5)],
    "X4": [(107, 108, 100, 104), (104, 105, 100.5, 103.5), (103.5, 104, 99, 99.5), (99.5, 101, 97.5, 98.5), (98.5, 99, 96, 96.5),
           (96.5, 99, 96.5, 98.5), (98.5, 100, 97, 99.5), (99.5, 99.8, 95, 95.5)],
}
MIRROR_OF = {"E3": "E2", "E5": "E4", "M4": "M3", "M5": "M1", "H2": "H1", "H5": "H3", "X5": "X4"}
LEVEL = {"E": "Easy", "M": "Medium", "H": "Hard", "X": "Extreme"}
COVERS = {
    "E1": "BSL pool, wick beyond vs close back inside, new pools from new swings",
    "E2": "SSL pool at the protected swing, wick beyond vs close back inside",
    "E3": "bearish mirror of E2 (BSL at the protected swing)",
    "E4": "close beyond a BSL level together with a bullish BOS; protected-swing update",
    "E5": "bearish mirror of E4",
    "M1": "repeated wicks at one SSL level on consecutive candles",
    "M2": "wick beyond, then a close beyond on the next candle (lifecycle + CHoCH)",
    "M3": "two SSL levels pierced by one candle (multiple pools on one candle)",
    "M4": "bearish mirror of M3",
    "M5": "bearish mirror of M1",
    "H1": "outside bar: SSL wick + BSL close beyond + BOS on one candle; P-B origin re-selection",
    "H2": "bearish mirror of H1",
    "H3": "liquidity at a freshly activated protected swing; D5 timing of activation",
    "H4": "no-look-ahead: a level pierced BEFORE it becomes a swing; pools only after confirmation",
    "H5": "bearish mirror of H3",
    "X1": "close exactly at the level (CHU04 / LQ-08)",
    "X2": "separated equal highs as two levels (LQ-03), touch at exactly the level, double pierce",
    "X3": "close beyond then close back inside (reclaim, LQ-12 / O4)",
    "X4": "long chain: repeated wicks, close beyond + CHoCH, D4 no-fallback, later wick/close at older levels, reversal BOS",
    "X5": "bearish mirror of X4",
}
T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)


def mirror(rows):
    return [(200 - o, 200 - l, 200 - h, 200 - c) for o, h, l, c in rows]


def main(out):
    scen = []
    for lvl in "EMHX":
        for n in range(1, 6):
            sid = "%s%d" % (lvl, n)
            if sid in MIRROR_OF:
                rows = mirror(BASE + T[MIRROR_OF[sid]])
            else:
                rows = BASE + T[sid]
            for o, h, l, c in rows:
                assert l <= min(o, c) and h >= max(o, c), (sid, o, h, l, c)   # OHLC validity only (no structure peeking)
            scen.append(dict(scenario_id="LSB-" + sid, difficulty=LEVEL[lvl], covers=COVERS[sid],
                             mirror_of=("LSB-" + MIRROR_OF[sid]) if sid in MIRROR_OF else None,
                             timeframe="5m", candle_numbering="1-based (candle 1 = first row)",
                             candles=[dict(candle=i + 1, t=(T0 + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
                                           o=o, h=h, l=l, c=c) for i, (o, h, l, c) in enumerate(rows)]))
    doc = dict(spec="V6 Liquidity Sweep BLIND examination fixtures (OHLC only; no answers)", created="2026-11-22",
               base="CHD01 c1-c16 + scenario tail; mirrors p -> 200 - p", scenarios=scen)
    s = json.dumps(doc, indent=1)
    open(out, "w").write(s)
    print(out, len(scen), "scenarios, sha256", hashlib.sha256(s.encode()).hexdigest())


if __name__ == "__main__":
    main(sys.argv[1])
