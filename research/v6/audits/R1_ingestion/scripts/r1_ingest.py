#!/usr/bin/env python3
"""R-1 ingestion + evaluation interface for additional historical OHLC CSV datasets (V6 research only).

  validate  python3 r1_ingest.py validate <dataset_dir>
  evaluate  python3 r1_ingest.py evaluate <dataset_dir> --out <results_root> [--derive 15m,1h,1D] [--controls 0]

A dataset is ONE market / source: a directory holding CSV files plus `dataset.json` (see R1_ingestion/README.md and
dataset.schema.json). Every CSV row is checked; nothing is repaired, filled, interpolated or substituted:
  * rows that fail a check are EXCLUDED and counted;
  * a file FAILS (is not evaluated) on: missing / invalid metadata, conflicting duplicate timestamps, rows outside
    the declared date range, or excluded rows above --max-bad-pct (default 1 %).
Results go to <results_root>/<dataset_id>/ and never overwrite another dataset (the Phase-3 NSE results are not
touched). The V6 detector is the unchanged worktree code (StructureStream); evaluation logic is r1_eval.py from
Phase 3 with its session / gap / segment functions made market-aware through the session model in dataset.json.
"""
import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
V6_ROOT = os.environ.get("V6_ROOT", "/home/claude/v6_wt")
_default_r1 = os.path.normpath(os.path.join(HERE, "..", "..", "R1_artifacts", "scripts"))
R1_SCRIPTS = os.environ.get("R1_SCRIPTS", _default_r1)
sys.path.insert(0, V6_ROOT)
sys.path.insert(0, R1_SCRIPTS)
import r1_eval as R  # noqa: E402

REQUIRED = ["instrument", "exchange", "timeframe", "timezone", "date_range", "data_source", "adjusted"]
ADJUSTED = {"adjusted", "unadjusted", "unknown"}
TF_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1D": 1440}
DEFAULT_24X7_SEGMENTS = [["ASIA", "00:00", "08:00"], ["EUROPE", "08:00", "13:30"], ["US", "13:30", "21:00"], ["LATE", "21:00", "24:00"]]


class DatasetError(Exception):
    pass


# --------------------------------------------------------------------------------------------- metadata
def hhmm(s):
    if s == "24:00":
        return 1440
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def load_dataset(ddir):
    path = os.path.join(ddir, "dataset.json")
    if not os.path.exists(path):
        raise DatasetError("dataset.json missing in %s" % ddir)
    d = json.load(open(path))
    for k in ("dataset_id", "market", "session", "files"):
        if k not in d:
            raise DatasetError("dataset.json: '%s' is required" % k)
    if not d["files"]:
        raise DatasetError("dataset.json: 'files' is empty")
    sess = d["session"]
    if sess.get("type") not in ("24x7", "exchange"):
        raise DatasetError("session.type must be '24x7' or 'exchange'")
    if sess["type"] == "exchange":
        for k in ("tz", "open", "close"):
            if k not in sess:
                raise DatasetError("session.%s is required for an exchange session" % k)
        ZoneInfo(sess["tz"])
    defaults = {k: v for k, v in d.items() if k not in ("dataset_id", "market", "session", "files")}   # dataset-level fields inherited by every file
    files = []
    for f in d["files"]:
        m = dict(defaults, **f)
        missing = [k for k in REQUIRED if m.get(k) in (None, "", [])]
        if missing:
            raise DatasetError("%s: required metadata missing: %s" % (f.get("file"), ", ".join(missing)))
        if m["timeframe"] not in TF_MIN:
            raise DatasetError("%s: timeframe %r not supported (%s)" % (f["file"], m["timeframe"], ", ".join(TF_MIN)))
        if m["adjusted"] not in ADJUSTED:
            raise DatasetError("%s: adjusted must be one of %s" % (f["file"], sorted(ADJUSTED)))
        ZoneInfo(m["timezone"])
        dr = m["date_range"]
        if not isinstance(dr, dict) or "start" not in dr or "end" not in dr:
            raise DatasetError("%s: date_range must be {start, end} (ISO dates)" % f["file"])
        m["_start"], m["_end"] = date.fromisoformat(dr["start"]), date.fromisoformat(dr["end"])
        m.setdefault("timestamp_format", "iso")
        m.setdefault("timestamp_is", "bar_open")
        if m["timestamp_format"] not in ("iso", "epoch_s", "epoch_ms"):
            raise DatasetError("%s: timestamp_format must be iso | epoch_s | epoch_ms" % f["file"])
        if m["timestamp_is"] not in ("bar_open", "bar_close"):
            raise DatasetError("%s: timestamp_is must be bar_open | bar_close" % f["file"])
        m["_path"] = os.path.join(ddir, f["file"])
        if not os.path.exists(m["_path"]):
            raise DatasetError("%s: file not found" % f["file"])
        files.append(m)
    return d, files


# --------------------------------------------------------------------------------------------- session model
class Session:
    def __init__(self, spec):
        self.spec = spec
        self.kind = spec["type"]
        if self.kind == "exchange":
            self.tz = ZoneInfo(spec["tz"])
            self.open, self.close = hhmm(spec["open"]), hhmm(spec["close"])
            self.segments = [(n, hhmm(a), hhmm(b)) for n, a, b in spec.get("segments", [])]
            self.holidays = set(spec.get("holidays", []))
        else:
            self.tz = timezone.utc
            self.open, self.close = 0, 1440
            self.segments = [(n, hhmm(a), hhmm(b)) for n, a, b in spec.get("segments", DEFAULT_24X7_SEGMENTS)]
            self.holidays = set()

    def local(self, t):
        return datetime.fromtimestamp(t, self.tz)

    def day(self, t):
        return self.local(t).date()

    def minute(self, t):
        x = self.local(t)
        return x.hour * 60 + x.minute

    def on_grid(self, t, tfm):
        x = self.local(t)
        m = x.hour * 60 + x.minute
        if x.second:
            return False
        if self.kind == "exchange":
            # grid alignment only (anchored at the session open); session membership is checked separately by
            # in_session(), so an on-grid bar outside the session counts as excluded_outside_session (R-1 D2)
            return (m - self.open) % tfm == 0
        return m % tfm == 0 if tfm < 1440 else m == 0

    def in_session(self, t):
        if self.kind == "24x7":
            return True
        m = self.minute(t)
        return self.open <= m < self.close and self.local(t).weekday() < 5

    def bars_per_day(self, tfm):
        return math.ceil((self.close - self.open) / tfm)

    def bucket(self, t, tf):
        if tf == "1D":
            return "n/a"
        x = self.local(t)
        if self.kind == "24x7" and x.weekday() >= 5:
            return "WEEKEND"
        m = x.hour * 60 + x.minute
        for n, a, b in self.segments:
            if a <= m < b:
                return n
        return "OTHER"


# --------------------------------------------------------------------------------------------- CSV loading + QC
def parse_ts(s, meta, tz):
    s = s.strip()
    if meta["timestamp_format"] == "epoch_s":
        t = float(s)
    elif meta["timestamp_format"] == "epoch_ms":
        t = float(s) / 1000.0
    else:
        x = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if x.tzinfo is None:
            x = x.replace(tzinfo=tz)
        t = x.timestamp()
    t = int(round(t))
    if meta["timestamp_is"] == "bar_close":
        t -= TF_MIN[meta["timeframe"]] * 60
    return t


def load_csv(meta, sess, max_bad_pct):
    tz = ZoneInfo(meta["timezone"])
    tfm = TF_MIN[meta["timeframe"]]
    qc = Counter()
    byts = {}
    with open(meta["_path"], newline="") as fh:
        rd = csv.DictReader(fh)
        cols = [c.strip().lower() for c in (rd.fieldnames or [])]
        need = ["timestamp", "open", "high", "low", "close"]
        if any(c not in cols for c in need):
            raise DatasetError("%s: header must contain %s (got %s)" % (meta["file"], need, cols))
        rd.fieldnames = cols
        prev = None
        for row in rd:
            qc["rows_read"] += 1
            try:
                t = parse_ts(row["timestamp"], meta, tz)
                o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
                v = float(row["volume"]) if row.get("volume") not in (None, "") else 0.0
            except (ValueError, TypeError):
                qc["excluded_parse_error"] += 1
                continue
            if any(math.isnan(x) or math.isinf(x) for x in (o, h, l, c)):
                qc["excluded_nan"] += 1
                continue
            if prev is not None and t < prev:
                qc["out_of_order"] += 1
            prev = t
            d = sess.day(t)
            if d < meta["_start"] or d > meta["_end"]:
                qc["outside_declared_range"] += 1
                continue
            if not (l <= min(o, c) and h >= max(o, c) and l <= h and l > 0):
                qc["excluded_ohlc_inconsistent"] += 1
                continue
            if not sess.on_grid(t, tfm):
                qc["excluded_off_grid"] += 1
                continue
            if not sess.in_session(t):
                qc["excluded_outside_session"] += 1
                continue
            if t in byts:
                if byts[t] == (o, h, l, c, v):
                    qc["duplicate_identical_dropped"] += 1
                    continue
                qc["duplicate_conflicting"] += 1
                continue
            byts[t] = (o, h, l, c, v)
    rows = [(t,) + byts[t] for t in sorted(byts)]
    bad = sum(qc[k] for k in qc if k.startswith("excluded_"))
    status, reasons = "OK", []
    if qc["duplicate_conflicting"]:
        reasons.append("conflicting duplicate timestamps (%d)" % qc["duplicate_conflicting"])
    if qc["outside_declared_range"]:
        reasons.append("rows outside the declared date_range (%d)" % qc["outside_declared_range"])
    if qc["rows_read"] and 100.0 * bad / qc["rows_read"] > max_bad_pct:
        reasons.append("excluded rows %.2f %% > %.2f %%" % (100.0 * bad / qc["rows_read"], max_bad_pct))
    if not rows:
        reasons.append("no valid rows")
    if reasons:
        status = "FAIL: " + "; ".join(reasons)
    return rows, qc, status


# --------------------------------------------------------------------------------------------- bars, calendar, gaps
def calendar(sess, files_rows, start, end):
    if sess.kind == "24x7":
        n = (end - start).days
        return [start + timedelta(days=i) for i in range(n + 1)]
    days = set()
    for rows in files_rows:
        days |= {sess.day(r[0]) for r in rows}
    return sorted(d for d in days if d.isoformat() not in sess.holidays)


def native_bars(rows, sess):
    return [dict(t=t, o=o, h=h, l=l, c=c, v=v, n=1, expected=1, complete=True, day=sess.day(t)) for t, o, h, l, c, v in rows]


def derive(rows, sess, native_tfm, target):
    tt = TF_MIN[target]
    if tt % native_tfm or tt <= native_tfm:
        raise DatasetError("cannot derive %s from %dm" % (target, native_tfm))
    groups = defaultdict(list)
    for r in rows:
        d = sess.day(r[0])
        m = sess.minute(r[0]) - sess.open
        key = (d, 0) if target == "1D" else (d, m // tt)
        groups[key].append(r)
    out = []
    for (d, b), rs in sorted(groups.items()):
        rs.sort()
        if target == "1D":
            start, end = 0, sess.close - sess.open
        else:
            start, end = b * tt, min(b * tt + tt, sess.close - sess.open)
        expected = (end - start) // native_tfm
        t0 = datetime.combine(d, time(0, 0), tzinfo=sess.tz) + timedelta(minutes=sess.open + start)
        out.append(dict(t=int(t0.timestamp()), o=rs[0][1], h=max(r[2] for r in rs), l=min(r[3] for r in rs), c=rs[-1][4],
                        v=sum(r[5] for r in rs), n=len(rs), expected=expected, complete=len(rs) == expected, day=d))
    return out


def make_label_gaps(sess):
    def label_gaps(bars, tf_minutes, trading_days):
        n = len(bars)
        first = [i == 0 or bars[i]["day"] != bars[i - 1]["day"] for i in range(n)]
        intrasession = [False] * n
        if tf_minutes != "1D":
            step = tf_minutes * 60
            for i in range(1, n):
                same = bars[i]["day"] == bars[i - 1]["day"] or sess.kind == "24x7"
                if same and bars[i]["t"] - bars[i - 1]["t"] > step:
                    intrasession[i] = True
        idx = {d: k for k, d in enumerate(trading_days)}
        missing_day = [False] * n
        for i in range(1, n):
            a, b = idx.get(bars[i - 1]["day"]), idx.get(bars[i]["day"])
            if a is not None and b is not None and b - a > 1:
                missing_day[i] = True
        sg, dq = [False] * n, [False] * n
        for i in range(n):
            if sess.kind == "exchange" and tf_minutes != "1D" and first[i] and i > 0:
                sg[i] = True
            for j in range(max(0, i - R.R), i + 1):
                if intrasession[j] or missing_day[j]:
                    dq[i] = True
            if not bars[i]["complete"]:
                dq[i] = True
        return sg, dq, first
    return label_gaps


# --------------------------------------------------------------------------------------------- commands
def cmd_validate(ddir, max_bad_pct, quiet=False):
    d, files = load_dataset(ddir)
    sess = Session(d["session"])
    report = []
    for m in files:
        rows, qc, status = load_csv(m, sess, max_bad_pct)
        tfm = TF_MIN[m["timeframe"]]
        report.append(dict(dataset_id=d["dataset_id"], market=d["market"], file=m["file"], instrument=m["instrument"],
                           exchange=m["exchange"], timeframe=m["timeframe"], timezone=m["timezone"],
                           declared_start=m["date_range"]["start"], declared_end=m["date_range"]["end"],
                           first_bar_utc=datetime.fromtimestamp(rows[0][0], timezone.utc).isoformat() if rows else "",
                           last_bar_utc=datetime.fromtimestamp(rows[-1][0], timezone.utc).isoformat() if rows else "",
                           data_source=m["data_source"], adjusted=m["adjusted"], retrieval_date=m.get("retrieval_date", ""),
                           valid_bars=len(rows), status=status, sha256=R.sha256(m["_path"]),
                           **{k: qc.get(k, 0) for k in ("rows_read", "excluded_parse_error", "excluded_nan", "excluded_ohlc_inconsistent",
                                                        "excluded_off_grid", "excluded_outside_session", "outside_declared_range",
                                                        "duplicate_identical_dropped", "duplicate_conflicting", "out_of_order")}))
        m["_rows"], m["_status"], m["_tfm"] = rows, status, tfm
    if not quiet:
        for r in report:
            print("%-28s %-5s %-8s bars=%-7d %s" % (r["instrument"], r["timeframe"], r["adjusted"], r["valid_bars"], r["status"]))
    return d, files, sess, report


def write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        w.writerows(rows)


def cmd_evaluate(ddir, out_root, derive_tfs, controls, max_bad_pct, primary):
    d, files, sess, report = cmd_validate(ddir, max_bad_pct)
    out = os.path.join(out_root, d["dataset_id"])
    if os.path.exists(os.path.join(out, "r1_summary_by_instrument_timeframe.csv")):
        raise DatasetError("%s already holds results; use a new dataset_id or a new --out (results are never overwritten)" % out)
    os.makedirs(out, exist_ok=True)
    # market-aware hooks into the Phase-3 evaluation (in memory only)
    R.label_gaps = make_label_gaps(sess)
    R.session_bucket = lambda b, tf: sess.bucket(b["t"], tf)
    ok_files = [m for m in files if m["_status"] == "OK"]
    starts = [m["_start"] for m in ok_files] or [date.today()]
    ends = [m["_end"] for m in ok_files] or [date.today()]
    cal = calendar(sess, [m["_rows"] for m in ok_files], min(starts), max(ends))
    summary, segs, quality, s1_rows, run_rows, pooled_in = [], [], [], [], [], defaultdict(list)
    for m in ok_files:
        tfs = [m["timeframe"]] + [t for t in derive_tfs if t != m["timeframe"]]
        for tf in tfs:
            bars = native_bars(m["_rows"], sess) if tf == m["timeframe"] else derive(m["_rows"], sess, m["_tfm"], tf)
            tfm = TF_MIN[tf]
            fcal = [x for x in cal if m["_start"] <= x <= m["_end"]]
            per_day = 1 if tf == "1D" else (sess.bars_per_day(tfm) if sess.kind == "exchange" else 1440 // tfm)
            exp = per_day * len(fcal)
            lead = trail = ""
            basis = "session days with data x bars per session"
            if sess.kind == "24x7":
                # R-1 D3: missing only between the first and last observed candle (inclusive); slots of the
                # calendar days before the first / after the last candle are reported separately, never as missing
                basis = "first to last observed candle (24x7)"
                step = tfm * 60
                if bars:
                    exp = (bars[-1]["t"] - bars[0]["t"]) // step + 1
                    day0 = int(datetime.combine(fcal[0] if fcal else bars[0]["day"], time(0, 0), tzinfo=sess.tz).timestamp())
                    dayN = int((datetime.combine(fcal[-1] if fcal else bars[-1]["day"], time(0, 0), tzinfo=sess.tz) + timedelta(days=1)).timestamp())
                    lead = max((bars[0]["t"] - day0) // step, 0)
                    trail = max((dayN - bars[-1]["t"] - step) // step, 0)
                else:
                    exp, lead, trail = 0, 0, 0
            res = R.evaluate(m["instrument"], tf, bars, fcal)
            sm = R.summarize(m["instrument"], tf, res)
            sample = "PRIMARY" if (not primary or m["instrument"] in primary) else "EXTENDED"
            sm.update(dataset_id=d["dataset_id"], market=d["market"], exchange=m["exchange"], sample=sample,
                      derived_from=("" if tf == m["timeframe"] else m["timeframe"]))
            summary.append(sm)
            segs += [dict(r, dataset_id=d["dataset_id"]) for r in R.segment_rows(m["instrument"], tf, res)]
            for L in res.get("_runs", []):
                run_rows.append(dict(dataset_id=d["dataset_id"], instrument=m["instrument"], timeframe=tf, run_len=L))
            for e in res["opt"]["O1_CURRENT"]["s1"]:
                s1_rows.append(dict(dataset_id=d["dataset_id"], instrument=m["instrument"], timeframe=tf, k_index=e[0], bos_id=e[1],
                                    direction=e[2], old_origin=e[3], new_origin=e[4], old_was_active=e[5], new_qualifies_a5=e[6]))
            pooled_in[(tf, sample)].append(res)
            quality.append(dict(dataset_id=d["dataset_id"], instrument=m["instrument"], exchange=m["exchange"], timeframe=tf,
                                derived_from=("" if tf == m["timeframe"] else m["timeframe"]), source=m["data_source"],
                                timezone_input=m["timezone"], session_model=json.dumps(d["session"]),
                                start=str(sess.local(bars[0]["t"])) if bars else "", end=str(sess.local(bars[-1]["t"])) if bars else "",
                                candles=len(bars), expected_candles=exp, missing_candles=max(exp - len(bars), 0),
                                incomplete_derived=sum(1 for b in bars if not b["complete"]),
                                coverage_pct=round(100.0 * len(bars) / exp, 2) if exp else "",
                                calendar_days=len(fcal), adjusted=m["adjusted"], retrieval_date=m.get("retrieval_date", ""),
                                evaluation_S_clean=sm["S_clean"], reliability=sm["reliability"],
                                missing_basis=basis, leading_unobserved_slots=lead, trailing_unobserved_slots=trail))
            print("evaluated", m["instrument"], tf, "S=%s U%%=%s" % (sm["S_clean"], sm["unprotected_pct_clean"]), flush=True)
    pooled = []
    for (tf, sample), rs in sorted(pooled_in.items()):
        est, lo, hi = R.day_block_bootstrap(rs)
        pooled.append(dict(dataset_id=d["dataset_id"], timeframe=tf, sample=sample, series=len(rs),
                           S_clean=sum(1 for r in rs for p in r["per"] if p["bucket"] == "STRUCTURED"),
                           unprotected_pct=round(est, 2), ci95_lo=round(lo, 2), ci95_hi=round(hi, 2)))
    write_csv(os.path.join(out, "r1_ingest_validation.csv"), report)
    write_csv(os.path.join(out, "r1_summary_by_instrument_timeframe.csv"), summary)
    write_csv(os.path.join(out, "r1_segments.csv"), segs)
    write_csv(os.path.join(out, "r1_data_quality.csv"), quality)
    write_csv(os.path.join(out, "r1_s1_reselections.csv"), s1_rows)
    write_csv(os.path.join(out, "r1_unprotected_runs.csv"), run_rows)
    write_csv(os.path.join(out, "r1_pooled_by_timeframe.csv"), pooled)
    json.dump(dict(dataset=d, calendar_days=[str(x) for x in cal], evaluated=[m["file"] for m in ok_files],
                   failed=[(m["file"], m["_status"]) for m in files if m["_status"] != "OK"],
                   thresholds=dict(MIN_S=R.MIN_S, MIN_BOS=R.MIN_BOS, MIN_LEGS=R.MIN_LEGS),
                   detector_root=V6_ROOT, evaluated_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds")),
              open(os.path.join(out, "r1_run_meta.json"), "w"), indent=1, default=str)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("dataset_dir")
    v.add_argument("--max-bad-pct", type=float, default=1.0)
    e = sub.add_parser("evaluate")
    e.add_argument("dataset_dir")
    e.add_argument("--out", required=True)
    e.add_argument("--derive", default="", help="comma list of higher timeframes derived from the native one, e.g. 15m,1h,1D")
    e.add_argument("--controls", type=int, default=0, help="reserved (synthetic controls are not generated here)")
    e.add_argument("--max-bad-pct", type=float, default=1.0)
    e.add_argument("--primary", default="", help="comma list of instruments labelled PRIMARY (others EXTENDED)")
    a = ap.parse_args()
    try:
        if a.cmd == "validate":
            _, _, _, rep = cmd_validate(a.dataset_dir, a.max_bad_pct)
            sys.exit(0 if all(r["status"] == "OK" for r in rep) else 2)
        out = cmd_evaluate(a.dataset_dir, a.out, [x for x in a.derive.split(",") if x], a.controls, a.max_bad_pct,
                           [x for x in a.primary.split(",") if x])
        print("results:", out)
    except DatasetError as ex:
        print("DATASET ERROR:", ex, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
