"""Tests for KiteHistoricalDataClient, chunking, rate limiting, retries, OI, and coverage preflight."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ml_data.india import (
    ContractDiscovery,
    InstrumentMasterDownloader,
    KiteAdapterError,
    KiteAuthError,
    KiteClientWrapper,
    KiteHistoricalDataClient,
    KiteRateLimiter,
    NSECalendar,
)
from ml_data.india.config import IST_TZ
from ml_data.india.historical import chunk_date_range
from ml_data.instruments import InstrumentRegistry
from ml_data.tests.india.fixtures import FakeKiteSDK


def _setup_registry(tmp_path, candles_by_token=None, client=None):
    sdk = FakeKiteSDK(candles_by_token=candles_by_token)
    c = client or KiteClientWrapper(kite_client=sdk, sleeper=lambda _: None)
    dl = InstrumentMasterDownloader(client=c, root_dir=str(tmp_path / "master"))
    d0 = date(2026, 11, 27)
    nse = dl.download_snapshot("NSE", snap_date=d0)
    nfo = dl.download_snapshot("NFO", snap_date=d0)
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    rep = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse, nfo_snapshot=nfo, registry=reg)
    return sdk, c, reg, rep


def test_historical_ohlcv_oi_tz_dedup_missing_and_checkpoint(tmp_path):
    # Token 100003 = NIFTY26D0324500CE
    # Include a duplicate, an out-of-range candle, and skip 09:20 IST (missing bar)
    c_rows = [
        ["2026-11-27T09:15:00+0530", 180.0, 185.0, 179.0, 184.0, 1000, 50000],
        ["2026-11-27T09:15:00+0530", 180.0, 185.0, 179.0, 184.0, 1000, 50000],  # duplicate
        ["2026-11-27T09:25:00+0530", 184.0, 186.0, 183.0, 185.5, 1200, 51000],  # 09:20 missing
        ["2026-11-27T16:00:00+0530", 185.5, 186.0, 185.0, 185.5, 10, 51000],    # out of requested range
    ]
    sdk, client, reg, rep = _setup_registry(tmp_path, candles_by_token={(100003, "5minute"): c_rows})
    nifty_ce = next(o for o in rep.options if o.canonical_symbol == "NIFTY26D0324500CE")

    hist = KiteHistoricalDataClient(
        client=client,
        registry=reg,
        calendar=NSECalendar(),
        checkpoint_dir=str(tmp_path / "ckpts"),
    )
    f_dt = datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ)
    t_dt = datetime(2026, 11, 27, 9, 30, tzinfo=IST_TZ)
    res = hist.fetch_historical_candles(nifty_ce.instrument_id, "5minute", f_dt, t_dt, include_oi=True)

    assert len(res.candles) == 2
    assert res.duplicates_dropped == 1
    assert res.out_of_range_dropped == 1
    assert len(res.missing_timestamps) == 1
    assert res.missing_timestamps[0].astimezone(IST_TZ).minute == 20
    assert res.candles[0].ts_utc.tzinfo == timezone.utc
    assert res.candles[0].open == Decimal("180.0")
    assert res.candles[0].oi == 50000

    # Second call resumes from checkpoint without calling SDK historical_data again
    hist_calls_before = sum(1 for c in sdk.calls if c[0] == "historical_data")
    res2 = hist.fetch_historical_candles(nifty_ce.instrument_id, "5minute", f_dt, t_dt, include_oi=True)
    hist_calls_after = sum(1 for c in sdk.calls if c[0] == "historical_data")
    assert hist_calls_after == hist_calls_before
    assert len(res2.candles) == 2
    reg.close()


def test_absent_oi_and_malformed_ohlc_rejection(tmp_path):
    ok_no_oi = [["2026-11-27T09:15:00+0530", 24500.0, 24510.0, 24490.0, 24505.0, 0]]
    bad_ohlc = [["2026-11-27T09:15:00+0530", 100.0, 95.0, 99.0, 100.0, 10]]  # high < open
    sdk, client, reg, rep = _setup_registry(
        tmp_path,
        candles_by_token={(256265, "minute"): ok_no_oi, (100001, "minute"): bad_ohlc},
    )
    hist = KiteHistoricalDataClient(client=client, registry=reg)
    f_dt = datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ)
    t_dt = datetime(2026, 11, 27, 9, 20, tzinfo=IST_TZ)

    r_idx = hist.fetch_historical_candles(rep.indices[0].instrument_id, "minute", f_dt, t_dt, include_oi=False)
    assert r_idx.candles[0].oi is None

    nifty_fut = next(f for f in rep.futures if f.canonical_symbol == "NIFTY26DECFUT")
    with pytest.raises(KiteAdapterError):
        hist.fetch_historical_candles(nifty_fut.instrument_id, "minute", f_dt, t_dt)
    reg.close()


def test_chunking_rate_limiter_429_retry_and_403_no_retry(tmp_path):
    f_dt = datetime(2026, 1, 1, 9, 15, tzinfo=IST_TZ)
    t_dt = datetime(2026, 5, 1, 15, 30, tzinfo=IST_TZ)
    chunks = chunk_date_range(f_dt, t_dt, "minute")
    assert len(chunks) == 3  # 120d 6h15m -> 60d + 60d + 6h15m

    sleeps = []
    t_now = [0.0]

    def fake_clock():
        return t_now[0]

    def fake_sleep(s):
        sleeps.append(s)
        t_now[0] += s

    rl = KiteRateLimiter(historical_rps=2.0, clock=fake_clock, sleeper=fake_sleep)
    rl.acquire("historical")
    rl.acquire("historical")
    assert sleeps and sleeps[0] >= 0.49

    attempts = {"429": 0, "403": 0}

    def flaky_429(*_a):
        attempts["429"] += 1
        if attempts["429"] < 3:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return [["2026-11-27T09:15:00+0530", 100.0, 101.0, 99.0, 100.5, 10, 100]]

    def fail_403(*_a):
        attempts["403"] += 1
        raise RuntimeError("403 TokenException: invalid access_token")

    sdk = FakeKiteSDK(candles_by_token={(100001, "5minute"): flaky_429, (100002, "5minute"): fail_403})
    client = KiteClientWrapper(kite_client=sdk, max_retries=3, base_backoff_s=0.01, sleeper=lambda _: None)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "m2"))
    nse = dl.download_snapshot("NSE", snap_date=date(2026, 11, 27))
    nfo = dl.download_snapshot("NFO", snap_date=date(2026, 11, 27))
    reg = InstrumentRegistry(str(tmp_path / "r2.sqlite3"))
    rep = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse, nfo_snapshot=nfo, registry=reg)
    hist = KiteHistoricalDataClient(client=client, registry=reg)

    nf = next(f for f in rep.futures if f.canonical_symbol == "NIFTY26DECFUT")
    bf = next(f for f in rep.futures if f.canonical_symbol == "BANKNIFTY26DECFUT")
    res = hist.fetch_historical_candles(nf.instrument_id, "5minute", datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ), datetime(2026, 11, 27, 9, 20, tzinfo=IST_TZ))
    assert len(res.candles) == 1
    assert attempts["429"] == 3

    with pytest.raises(KiteAuthError):
        hist.fetch_historical_candles(bf.instrument_id, "5minute", datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ), datetime(2026, 11, 27, 9, 20, tzinfo=IST_TZ))
    assert attempts["403"] == 1  # Never retried 403 TokenException!
    reg.close()


def test_coverage_preflight_report(tmp_path):
    single_row = [["2026-11-27T09:15:00+0530", 100.0, 102.0, 99.0, 101.0, 500, 12000]]
    full_5m_rows = [
        ["2026-11-27T09:15:00+0530", 100.0, 102.0, 99.0, 101.0, 500, 12000],
        ["2026-11-27T09:20:00+0530", 101.0, 103.0, 100.0, 102.0, 600, 12100],
        ["2026-11-27T09:25:00+0530", 102.0, 104.0, 101.0, 103.0, 700, 12200],
    ]
    sdk, client, reg, rep = _setup_registry(
        tmp_path,
        candles_by_token={
            (256265, "5minute"): single_row,
            (100001, "5minute"): full_5m_rows,
        },
    )
    f_dt = datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ)
    t_dt = datetime(2026, 11, 27, 9, 30, tzinfo=IST_TZ)
    sample = [rep.indices[0].instrument_id, rep.futures[0].instrument_id, rep.futures[1].instrument_id, "IN:INDEX:NSE:UNKNOWN"]

    # Unverified calendar must report UNVERIFIED_CALENDAR
    hist_unverified = KiteHistoricalDataClient(client=client, registry=reg, calendar=NSECalendar())
    cov_unv = hist_unverified.coverage_preflight(sample, f_dt, t_dt, intervals=("5minute",))
    assert cov_unv[0]["status"] == "UNVERIFIED_CALENDAR"
    assert cov_unv[3]["status"] == "UNSUPPORTED"

    # Verified calendar: 1 candle in 15m window -> PARTIAL_DATA (not VERIFIED_WITH_DATA),
    # full range -> VERIFIED_WITH_DATA, zero candles -> EMPTY_RESPONSE
    hist_verified = KiteHistoricalDataClient(
        client=client, registry=reg, calendar=NSECalendar(verified_years=frozenset({2026}))
    )
    cov = hist_verified.coverage_preflight(sample[:3], f_dt, t_dt, intervals=("5minute",))
    assert cov[0]["data_returned"] is True
    assert cov[0]["range_covered"] is False
    assert cov[0]["status"] == "PARTIAL_DATA"

    assert cov[1]["data_returned"] is True
    assert cov[1]["range_covered"] is True
    assert cov[1]["oi_available"] is True
    assert cov[1]["status"] == "VERIFIED_WITH_DATA"
    assert cov[1]["intervals"]["5minute"]["candle_count"] == 3
    assert cov[1]["intervals"]["5minute"]["earliest"] is not None

    assert cov[2]["data_returned"] is False
    assert cov[2]["status"] == "EMPTY_RESPONSE"
    reg.close()


def test_checkpoint_isolation_oi_snapshot_corrupt_and_recovery(tmp_path):
    from datetime import timedelta
    from ml_data.india import CalendarError
    from ml_data.instruments import Instrument

    all_rows = [
        ["2026-11-27T09:15:00+0530", 180.0, 185.0, 179.0, 184.0, 1000, 50000],
        ["2026-11-27T09:20:00+0530", 184.0, 186.0, 183.0, 185.0, 1100, 50500],
        ["2026-11-27T09:25:00+0530", 185.0, 187.0, 184.0, 186.0, 1200, 51000],
        ["2026-11-27T09:30:00+0530", 186.0, 188.0, 185.0, 187.0, 1300, 51500],
    ]

    def _ranged(tok, f_ist, t_ist, iv, oi):
        f_dt = datetime.strptime(f_ist, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST_TZ)
        t_dt = datetime.strptime(t_ist, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST_TZ)
        out = []
        for r in all_rows:
            ts = datetime.fromisoformat(r[0])
            if f_dt <= ts <= t_dt:
                out.append(r if oi else r[:6])
        return out

    sdk, client, reg, rep = _setup_registry(tmp_path, candles_by_token={(100003, "5minute"): _ranged})
    nifty_ce = next(o for o in rep.options if o.canonical_symbol == "NIFTY26D0324500CE")
    ckpt_dir = tmp_path / "ckpts"
    hist = KiteHistoricalDataClient(
        client=client,
        registry=reg,
        calendar=NSECalendar(verified_years=frozenset({2026})),
        checkpoint_dir=str(ckpt_dir),
    )

    # 1. Two consecutive disjoint date ranges: second must NOT contain 09:15
    r1 = hist.fetch_historical_candles(
        nifty_ce.instrument_id, "5minute",
        datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ),
        datetime(2026, 11, 27, 9, 20, tzinfo=IST_TZ),
    )
    r2 = hist.fetch_historical_candles(
        nifty_ce.instrument_id, "5minute",
        datetime(2026, 11, 27, 9, 25, tzinfo=IST_TZ),
        datetime(2026, 11, 27, 9, 30, tzinfo=IST_TZ),
    )
    assert [c.ts_ist.minute for c in r1.candles] == [15, 20]
    assert [c.ts_ist.minute for c in r2.candles] == [25, 30]

    # 2. Overlapping range & wider range after narrower range
    r_ov = hist.fetch_historical_candles(
        nifty_ce.instrument_id, "5minute",
        datetime(2026, 11, 27, 9, 20, tzinfo=IST_TZ),
        datetime(2026, 11, 27, 9, 30, tzinfo=IST_TZ),
    )
    assert [c.ts_ist.minute for c in r_ov.candles] == [20, 25, 30]
    r_wide = hist.fetch_historical_candles(
        nifty_ce.instrument_id, "5minute",
        datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ),
        datetime(2026, 11, 27, 9, 30, tzinfo=IST_TZ),
    )
    assert [c.ts_ist.minute for c in r_wide.candles] == [15, 20, 25, 30]

    # 3. include_oi=False followed by include_oi=True must fetch OI
    r_no_oi = hist.fetch_historical_candles(
        nifty_ce.instrument_id, "5minute",
        datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ),
        datetime(2026, 11, 27, 9, 25, tzinfo=IST_TZ),
        include_oi=False,
    )
    assert all(c.oi is None for c in r_no_oi.candles)
    r_with_oi = hist.fetch_historical_candles(
        nifty_ce.instrument_id, "5minute",
        datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ),
        datetime(2026, 11, 27, 9, 25, tzinfo=IST_TZ),
        include_oi=True,
    )
    assert all(c.oi is not None for c in r_with_oi.candles)

    # 4. Corrupt checkpoint recovers cleanly
    for p in ckpt_dir.glob("*.json"):
        p.write_text("{corrupt_json", encoding="utf-8")
    r_rec = hist.fetch_historical_candles(
        nifty_ce.instrument_id, "5minute",
        datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ),
        datetime(2026, 11, 27, 9, 20, tzinfo=IST_TZ),
    )
    assert len(r_rec.candles) == 2

    # 5. Changed snapshot_date invalidates/separates checkpoint
    updated = Instrument.from_dict({
        **nifty_ce.to_dict(),
        "metadata": {**nifty_ce.metadata, "snapshot_date": "2026-11-28"},
    })
    reg.upsert(updated)
    calls_before = sum(1 for c in sdk.calls if c[0] == "historical_data")
    hist.fetch_historical_candles(
        nifty_ce.instrument_id, "5minute",
        datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ),
        datetime(2026, 11, 27, 9, 20, tzinfo=IST_TZ),
    )
    calls_after = sum(1 for c in sdk.calls if c[0] == "historical_data")
    assert calls_after > calls_before

    # 6. NSECalendar holidays, unexpected closures, special sessions, and unverified year guard
    from datetime import time as dt_time
    cal = NSECalendar(
        holidays=frozenset({date(2026, 11, 24)}),
        unexpected_closures=frozenset({date(2026, 11, 25)}),
        special_sessions={date(2026, 11, 26): (dt_time(18, 0), dt_time(19, 0))},
        verified_years=frozenset({2026}),
    )
    assert cal.session_bounds(date(2026, 11, 24), require_verified=True) is None
    assert cal.session_bounds(date(2026, 11, 25), require_verified=True) is None
    sp = cal.session_bounds(date(2026, 11, 26), require_verified=True)
    assert sp is not None and sp[0].hour == 18 and sp[1].hour == 19
    with pytest.raises(CalendarError):
        cal.session_bounds(date(2027, 1, 4), require_verified=True)
    reg.close()


def test_historical_coverage_exact_boundaries_intervals_and_states(tmp_path):
    from ml_data.india.historical import expected_session_timestamps

    # Reproduce 09:20 / 09:25 false-positive on 09:15-09:30 IST request
    missing_first = [
        ["2026-11-27T09:20:00+0530", 100.0, 102.0, 99.0, 101.0, 500, 12000],
        ["2026-11-27T09:25:00+0530", 101.0, 103.0, 100.0, 102.0, 600, 12100],
    ]
    missing_last = [
        ["2026-11-27T09:15:00+0530", 100.0, 102.0, 99.0, 101.0, 500, 12000],
        ["2026-11-27T09:20:00+0530", 101.0, 103.0, 100.0, 102.0, 600, 12100],
    ]
    missing_mid = [
        ["2026-11-27T09:15:00+0530", 100.0, 102.0, 99.0, 101.0, 500, 12000],
        ["2026-11-27T09:25:00+0530", 101.0, 103.0, 100.0, 102.0, 600, 12100],
    ]
    full_win = [
        ["2026-11-27T09:15:00+0530", 100.0, 102.0, 99.0, 101.0, 500, 12000],
        ["2026-11-27T09:20:00+0530", 101.0, 103.0, 100.0, 102.0, 600, 12100],
        ["2026-11-27T09:25:00+0530", 102.0, 104.0, 101.0, 103.0, 700, 12200],
    ]
    sdk, client, reg, rep = _setup_registry(
        tmp_path,
        candles_by_token={
            (256265, "5minute"): missing_first,     # NIFTY 50 index: missing 09:15 -> PARTIAL_DATA
            (260105, "5minute"): missing_last,      # BANKNIFTY index: missing 09:25 -> PARTIAL_DATA
            (100001, "5minute"): missing_mid,       # NIFTY26DECFUT: missing 09:20 -> PARTIAL_DATA
            (100002, "5minute"): full_win,          # BANKNIFTY26DECFUT: full 3 bars -> VERIFIED_WITH_DATA
            (100003, "5minute"): missing_mid,       # NIFTY26D0324500CE option: interior gap -> UNKNOWN
            (100004, "5minute"): [],                # NIFTY26D0324500PE option: empty -> EMPTY_RESPONSE
        },
    )
    cal = NSECalendar(holidays=frozenset({date(2026, 11, 26)}), verified_years=frozenset({2026}))
    hist = KiteHistoricalDataClient(client=client, registry=reg, calendar=cal)

    f_dt = datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ)
    t_dt = datetime(2026, 11, 27, 9, 30, tzinfo=IST_TZ)
    nifty_idx = next(i for i in rep.indices if i.canonical_symbol == "NIFTY")
    bank_idx = next(i for i in rep.indices if i.canonical_symbol == "BANKNIFTY")
    nifty_fut = next(f for f in rep.futures if f.canonical_symbol == "NIFTY26DECFUT")
    bank_fut = next(f for f in rep.futures if f.canonical_symbol == "BANKNIFTY26DECFUT")
    nifty_ce = next(o for o in rep.options if o.canonical_symbol == "NIFTY26D0324500CE")
    nifty_pe = next(o for o in rep.options if o.canonical_symbol == "NIFTY26D0324500PE")

    cov = hist.coverage_preflight(
        [
            nifty_idx.instrument_id,
            bank_idx.instrument_id,
            nifty_fut.instrument_id,
            bank_fut.instrument_id,
            nifty_ce.instrument_id,
            nifty_pe.instrument_id,
        ],
        f_dt,
        t_dt,
        intervals=("5minute",),
    )
    assert cov[0]["status"] == "PARTIAL_DATA" and cov[0]["range_covered"] is False and cov[0]["missing_count"] == 1
    assert cov[1]["status"] == "PARTIAL_DATA" and cov[1]["range_covered"] is False and cov[1]["missing_count"] == 1
    assert cov[2]["status"] == "PARTIAL_DATA" and cov[2]["range_covered"] is False and cov[2]["missing_count"] == 1
    assert cov[3]["status"] == "VERIFIED_WITH_DATA" and cov[3]["range_covered"] is True and cov[3]["missing_count"] == 0
    assert cov[4]["status"] == "UNKNOWN" and cov[4]["range_covered"] is False
    assert cov[5]["status"] == "EMPTY_RESPONSE" and cov[5]["data_returned"] is False

    # All 7 intervals & truncated final buckets on full session
    full_s = datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ)
    full_e = datetime(2026, 11, 27, 15, 30, tzinfo=IST_TZ)
    expected_counts = {"minute": 375, "3minute": 125, "5minute": 75, "10minute": 38, "15minute": 25, "30minute": 13, "60minute": 7}
    for iv, exp_cnt in expected_counts.items():
        ts_list = expected_session_timestamps(cal, iv, full_s, full_e, require_verified=True)
        assert len(ts_list) == exp_cnt, iv

    # Multi-day range skipping holiday (2026-11-26 is holiday, 2026-11-27 is trading day) + partial range
    multi_ts = expected_session_timestamps(
        cal, "5minute",
        datetime(2026, 11, 26, 9, 15, tzinfo=IST_TZ),
        datetime(2026, 11, 27, 9, 30, tzinfo=IST_TZ),
        require_verified=True,
    )
    assert len(multi_ts) == 3  # only 2026-11-27 09:15, 09:20, 09:25

    # Unverified calendar year reports UNVERIFIED_CALENDAR
    hist_unv = KiteHistoricalDataClient(client=client, registry=reg, calendar=NSECalendar())
    cov_unv = hist_unv.coverage_preflight([bank_fut.instrument_id], f_dt, t_dt, intervals=("5minute",))
    assert cov_unv[0]["status"] == "UNVERIFIED_CALENDAR"
    reg.close()
