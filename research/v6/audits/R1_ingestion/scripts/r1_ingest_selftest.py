"""Self-test of r1_ingest.py validation rules on TINY SYNTHETIC files (TEST ONLY: never reported as market results)."""
import csv, json, os, random, shutil, subprocess, sys, tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__))
ING = os.path.join(HERE, "r1_ingest.py")
results = []

def mk(ddir, meta, files):
    os.makedirs(ddir, exist_ok=True)
    for name, rows in files.items():
        with open(os.path.join(ddir, name), "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["timestamp", "open", "high", "low", "close", "volume"]); w.writerows(rows)
    json.dump(meta, open(os.path.join(ddir, "dataset.json"), "w"), indent=1)

def walk(ts_list, fmt=lambda t: t.isoformat().replace("+00:00", "Z"), seed=1, p=100.0):
    rnd = random.Random(seed); out = []
    for t in ts_list:
        o = p; c = round(o * (1 + rnd.gauss(0, 0.002)), 2); h = round(max(o, c) * (1 + abs(rnd.gauss(0, 0.001))), 2); l = round(min(o, c) * (1 - abs(rnd.gauss(0, 0.001))), 2)  # random wicks (a fixed wick makes every peak an equal-high tie)
        out.append([fmt(t), o, h, l, c, 1]); p = c
    return out

def run(args):
    r = subprocess.run([sys.executable, ING] + args, capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return r.returncode, r.stdout + r.stderr

def check(name, cond, detail=""):
    results.append((name, "PASS" if cond else "FAIL", detail)); print(("PASS " if cond else "FAIL ") + name, detail[:160].replace("\n", " | "))

T = tempfile.mkdtemp(prefix="r1ing_")
utc = timezone.utc
base = dict(dataset_id="TEST", market="TEST ONLY", exchange="TESTX", timeframe="5m", timezone="UTC",
            date_range={"start": "2026-01-05", "end": "2026-01-05"}, data_source="synthetic self-test", adjusted="unadjusted",
            session={"type": "24x7"})
ts = [datetime(2026, 1, 5, tzinfo=utc) + timedelta(minutes=5 * i) for i in range(288)]
good = walk(ts)
# 1 missing required metadata
m = dict(base); del m["adjusted"]; m["files"] = [{"file": "a.csv", "instrument": "X"}]
mk(os.path.join(T, "t1"), m, {"a.csv": good}); rc, out = run(["validate", os.path.join(T, "t1")])
check("missing metadata 'adjusted' -> dataset error", rc == 2 and "required metadata missing: adjusted" in out, out)
# 2 invalid adjusted value
m = dict(base, adjusted="maybe"); m["files"] = [{"file": "a.csv", "instrument": "X"}]
mk(os.path.join(T, "t2"), m, {"a.csv": good}); rc, out = run(["validate", os.path.join(T, "t2")])
check("invalid adjusted value -> dataset error", rc == 2 and "adjusted must be one of" in out, out)
# 3 conflicting duplicate
rows = good + [[good[10][0], 1, 2, 0.5, 1.5, 1]]
m = dict(base); m["files"] = [{"file": "a.csv", "instrument": "X"}]
mk(os.path.join(T, "t3"), m, {"a.csv": rows}); rc, out = run(["validate", os.path.join(T, "t3")])
check("conflicting duplicate timestamp -> file FAIL", rc == 2 and "conflicting duplicate" in out, out)
# 4 identical duplicate -> dropped, OK
rows = good + [list(good[10])]
mk(os.path.join(T, "t4"), m, {"a.csv": rows}); rc, out = run(["validate", os.path.join(T, "t4")])
check("identical duplicate -> dropped, file OK", rc == 0 and "OK" in out, out)
# 5 OHLC inconsistent: 1 row (0.35 %) -> excluded, OK; 5 rows (1.7 %) -> FAIL
r5 = [list(x) for x in good]; r5[20][3] = r5[20][2] + 1          # low above high
mk(os.path.join(T, "t5"), m, {"a.csv": r5}); rc, out = run(["validate", os.path.join(T, "t5")])
check("1 inconsistent OHLC row (<1%) -> excluded, file OK", rc == 0 and "bars=287" in out, out)
for i in (30, 40, 50, 60, 70): r5[i][3] = r5[i][2] + 1
mk(os.path.join(T, "t5b"), m, {"a.csv": r5}); rc, out = run(["validate", os.path.join(T, "t5b")])
check("6 inconsistent OHLC rows (>1%) -> file FAIL", rc == 2 and "excluded rows" in out, out)
# 6 rows outside declared date range
rows = good + walk([datetime(2026, 1, 6, tzinfo=utc)])
mk(os.path.join(T, "t6"), m, {"a.csv": rows}); rc, out = run(["validate", os.path.join(T, "t6")])
check("row outside declared date_range -> file FAIL", rc == 2 and "outside the declared date_range" in out, out)
# 7 off-grid timestamp (5m file with a :07 bar) -> excluded
rows = good + walk([datetime(2026, 1, 5, 12, 7, tzinfo=utc)])
mk(os.path.join(T, "t7"), m, {"a.csv": rows}); rc, out = run(["validate", os.path.join(T, "t7")])
check("off-grid timestamp -> excluded, file OK", rc == 0 and "bars=288" in out, out)
# 8 epoch_ms + bar_close conversion
rows = walk([t + timedelta(minutes=5) for t in ts], fmt=lambda t: str(int(t.timestamp() * 1000)))
m8 = dict(base, timestamp_format="epoch_ms", timestamp_is="bar_close"); m8["files"] = [{"file": "a.csv", "instrument": "X"}]
mk(os.path.join(T, "t8"), m8, {"a.csv": rows}); rc, out = run(["validate", os.path.join(T, "t8")])
check("epoch_ms + bar_close timestamps -> converted to bar open, OK", rc == 0 and "bars=288" in out, out)
# 9 US exchange session across the DST change (Fri 30 Oct and Mon 2 Nov 2026), naive local ISO timestamps
ny = ZoneInfo("America/New_York")
tl = []
for d in (datetime(2026, 10, 30), datetime(2026, 11, 2)):
    for k in range(78):
        tl.append(d.replace(hour=9, minute=30) + timedelta(minutes=5 * k))
rows = walk(tl, fmt=lambda t: t.isoformat())
pre = walk([datetime(2026, 11, 2, 8, 0)], fmt=lambda t: t.isoformat())       # pre-market bar
m9 = dict(base, timezone="America/New_York", date_range={"start": "2026-10-30", "end": "2026-11-02"},
          session={"type": "exchange", "tz": "America/New_York", "open": "09:30", "close": "16:00",
                   "segments": [["OPEN", "09:30", "10:30"], ["MID", "10:30", "15:00"], ["CLOSE", "15:00", "16:00"]]})
m9["files"] = [{"file": "a.csv", "instrument": "X"}]
mk(os.path.join(T, "t9"), m9, {"a.csv": rows + pre}); rc, out = run(["validate", os.path.join(T, "t9")])
check("US session across DST (naive local ISO): 156 bars on grid, pre-market bar excluded", rc == 0 and "bars=156" in out, out)
# 10 24x7 evaluate with a deliberate 1h hole + derived 1h/4h/1D; checks DQ flagged, no SESSION_GAP, WEEKEND segment
ts10 = [datetime(2026, 1, 1, tzinfo=utc) + timedelta(minutes=5 * i) for i in range(288 * 14)]
ts10 = [t for t in ts10 if not (datetime(2026, 1, 7, 10, 0, tzinfo=utc) <= t < datetime(2026, 1, 7, 11, 0, tzinfo=utc))]
m10 = dict(base, dataset_id="TEST_24x7", date_range={"start": "2026-01-01", "end": "2026-01-14"})
m10["files"] = [{"file": "a.csv", "instrument": "X"}]
mk(os.path.join(T, "t10"), m10, {"a.csv": walk(ts10, seed=3)})
rc, out = run(["evaluate", os.path.join(T, "t10"), "--out", os.path.join(T, "res"), "--derive", "1h,4h,1D"])
S = list(csv.DictReader(open(os.path.join(T, "res", "TEST_24x7", "r1_summary_by_instrument_timeframe.csv")))) if rc == 0 else []
Q = list(csv.DictReader(open(os.path.join(T, "res", "TEST_24x7", "r1_data_quality.csv")))) if rc == 0 else []
G = list(csv.DictReader(open(os.path.join(T, "res", "TEST_24x7", "r1_segments.csv")))) if rc == 0 else []
s5 = [r for r in S if r["timeframe"] == "5m"]
q5 = [r for r in Q if r["timeframe"] == "5m"]
check("24x7 evaluate runs; 5m: 12 missing bars reported, not filled", rc == 0 and q5 and q5[0]["missing_candles"] == "12" and q5[0]["candles"] == str(288 * 14 - 12), out[-300:])
check("24x7: no SESSION_GAP candles; DATA_QUALITY > 0 around the hole", s5 and s5[0]["n_session_gap"] == "0" and int(s5[0]["n_data_quality"]) > 0, str(s5[0]["n_data_quality"] if s5 else ""))
qi = {r["timeframe"]: (r["incomplete_derived"], r["missing_candles"]) for r in Q}
check("24x7: the 1h hole -> 1h bar ABSENT (missing 1, incomplete 0); 4h and 1D bars INCOMPLETE (1 each)", rc == 0 and qi.get("1h") == ("0", "1") and qi.get("4h") == ("1", "0") and qi.get("1D") == ("1", "0"), str(qi))
check("24x7: 5m structured candles exist (detector ran on the walk)", s5 and int(s5[0]["S_clean"]) > 0, str(s5[0]["S_clean"] if s5 else ""))
check("24x7: WEEKEND session segment present (3-4 Jan, 10-11 Jan 2026)", any(r["segment"] == "WEEKEND" for r in G))
# 11 results are never overwritten
rc, out = run(["evaluate", os.path.join(T, "t10"), "--out", os.path.join(T, "res")])
check("re-evaluating into an existing dataset_id is refused (no overwrite)", rc == 2 and "never overwritten" in out, out)

# ---- R-1 D2: grid alignment and session membership are counted independently (synthetic, TEST ONLY)
def vrow(res_root, dsid):
    return list(csv.DictReader(open(os.path.join(res_root, dsid, "r1_ingest_validation.csv"))))[0]


def qrows(res_root, dsid):
    return {r["timeframe"]: r for r in csv.DictReader(open(os.path.join(res_root, dsid, "r1_data_quality.csv")))}


def session_days(tzname, days, op, n):
    tz = ZoneInfo(tzname)
    return [datetime(d[0], d[1], d[2], op[0], op[1], tzinfo=tz) + timedelta(minutes=5 * k) for d in days for k in range(n)]


def iso_off(t):
    return t.isoformat()                                    # ISO with the local offset, as the export writes it


US = dict(type="exchange", tz="America/New_York", open="09:30", close="16:00")
IN = dict(type="exchange", tz="Asia/Kolkata", open="09:15", close="15:30")
RES = os.path.join(T, "res_d2d3")
# 12 AAPL-style session-close bar 2026-11-20 16:00 -05:00 (on the 5m grid, outside the session)
tl = session_days("America/New_York", [(2026, 11, 19), (2026, 11, 20)], (9, 30), 78)
close_bar = datetime(2026, 11, 20, 16, 0, tzinfo=ZoneInfo("America/New_York"))
m12 = dict(base, dataset_id="TEST_D2_AAPL_CLOSE", timezone="America/New_York", date_range={"start": "2026-11-19", "end": "2026-11-20"}, session=US)
m12["files"] = [{"file": "a.csv", "instrument": "X"}]
mk(os.path.join(T, "t12"), m12, {"a.csv": walk(tl, fmt=iso_off) + [[iso_off(close_bar), 342.56, 342.56, 342.56, 342.56, 0.0]]})
rc, out = run(["evaluate", os.path.join(T, "t12"), "--out", RES])
v = vrow(RES, "TEST_D2_AAPL_CLOSE") if rc == 0 else {}
check("D2 AAPL 16:00 session-close bar -> excluded_outside_session 1, excluded_off_grid 0, still excluded (156 bars)",
      rc == 0 and v.get("excluded_outside_session") == "1" and v.get("excluded_off_grid") == "0" and v.get("valid_bars") == "156" and v.get("status") == "OK", str({k: v.get(k) for k in ("excluded_outside_session", "excluded_off_grid", "valid_bars", "status")}) + out[-200:])
# 13 NIFTY-style session-close bar 2026-11-20 15:30 +05:30
tl = session_days("Asia/Kolkata", [(2026, 11, 19), (2026, 11, 20)], (9, 15), 75)
close_bar = datetime(2026, 11, 20, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
m13 = dict(base, dataset_id="TEST_D2_NIFTY_CLOSE", timezone="Asia/Kolkata", date_range={"start": "2026-11-19", "end": "2026-11-20"}, session=IN)
m13["files"] = [{"file": "a.csv", "instrument": "X"}]
mk(os.path.join(T, "t13"), m13, {"a.csv": walk(tl, fmt=iso_off) + [[iso_off(close_bar), 25800.6, 25800.6, 25800.6, 25800.6, 0.0]]})
rc, out = run(["evaluate", os.path.join(T, "t13"), "--out", RES])
v = vrow(RES, "TEST_D2_NIFTY_CLOSE") if rc == 0 else {}
check("D2 NIFTY 15:30 session-close bar -> excluded_outside_session 1, excluded_off_grid 0, still excluded (150 bars)",
      rc == 0 and v.get("excluded_outside_session") == "1" and v.get("excluded_off_grid") == "0" and v.get("valid_bars") == "150" and v.get("status") == "OK", str({k: v.get(k) for k in ("excluded_outside_session", "excluded_off_grid", "valid_bars", "status")}) + out[-200:])
q = qrows(RES, "TEST_D2_NIFTY_CLOSE").get("5m", {})
check("D3 exchange sessions unchanged: missing = bars/session x session days - bars; no leading / trailing slots",
      q.get("expected_candles") == "150" and q.get("missing_candles") == "0" and q.get("leading_unobserved_slots") == "" and q.get("trailing_unobserved_slots") == ""
      and q.get("missing_basis") == "session days with data x bars per session", str({k: q.get(k) for k in ("expected_candles", "missing_candles", "leading_unobserved_slots", "trailing_unobserved_slots", "missing_basis")}))
# 14 a genuinely off-grid bar inside the session is still excluded_off_grid (not outside_session)
tl = session_days("America/New_York", [(2026, 11, 19), (2026, 11, 20)], (9, 30), 78)
odd = datetime(2026, 11, 20, 12, 7, tzinfo=ZoneInfo("America/New_York"))
m14 = dict(m12, dataset_id="TEST_D2_OFFGRID")
mk(os.path.join(T, "t14"), m14, {"a.csv": walk(tl, fmt=iso_off) + [[iso_off(odd), 1, 2, 0.5, 1.5, 1]]})
rc, out = run(["evaluate", os.path.join(T, "t14"), "--out", RES])
v = vrow(RES, "TEST_D2_OFFGRID") if rc == 0 else {}
check("D2 off-grid 12:07 bar inside the session -> excluded_off_grid 1, excluded_outside_session 0",
      rc == 0 and v.get("excluded_off_grid") == "1" and v.get("excluded_outside_session") == "0" and v.get("valid_bars") == "156", str({k: v.get(k) for k in ("excluded_off_grid", "excluded_outside_session", "valid_bars")}))
# 15 an on-grid pre-market bar (08:00) -> outside_session, not off_grid
pre = datetime(2026, 11, 20, 8, 0, tzinfo=ZoneInfo("America/New_York"))
m15 = dict(m12, dataset_id="TEST_D2_PREMARKET")
mk(os.path.join(T, "t15"), m15, {"a.csv": walk(tl, fmt=iso_off) + [[iso_off(pre), 1, 2, 0.5, 1.5, 1]]})
rc, out = run(["evaluate", os.path.join(T, "t15"), "--out", RES])
v = vrow(RES, "TEST_D2_PREMARKET") if rc == 0 else {}
check("D2 on-grid 08:00 pre-market bar -> excluded_outside_session 1, excluded_off_grid 0",
      rc == 0 and v.get("excluded_outside_session") == "1" and v.get("excluded_off_grid") == "0" and v.get("valid_bars") == "156", str({k: v.get(k) for k in ("excluded_off_grid", "excluded_outside_session", "valid_bars")}))
# ---- R-1 D3: 24x7 missing only between the first and last observed candle (synthetic, TEST ONLY)
t_first = datetime(2026, 1, 1, 10, 40, tzinfo=utc)                       # partial first UTC day (128 slots before)
n = (datetime(2026, 1, 3, 10, 35, tzinfo=utc) - t_first) // timedelta(minutes=5) + 1   # partial last UTC day (160 after)
ts16 = [t_first + timedelta(minutes=5 * i) for i in range(n)]
m16 = dict(base, dataset_id="TEST_D3_EDGES", date_range={"start": "2026-01-01", "end": "2026-01-03"})
m16["files"] = [{"file": "a.csv", "instrument": "X"}]
mk(os.path.join(T, "t16"), m16, {"a.csv": walk(ts16, seed=5)})
rc, out = run(["evaluate", os.path.join(T, "t16"), "--out", RES, "--derive", "1h"])
q = qrows(RES, "TEST_D3_EDGES") if rc == 0 else {}
q5, q1 = q.get("5m", {}), q.get("1h", {})
check("D3 24x7 partial first/last UTC days: 5m missing 0, leading 128, trailing 160, coverage 100 over the observed range",
      (q5.get("candles"), q5.get("expected_candles"), q5.get("missing_candles"), q5.get("leading_unobserved_slots"), q5.get("trailing_unobserved_slots"), q5.get("coverage_pct"))
      == (str(n), str(n), "0", "128", "160", "100.0"), str({k: q5.get(k) for k in ("candles", "expected_candles", "missing_candles", "leading_unobserved_slots", "trailing_unobserved_slots", "coverage_pct")}))
check("D3 24x7 derived 1h: missing 0, leading 10, trailing 13 (hours outside the observed range not missing)",
      (q1.get("missing_candles"), q1.get("leading_unobserved_slots"), q1.get("trailing_unobserved_slots")) == ("0", "10", "13"),
      str({k: q1.get(k) for k in ("candles", "expected_candles", "missing_candles", "leading_unobserved_slots", "trailing_unobserved_slots")}))
# 17 the same edges plus a GENUINE 1-hour gap inside the observed range
gap0, gap1 = datetime(2026, 1, 2, 5, 0, tzinfo=utc), datetime(2026, 1, 2, 6, 0, tzinfo=utc)
ts17 = [t for t in ts16 if not (gap0 <= t < gap1)]
m17 = dict(m16, dataset_id="TEST_D3_GAP")
mk(os.path.join(T, "t17"), m17, {"a.csv": walk(ts17, seed=5)})
rc, out = run(["evaluate", os.path.join(T, "t17"), "--out", RES, "--derive", "1h"])
q = qrows(RES, "TEST_D3_GAP") if rc == 0 else {}
q5, q1 = q.get("5m", {}), q.get("1h", {})
check("D3 24x7 genuine gap inside the observed range: 5m missing 12, leading 128, trailing 160, coverage %.2f" % round(100.0 * (n - 12) / n, 2),
      (q5.get("missing_candles"), q5.get("leading_unobserved_slots"), q5.get("trailing_unobserved_slots"), q5.get("coverage_pct"))
      == ("12", "128", "160", str(round(100.0 * (n - 12) / n, 2))), str({k: q5.get(k) for k in ("candles", "expected_candles", "missing_candles", "leading_unobserved_slots", "trailing_unobserved_slots", "coverage_pct")}))
check("D3 24x7 genuine gap, derived 1h: the absent hour is missing (1); edges still separate (10 / 13)",
      (q1.get("missing_candles"), q1.get("leading_unobserved_slots"), q1.get("trailing_unobserved_slots")) == ("1", "10", "13"),
      str({k: q1.get(k) for k in ("candles", "expected_candles", "missing_candles", "leading_unobserved_slots", "trailing_unobserved_slots")}))
shutil.rmtree(T)
with open(os.path.join(HERE, "r1_ingest_selftest_results.txt"), "w") as fh:
    for r in results:
        fh.write("%s  %s\n" % (r[1], r[0]))
print("%d / %d PASS" % (sum(r[1] == "PASS" for r in results), len(results)))
