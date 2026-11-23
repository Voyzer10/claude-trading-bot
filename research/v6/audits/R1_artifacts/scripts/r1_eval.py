#!/usr/bin/env python3
"""R-1 real-market evaluation of protected-swing availability (V6 BOS + CHoCH). RESEARCH ONLY.

- Uses the repo's StructureStream UNCHANGED (official baseline). The S-1 options run only through the separate,
  clearly labelled counterfactual simulator s1_options.py (in-memory tracker swap; no repo file is modified).
- Reads raw OHLC files read-only; never fabricates or fills candles; writes derived CSV / JSON / PNG only to OUT.

    python3 r1_eval.py --raw <dir with *_5m.json> --out <output dir> [--extended]
"""
import argparse
import csv
import glob
import hashlib
import json
import math
import os
import random
import statistics as stats
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
import os as _os
V6_ROOT = _os.environ.get("V6_ROOT", "/home/claude/v6_wt")
sys.path.insert(0, V6_ROOT)
sys.path.insert(0, HERE)
from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.models import Direction, SwingKind  # noqa: E402
from scanner_v6.structure.choch import CHoCHBreak, State, StructureStream  # noqa: E402
from s1_options import OPTIONS, run as run_option  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
PRIMARY = ["RELIANCE", "HDFCBANK", "INFY", "TCS", "SBIN", "ICICIBANK"]
UNAVAILABLE = [  # requested by the plan, not obtainable in this environment
    ("NSE index", "NIFTY 50 (^NSEI)", "5m/15m/1h/1D", "not in the uploaded cache; Yahoo / NSE unreachable from the workspace (proxy allowlist)"),
    ("NSE index", "NIFTY BANK (^NSEBANK)", "5m/15m/1h/1D", "same"),
    ("Crypto", "BTC-USD, ETH-USD, SOL-USD, XRP-USD (Coinbase)", "5m/15m/1h/4h/1D", "api.exchange.coinbase.com unreachable (HTTP 000 via proxy); no cached crypto candles found; linked VPS not connected"),
    ("US", "SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMZN, JPM (Alpaca IEX)", "5m/15m/1h/1D", "requires broker data key (excluded by the task); Yahoo / Stooq unreachable; no cached US candles found"),
    ("NSE", "1D for every stock", "1D", "only ~60 trading days exist (Yahoo range=60d): evaluated but labelled INSUFFICIENT DATA"),
]
SESSION_OPEN = (9, 15)
SESSION_BARS_5M = 75                      # 09:15 .. 15:25 IST
R = 2                                     # swing right window (approved L2/R2)
MIN_S = 500                               # reliability thresholds (declared before running)
MIN_BOS = 30
MIN_LEGS = 30


# ---------------------------------------------------------------------------------------------------- data + QC
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def load_raw(path):
    d = json.load(open(path))
    meta = d.get("meta") or {}
    rows, qc = [], Counter()
    seen = set()
    prev_t = None
    for i, t in enumerate(d["t"]):
        o, h, l, c = d["o"][i], d["h"][i], d["l"][i], d["c"][i]
        v = d["v"][i] if i < len(d["v"]) else 0
        if any(x is None or (isinstance(x, float) and math.isnan(x)) for x in (o, h, l, c)):
            qc["null_ohlc_dropped"] += 1
            continue
        if t in seen:
            qc["duplicate_ts"] += 1
            continue
        if prev_t is not None and t < prev_t:
            qc["out_of_order"] += 1
        if not (l <= min(o, c) and h >= max(o, c) and l <= h and l > 0):
            qc["ohlc_inconsistent"] += 1
            continue                                   # excluded, never repaired
        seen.add(t)
        prev_t = t
        rows.append((t, float(o), float(h), float(l), float(c), float(v or 0)))
    rows.sort()
    return rows, meta, qc


def ist(t):
    return datetime.fromtimestamp(t, IST)


def session_grid_check(rows):
    """5m bars must sit on the 09:15 + 5k IST grid inside 09:15..15:25."""
    off = 0
    for t, *_ in rows:
        x = ist(t)
        mins = x.hour * 60 + x.minute - (9 * 60 + 15)
        if mins < 0 or mins > 370 or mins % 5 or x.second:
            off += 1
    return off


def resample(rows5, minutes):
    """Session-anchored (09:15 IST) bars from 5m rows. A bar is `complete` only if every expected 5m constituent
    exists. Bars with no constituent are simply absent (never fabricated). 1D = one bar per trading day."""
    groups = defaultdict(list)
    for r in rows5:
        x = ist(r[0])
        day = x.date()
        if minutes == "1D":
            key = (day, 0)
        else:
            mins = x.hour * 60 + x.minute - (9 * 60 + 15)
            key = (day, mins // minutes)
        groups[key].append(r)
    out = []
    for (day, b), rs in sorted(groups.items()):
        rs.sort()
        if minutes == "1D":
            expected = SESSION_BARS_5M
        else:
            start = b * minutes
            end = min(start + minutes, 375)
            expected = (end - start) // 5
        t0 = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST) + timedelta(minutes=0 if minutes == "1D" else b * minutes)
        out.append(dict(t=int(t0.timestamp()), o=rs[0][1], h=max(r[2] for r in rs), l=min(r[3] for r in rs),
                        c=rs[-1][4], v=sum(r[5] for r in rs), n=len(rs), expected=expected,
                        complete=len(rs) == expected, day=day))
    return out


def as_bars(rows5):
    out = []
    for t, o, h, l, c, v in rows5:
        x = ist(t)
        out.append(dict(t=t, o=o, h=h, l=l, c=c, v=v, n=1, expected=1, complete=True, day=x.date()))
    return out


# ---------------------------------------------------------------------------------------------------- per-candle labels
def label_gaps(bars, tf_minutes, trading_days):
    """session_gap: the first candle of each session after a break (intraday only); dq: a missing expected bar inside the
    session between this candle and the one R candles before, or an incomplete resampled candle."""
    n = len(bars)
    first_of_session = [i == 0 or bars[i]["day"] != bars[i - 1]["day"] for i in range(n)]
    intrasession_missing = [False] * n
    if tf_minutes != "1D":
        step = tf_minutes * 60
        for i in range(1, n):
            if bars[i]["day"] == bars[i - 1]["day"] and bars[i]["t"] - bars[i - 1]["t"] > step:
                intrasession_missing[i] = True
    # missing trading days (a day the market traded, absent for this instrument)
    day_idx = {d: k for k, d in enumerate(trading_days)}
    missing_day_before = [False] * n
    for i in range(1, n):
        a, b = day_idx.get(bars[i - 1]["day"]), day_idx.get(bars[i]["day"])
        if a is not None and b is not None and b - a > 1:
            missing_day_before[i] = True
    sg, dq = [False] * n, [False] * n
    for i in range(n):
        if tf_minutes != "1D" and first_of_session[i] and i > 0:
            sg[i] = True                      # the gap-open candle itself (O7 unresolved; see report)
        for j in range(max(0, i - R), i + 1):
            if intrasession_missing[j] or missing_day_before[j]:
                dq[i] = True
        if not bars[i]["complete"]:
            dq[i] = True
    return sg, dq, first_of_session


def atr_series(bars, n=14):
    out, trs = [], []
    for i, b in enumerate(bars):
        pc = bars[i - 1]["c"] if i else b["c"]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
        out.append(sum(trs[-n:]) / n if len(trs) >= n else None)
    return out


def sma(vals, n):
    out, s = [], 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def session_bucket(b, tf):
    if tf == "1D":
        return "n/a"
    x = ist(b["t"])
    m = x.hour * 60 + x.minute
    if m < 10 * 60:
        return "OPEN_0915_1000"
    if m < 14 * 60 + 30:
        return "MID_1000_1430"
    return "CLOSE_1430_1530"


def vol_terciles(atr, bars, warm=100):
    lab, hist = [], []
    for a, b in zip(atr, bars):
        if a is None:
            lab.append("WARMUP")
            continue
        x = a / b["c"]
        if len(hist) < warm:
            lab.append("WARMUP")
        else:
            s = sorted(hist)
            q1, q2 = s[len(s) // 3], s[2 * len(s) // 3]
            lab.append("LOW" if x <= q1 else ("MID" if x <= q2 else "HIGH"))
        hist.append(x)                       # thresholds use strictly earlier candles only
    return lab


def trend_labels(bars, n=50, lag=10):
    m = sma([b["c"] for b in bars], n)
    out = []
    for i in range(len(bars)):
        if i < lag or m[i] is None or m[i - lag] is None:
            out.append("WARMUP")
        else:
            out.append("UP" if m[i] > m[i - lag] else ("DOWN" if m[i] < m[i - lag] else "FLAT"))
    return out


# ---------------------------------------------------------------------------------------------------- evaluation
def evaluate(symbol, tf, bars, trading_days, control=False):
    rows = [(datetime.fromtimestamp(b["t"], timezone.utc), b["o"], b["h"], b["l"], b["c"], b["v"]) for b in bars]
    series = CandleSeries.from_rows(rows, symbol, tf)
    tfm = "1D" if tf == "1D" else int(tf[:-1]) if tf.endswith("m") else int(tf[:-1]) * 60
    sg, dq, first = label_gaps(bars, tfm, trading_days)
    atr = atr_series(bars)
    vol = vol_terciles(atr, bars)
    trd = trend_labels(bars)

    st = StructureStream()
    per = []
    note_status = {}                         # bos_id -> list of (index, code)
    bos_dir = {}
    missed = []
    seen_missed = set()
    run_id = 0
    prev_unprot = False
    for i, c in enumerate(series):
        pre_state = st.state
        known_before = list(st.bos.swings)
        st.on_candle(c)
        for b in st.bos_events:
            bos_dir.setdefault(b.id, (b.direction, b.index))
        for nn in st.tracker.notes:
            note_status.setdefault(nn.bos_id, [])
        note_status = {}
        for nn in st.tracker.notes:
            note_status.setdefault(nn.bos_id, []).append((nn.index, nn.code))
        state = st.state
        tl = st.timeline[-1]
        nh = sum(1 for s in st.bos.swings if s.kind is SwingKind.HIGH)
        nl = sum(1 for s in st.bos.swings if s.kind is SwingKind.LOW)
        # bucket (priority: DQ > SESSION_GAP > INSUFFICIENT_HISTORY > TRANSITION > UNKNOWN > STRUCTURED)
        if dq[i]:
            bucket = "DATA_QUALITY"
        elif sg[i]:
            bucket = "SESSION_GAP"
        elif state is State.UNKNOWN and (nh < 2 or nl < 2):
            bucket = "INSUFFICIENT_HISTORY"
        elif state in (State.TRANSITION_BULLISH, State.TRANSITION_BEARISH):
            bucket = "TRANSITION"
        elif state is State.UNKNOWN:
            bucket = "UNKNOWN_STRUCTURE"
        else:
            bucket = "STRUCTURED"
        structured_any = state in (State.BULLISH, State.BEARISH)
        direction = None
        cause = ""
        prot_price = tl.protected_price
        if structured_any:
            d = Direction.BULLISH if state is State.BULLISH else Direction.BEARISH
            direction = d.value
            if prot_price is None:
                a = st.tracker.active[d]
                if a is not None and a[0] >= st.min_bos_index[d] and a[1].id in st.consumed:
                    cause = "CONSUMED"
                else:
                    cands = [(idx, bid) for bid, (dd, idx) in bos_dir.items() if dd is d and idx >= st.min_bos_index[d] and idx <= i]
                    if not cands:
                        cause = "NO_SAME_DIRECTION_BOS"
                    else:
                        _, bid = max(cands)
                        codes = [code for (k, code) in note_status.get(bid, []) if k <= i]
                        if "ACTIVATED" in codes:
                            cause = "CONSUMED_OR_SUPERSEDED"
                        elif "NOT_QUALIFIED" in codes:
                            cause = "NOT_QUALIFIED_A5"
                        elif "NO_ORIGIN_SWING" in codes:
                            cause = "NO_ORIGIN_SWING"
                        else:
                            cause = "ORIGIN_PENDING"
        unprot = structured_any and prot_price is None
        if unprot and not prev_unprot:
            run_id += 1
        prev_unprot = unprot
        # potential breaks missed while unprotected (diagnostic only, NOT a rule): the close goes beyond the latest
        # confirmed opposite swing known before the candle
        if unprot:
            kind = SwingKind.LOW if state is State.BULLISH else SwingKind.HIGH
            ks = [s for s in known_before if s.kind is kind]
            if ks:
                last = max(ks, key=lambda s: s.confirmed_index)
                hit = c.close < last.price if kind is SwingKind.LOW else c.close > last.price
                if hit and (run_id, last.id) not in seen_missed:
                    seen_missed.add((run_id, last.id))
                    missed.append((i, direction, last.price, bucket))
        dist = None
        if prot_price is not None and atr[i]:
            dist = abs(c.close - prot_price) / atr[i]
        per.append(dict(i=i, bucket=bucket, structured_any=structured_any, direction=direction, unprot=unprot,
                        cause=cause, run=run_id if unprot else 0, dist=dist, session=session_bucket(bars[i], tf),
                        vol=vol[i], trend=trd[i], day=str(bars[i]["day"]), state=state.value))
    # S-1 frequency + counterfactual options (separate simulator; official result untouched)
    opt = {}
    for o in OPTIONS:
        sto, evo = run_option(series, o)
        opt[o] = dict(choch=[(e.index, e.direction.value, e.level) for e in evo if isinstance(e, CHoCHBreak)],
                      prot=[t.protected_price for t in sto.timeline],
                      states=[t.state for t in sto.timeline],
                      s1=sto.tracker.s1_events, notes=sto.tracker.notes)
    # sanity: O1 must equal official
    off_prot = [t.protected_price for t in st.timeline]
    assert opt["O1_CURRENT"]["prot"] == off_prot, (symbol, tf)
    return dict(per=per, missed=missed, bos=st.bos_events, notes=list(st.tracker.notes), opt=opt,
                n=len(series), trading_days=len({b["day"] for b in bars}))


def pct(a, b):
    return 100.0 * a / b if b else float("nan")


def quantiles(xs, qs=(0.25, 0.5, 0.75, 0.9)):
    if not xs:
        return [float("nan")] * len(qs)
    s = sorted(xs)
    return [s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))] for q in qs]


def summarize(sym, tf, res):
    per = res["per"]
    bk = Counter(p["bucket"] for p in per)
    S = [p for p in per if p["bucket"] == "STRUCTURED"]
    S_all = [p for p in per if p["structured_any"]]
    U = [p for p in S if p["unprot"]]
    U_all = [p for p in S_all if p["unprot"]]
    out = dict(instrument=sym, timeframe=tf, candles=res["n"], trading_days=res["trading_days"])
    for b in ("DATA_QUALITY", "SESSION_GAP", "INSUFFICIENT_HISTORY", "TRANSITION", "UNKNOWN_STRUCTURE", "STRUCTURED"):
        out["n_" + b.lower()] = bk.get(b, 0)
    out["S_clean"] = len(S)
    out["unprotected_clean"] = len(U)
    out["unprotected_pct_clean"] = round(pct(len(U), len(S)), 2)
    out["S_all_structured"] = len(S_all)
    out["unprotected_pct_all_structured"] = round(pct(len(U_all), len(S_all)), 2)
    for b in ("SESSION_GAP", "DATA_QUALITY"):
        g = [p for p in per if p["bucket"] == b and p["structured_any"]]
        out["structured_in_" + b.lower()] = len(g)
        out["unprotected_pct_in_" + b.lower()] = round(pct(sum(p["unprot"] for p in g), len(g)), 2)
    for d in ("bullish", "bearish"):
        sd = [p for p in S if p["direction"] == d]
        out["S_" + d] = len(sd)
        out["unprotected_pct_" + d] = round(pct(sum(p["unprot"] for p in sd), len(sd)), 2)
    cz = Counter(p["cause"] for p in U)
    for c in ("NO_ORIGIN_SWING", "NOT_QUALIFIED_A5", "ORIGIN_PENDING", "NO_SAME_DIRECTION_BOS", "CONSUMED", "CONSUMED_OR_SUPERSEDED"):
        out["cause_" + c.lower()] = cz.get(c, 0)
    # runs of consecutive unprotected clean-structured candles (a run is split by any other bucket)
    # runs of consecutive unprotected candles while BULLISH / BEARISH. A run ends only at a protected candle or a
    # state change; session-gap / data-quality candles inside a run are counted (the state carries across them) and
    # the number of session breaks a run spans is recorded.
    runs, spans, cur, sess, prev_day = [], [], 0, 0, None
    for p in per:
        if p["structured_any"] and p["unprot"]:
            if cur and p["day"] != prev_day:
                sess += 1
            cur += 1
        else:
            if cur:
                runs.append(cur)
                spans.append(sess)
            cur, sess = 0, 0
        prev_day = p["day"]
    if cur:
        runs.append(cur)
        spans.append(sess)
    res["_spans"] = spans
    out["runs_spanning_session_break_pct"] = round(pct(sum(1 for x in spans if x), len(spans)), 2)
    res["_runs"] = runs
    res["_dist"] = [p["dist"] for p in per if p["bucket"] == "STRUCTURED" and p["dist"] is not None]
    q = quantiles(runs, (0.5, 0.9))
    out.update(unprot_runs=len(runs), run_len_median=q[0], run_len_p90=q[1], run_len_max=max(runs) if runs else 0)
    nb = len(res["bos"])
    act = [n for n in res["notes"] if n.code == "ACTIVATED"]
    act_bos = {n.bos_id for n in act}
    out.update(bos=nb, activations=len(act), activations_per_1000=round(1000.0 * len(act) / res["n"], 2),
               bos_with_activation_pct=round(pct(len(act_bos), nb), 2),
               bos_not_qualified=len({n.bos_id for n in res["notes"] if n.code == "NOT_QUALIFIED"}),
               bos_no_origin=len({n.bos_id for n in res["notes"] if n.code == "NO_ORIGIN_SWING"}))
    bidx = {b.id: b.index for b in res["bos"]}
    loc = Counter()
    lags = []
    final_origin = {}
    for n_ in res["notes"]:
        if n_.code in ("ACTIVATED", "NOT_QUALIFIED") and n_.swing_id:
            final_origin[n_.bos_id] = (int(n_.swing_id.split(":")[2]), n_.code, n_.index)
    for bid, (oi, code, k) in final_origin.items():
        off = bidx[bid] - oi
        loc["origin_on_bos_candle" if off == 0 else ("origin_on_k_minus_1" if off == 1 else "origin_earlier")] += 1
    for n_ in res["notes"]:
        if n_.code == "ACTIVATED":
            lags.append(n_.index - bidx[n_.bos_id])
    for k_ in ("origin_on_bos_candle", "origin_on_k_minus_1", "origin_earlier"):
        out["legs_" + k_] = loc.get(k_, 0)
    out["activation_lag_median"] = quantiles(lags, (0.5,))[0] if lags else float("nan")
    out["activation_lag_lag0_pct"] = round(pct(sum(1 for x in lags if x == 0), len(lags)), 2)
    d = [p["dist"] for p in S if p["dist"] is not None]
    q = quantiles(d)
    out.update(atr_dist_p25=round(q[0], 3), atr_dist_median=round(q[1], 3), atr_dist_p75=round(q[2], 3), atr_dist_p90=round(q[3], 3))
    out["missed_breaks_while_unprotected"] = sum(1 for m in res["missed"] if m[3] == "STRUCTURED")
    out["missed_breaks_per_1000_S"] = round(1000.0 * out["missed_breaks_while_unprotected"] / len(S), 2) if S else float("nan")
    # S-1 frequency (from the O1 = official simulator run, which records every origin re-selection)
    s1 = res["opt"]["O1_CURRENT"]["s1"]
    legs = {n.bos_id for n in res["notes"] if n.code in ("ACTIVATED", "NOT_QUALIFIED")}
    out["eligible_bos_legs"] = len(legs)
    out["s1_reselections"] = len(s1)
    out["s1_classic_active_kept"] = sum(1 for e in s1 if e[5] and not e[6])
    out["s1_bullish"] = sum(1 for e in s1 if e[2] == "bullish")
    out["s1_bearish"] = sum(1 for e in s1 if e[2] == "bearish")
    out["s1_legs_affected_pct"] = round(pct(len({e[1] for e in s1}), len(legs)), 2)
    base = res["opt"]["O1_CURRENT"]
    for o in OPTIONS[1:]:
        alt = res["opt"][o]
        out["cf_%s_choch" % o] = len(alt["choch"])
        out["cf_%s_choch_diff" % o] = len(set(alt["choch"]) ^ set(base["choch"]))
        out["cf_%s_prot_candles_diff" % o] = sum(1 for a, b in zip(alt["prot"], base["prot"]) if a != b)
    out["choch_official"] = len(base["choch"])
    rel = []
    if len(S) < MIN_S:
        rel.append("S<%d" % MIN_S)
    if nb < MIN_BOS:
        rel.append("BOS<%d" % MIN_BOS)
    out["reliability"] = "OK" if not rel else "INSUFFICIENT DATA (" + ", ".join(rel) + ")"
    out["s1_reliability"] = "OK" if len(legs) >= MIN_LEGS else "INSUFFICIENT DATA (legs<%d)" % MIN_LEGS
    return out


def segment_rows(sym, tf, res):
    rows = []
    S = [p for p in res["per"] if p["bucket"] == "STRUCTURED"]
    for dim in ("session", "vol", "trend", "direction"):
        g = defaultdict(list)
        for p in S:
            g[p[dim]].append(p)
        for k, ps in sorted(g.items(), key=lambda x: str(x[0])):
            rows.append(dict(instrument=sym, timeframe=tf, dimension=dim, segment=k, S=len(ps),
                             unprotected=sum(p["unprot"] for p in ps),
                             unprotected_pct=round(pct(sum(p["unprot"] for p in ps), len(ps)), 2)))
    return rows


def day_block_bootstrap(results, reps=1000, seed=7):
    """Pooled U% CI per timeframe: resample (instrument, day) blocks with replacement."""
    random.seed(seed)
    blocks = []
    for res in results:
        g = defaultdict(lambda: [0, 0])
        for p in res["per"]:
            if p["bucket"] == "STRUCTURED":
                g[p["day"]][0] += 1
                g[p["day"]][1] += p["unprot"]
        blocks += list(g.values())
    if not blocks:
        return (float("nan"),) * 3
    est = pct(sum(b[1] for b in blocks), sum(b[0] for b in blocks))
    vals = []
    for _ in range(reps):
        smp = [blocks[random.randrange(len(blocks))] for _ in blocks]
        vals.append(pct(sum(b[1] for b in smp), sum(b[0] for b in smp)))
    vals.sort()
    return est, vals[int(0.025 * reps)], vals[int(0.975 * reps)]


def synthetic_control(bars, seed, tick=0.05):
    """Gaussian random walk with the real series' in-session close-to-close log-return std and median wick size.
    Same timestamps and session structure; labelled SYNTHETIC CONTROL; never pooled with real data."""
    rets, wick = [], []
    for i in range(1, len(bars)):
        if bars[i]["day"] == bars[i - 1]["day"]:
            rets.append(math.log(bars[i]["c"] / bars[i - 1]["c"]))
    for b in bars:
        wick.append((b["h"] - max(b["o"], b["c"])) / b["c"])
        wick.append((min(b["o"], b["c"]) - b["l"]) / b["c"])
    sd = stats.pstdev(rets)
    mw = stats.median(wick)
    rnd = random.Random(seed)
    p = bars[0]["o"]
    out = []
    for b in bars:
        o = p
        c = round(o * math.exp(rnd.gauss(0, sd)) / tick) * tick
        h = round(max(o, c) * (1 + abs(rnd.gauss(0, mw * 1.25))) / tick) * tick
        l = round(min(o, c) * (1 - abs(rnd.gauss(0, mw * 1.25))) / tick) * tick
        out.append(dict(b, o=o, h=max(h, o, c), l=min(l, o, c), c=c))
        p = c
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--extended", action="store_true", help="also evaluate every other NSE stock in --raw (secondary sample)")
    ap.add_argument("--controls", type=int, default=3)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    files = sorted(glob.glob(os.path.join(a.raw, "*.NS_5m.json")))
    syms_all = [os.path.basename(f).split(".NS_")[0] for f in files]
    syms = PRIMARY + ([s for s in syms_all if s not in PRIMARY] if a.extended else [])
    # trading-day calendar = union of days present in ANY file (a day absent from all files = holiday / weekend)
    raw, manifest, qc_rows = {}, [], []
    for f, s in zip(files, syms_all):
        rows, meta, qc = load_raw(f)
        raw[s] = (rows, meta)
        manifest.append(dict(instrument=s, yahoo_symbol=meta.get("symbol"), exchange=meta.get("fullExchangeName"),
                             currency=meta.get("currency"), exchange_tz=meta.get("exchangeTimezoneName"),
                             file=os.path.basename(f), sha256=sha256(f), bytes=os.path.getsize(f),
                             regular_market_time_utc=datetime.fromtimestamp(meta.get("regularMarketTime", 0), timezone.utc).isoformat()))
        qc_rows.append(dict(instrument=s, **{k: qc.get(k, 0) for k in ("null_ohlc_dropped", "duplicate_ts", "out_of_order", "ohlc_inconsistent")},
                            off_session_grid=session_grid_check(rows),
                            label_matches_file=(meta.get("symbol") == s + ".NS")))
    trading_days = sorted({ist(r[0]).date() for s in raw for r in raw[s][0]})
    summary, segs, results_by_tf, quality, controls = [], [], defaultdict(list), [], []
    s1_legs = []
    run_rows, dist_rows = [], []
    for s in syms:
        rows, meta = raw[s]
        days_present = sorted({ist(r[0]).date() for r in rows})
        per_day = Counter(ist(r[0]).date() for r in rows)
        expected_5m = len(trading_days) * SESSION_BARS_5M
        missing_5m = expected_5m - len(rows)
        # overnight gaps > 10 % (possible corporate action, Yahoo intraday is not split-adjusted)
        big_gaps = []
        for i in range(1, len(rows)):
            if ist(rows[i][0]).date() != ist(rows[i - 1][0]).date():
                g = rows[i][1] / rows[i - 1][4] - 1
                if abs(g) > 0.10:
                    big_gaps.append("%s %.1f%%" % (ist(rows[i][0]).date(), 100 * g))
        for tf in ("5m", "15m", "1h", "1D"):
            if tf == "5m":
                bars = as_bars(rows)
            else:
                bars = resample(rows, {"15m": 15, "1h": 60, "1D": "1D"}[tf])
            exp_bars = {"5m": 75, "15m": 25, "1h": 7, "1D": 1}[tf] * len(trading_days)
            res = evaluate(s, tf, bars, trading_days)
            sm = summarize(s, tf, res)
            sm["sample"] = "PRIMARY" if s in PRIMARY else "EXTENDED"
            summary.append(sm)
            segs += segment_rows(s, tf, res)
            for L, sp in zip(res["_runs"], res["_spans"]):
                run_rows.append(dict(instrument=s, timeframe=tf, sample=sm["sample"], run_len=L, session_breaks_spanned=sp))
            edges = [0, 0.5, 1, 2, 3, 5, 8, 13, 1e9]
            for lo_, hi_ in zip(edges, edges[1:]):
                dist_rows.append(dict(instrument=s, timeframe=tf, sample=sm["sample"], atr_bin_lo=lo_,
                                      atr_bin_hi=("inf" if hi_ > 1e8 else hi_),
                                      candles=sum(1 for x in res["_dist"] if lo_ <= x < hi_)))
            results_by_tf[(tf, sm["sample"])].append(res)
            quality.append(dict(instrument=s, timeframe=tf, sample=sm["sample"], source="Yahoo Finance chart API v8 (via bot research.py cache)",
                                timezone_raw="UTC epoch seconds", timezone_eval="Asia/Kolkata (IST) for sessions",
                                start=str(ist(bars[0]["t"])), end=str(ist(bars[-1]["t"])), candles=len(bars),
                                expected_candles=exp_bars, missing_candles=exp_bars - len(bars),
                                incomplete_resampled=sum(1 for b in bars if not b["complete"]),
                                coverage_pct=round(pct(len(bars), exp_bars), 2),
                                trading_days_calendar=len(trading_days), trading_days_present=len(days_present),
                                days_with_partial_5m=sum(1 for d, n in per_day.items() if n < SESSION_BARS_5M),
                                overnight_gaps_gt10pct=";".join(big_gaps) or "none",
                                adjusted="no (intraday, raw prices)", evaluation_S_clean=sm["S_clean"],
                                reliability=sm["reliability"]))
            for e in res["opt"]["O1_CURRENT"]["s1"]:
                s1_legs.append(dict(instrument=s, timeframe=tf, sample=sm["sample"], k_index=e[0], bos_id=e[1],
                                    direction=e[2], old_origin=e[3], new_origin=e[4], old_was_active=e[5],
                                    new_qualifies_a5=e[6]))
            if s in PRIMARY and tf != "1D":
                for seed in range(a.controls):
                    cb = synthetic_control(bars, seed=1000 + seed)
                    cr = evaluate(s + "_CONTROL", tf, cb, trading_days)
                    cs = summarize(s + "_CONTROL", tf, cr)
                    controls.append(dict(instrument=s, timeframe=tf, seed=1000 + seed, S_clean=cs["S_clean"],
                                         unprotected_pct_clean=cs["unprotected_pct_clean"],
                                         s1_legs_affected_pct=cs["s1_legs_affected_pct"], bos=cs["bos"]))
            print("done", s, tf, sm["S_clean"], sm["unprotected_pct_clean"], flush=True)
    pooled = []
    for (tf, sample), rs in sorted(results_by_tf.items()):
        est, lo, hi = day_block_bootstrap(rs)
        Ssum = sum(1 for r in rs for p in r["per"] if p["bucket"] == "STRUCTURED")
        pooled.append(dict(timeframe=tf, sample=sample, instruments=len(rs), S_clean=Ssum,
                           unprotected_pct=round(est, 2), ci95_lo=round(lo, 2), ci95_hi=round(hi, 2)))

    def wcsv(name, rows):
        if not rows:
            return
        keys = list(rows[0].keys())
        for r in rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with open(os.path.join(a.out, name), "w", newline="") as fh:
            w = csv.DictWriter(fh, keys)
            w.writeheader()
            w.writerows(rows)

    wcsv("r1_summary_by_instrument_timeframe.csv", summary)
    wcsv("r1_segments.csv", segs)
    wcsv("r1_unprotected_runs.csv", run_rows)
    wcsv("r1_atr_distance_hist.csv", dist_rows)
    wcsv("r1_pooled_by_timeframe.csv", pooled)
    wcsv("r1_data_quality.csv", quality)
    wcsv("r1_raw_qc.csv", qc_rows)
    wcsv("r1_s1_reselections.csv", s1_legs)
    wcsv("r1_synthetic_control.csv", controls)
    wcsv("r1_data_manifest.csv", manifest)
    with open(os.path.join(a.out, "r1_unavailable.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["market", "instrument", "timeframes", "reason"])
        w.writerows(UNAVAILABLE)
    json.dump(dict(trading_days=[str(d) for d in trading_days], primary=PRIMARY, evaluated=syms,
                   thresholds=dict(MIN_S=MIN_S, MIN_BOS=MIN_BOS, MIN_LEGS=MIN_LEGS)),
              open(os.path.join(a.out, "r1_run_meta.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
