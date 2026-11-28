"""Third-review regression tests for Phase 1 Final Frozen-Scope Acceptance (P1-1, P1-2, P2-1..P2-5)."""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from ml_data.calendars import (
    USEquityCalendarAdapter,
    USFuturesCalendarAdapter,
    VERIFIED_CALENDAR_SPECS,
    audit_calendar,
)
from ml_data.calendars.audit import _validate_spec_contents
from ml_data.calendars.verified_schedules import VerifiedCalendarSpec
from ml_data.futures.config import CME_TZ
from ml_data.futures.exceptions import FuturesInputError
from ml_data.instruments import AssetClass, Instrument, Market, Segment
from ml_data.storage import (
    CanonicalCandle,
    CanonicalCandleStore,
    DatasetRegistry,
    DatasetVersionConflictError,
    SchemaValidationError,
    resample_candles,
)
from ml_data.us.config import NY_TZ
from ml_data.us.exceptions import USCalendarError

UTC = timezone.utc


def _eq(symbol: str = "AAPL") -> Instrument:
    return Instrument(
        instrument_id="",
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        segment=Segment.US_EQUITY,
        exchange="NASDAQ",
        canonical_symbol=symbol,
        trading_symbol=symbol,
        display_name=symbol,
        price_currency="USD",
        primary_provider="alpaca",
        tick_size=Decimal("0.01"),
    )


def _c(
    inst: Instrument,
    start_utc: datetime,
    close: str = "100",
    *,
    minutes: int = 1,
    timeframe: str = "1m",
    trading_date: date | None = None,
    trading_session: str = "REGULAR",
    dataset_version: str = "v1",
    retrieval_run_id: str = "run-1",
) -> CanonicalCandle:
    end_utc = start_utc + timedelta(minutes=minutes)
    td = trading_date or start_utc.astimezone(UTC).date()
    cd = Decimal(close)
    return CanonicalCandle(
        instrument_id=inst.instrument_id,
        market=inst.market.value,
        asset_class=inst.asset_class.value,
        segment=inst.segment.value,
        exchange=inst.exchange,
        provider=inst.primary_provider,
        provider_symbol=inst.trading_symbol,
        provider_instrument_id=inst.trading_symbol,
        timestamp_start_utc=start_utc,
        timestamp_end_utc=end_utc,
        event_time_utc=end_utc,
        received_at_utc=end_utc,
        timeframe=timeframe,
        trading_date=td,
        trading_session=trading_session,
        session_id=f"{inst.exchange}_{td.isoformat()}_{trading_session}",
        calendar_id="XNYS",
        calendar_version="2026.1",
        open=cd,
        high=cd + Decimal("1"),
        low=cd - Decimal("1"),
        close=cd,
        volume=Decimal("100"),
        provider_feed="iex",
        source_snapshot_id="snap-1",
        source_record_id=f"rec-{start_utc.isoformat()}",
        dataset_version=dataset_version,
        adjustment_mode="RAW",
        retrieval_run_id=retrieval_run_id,
        quality_status="VERIFIED",
    )


# ------------------------------------------------------------------ P1-1: NYSE Eligible Options Early Close
@pytest.mark.parametrize("early_day", [date(2026, 11, 27), date(2027, 11, 26), date(2028, 11, 24)])
def test_p1_1_nyse_eligible_options_early_close_1315_et(early_day: date) -> None:
    eq_cal = USEquityCalendarAdapter(calendar_id="XNYS", options_late_close=False)
    opt_cal = USEquityCalendarAdapter(calendar_id="XNYS", options_late_close=True)

    t_1305 = datetime(early_day.year, early_day.month, early_day.day, 13, 5, tzinfo=NY_TZ)
    t_1314 = datetime(early_day.year, early_day.month, early_day.day, 13, 14, tzinfo=NY_TZ)
    t_1315 = datetime(early_day.year, early_day.month, early_day.day, 13, 15, tzinfo=NY_TZ)

    assert eq_cal.classify_session(t_1305, require_verified=True) == "POST_MARKET"
    assert opt_cal.classify_session(t_1305, require_verified=True) == "REGULAR"
    assert opt_cal.classify_session(t_1314, require_verified=True) == "REGULAR"
    assert opt_cal.classify_session(t_1315, require_verified=True) == "POST_MARKET"

    # Normal day: 16:05 ET -> equity POST_MARKET, eligible options REGULAR, non-eligible options POST_MARKET
    normal = date(early_day.year, 1, 5)
    while normal.weekday() >= 5:
        normal += timedelta(days=1)
    t_1605 = datetime(normal.year, normal.month, normal.day, 16, 5, tzinfo=NY_TZ)
    assert eq_cal.classify_session(t_1605, require_verified=True) == "POST_MARKET"
    assert opt_cal.classify_session(t_1605, require_verified=True) == "REGULAR"


# ------------------------------------------------------------------ P1-2: CME 2027 Known Closures
def test_p1_2_cme_2027_known_closures_and_partial_verification() -> None:
    cme = USFuturesCalendarAdapter()
    assert cme.metadata.verified_years == frozenset({2026})
    assert audit_calendar("us_futures", 2027)["verification_status"] == "PARTIALLY_VERIFIED"

    for closed_day in (date(2027, 1, 1), date(2027, 3, 26), date(2027, 12, 24)):
        assert cme.is_trading_day(closed_day, require_verified=False) is False
        assert cme.is_trading_day(closed_day, require_verified=True) is False
        ts_noon = datetime(closed_day.year, closed_day.month, closed_day.day, 12, 0, tzinfo=CME_TZ)
        assert cme.classify_session(ts_noon, require_verified=True) == "CLOSED"

    # Unverified ordinary 2027 session fails closed when verified required
    with pytest.raises(FuturesInputError):
        cme.is_trading_day(date(2027, 1, 4), require_verified=True)
    with pytest.raises(FuturesInputError):
        cme.classify_session(datetime(2027, 1, 4, 10, 0, tzinfo=CME_TZ), require_verified=True)

    # 2026 regression & maintenance break
    assert cme.is_trading_day(date(2026, 12, 25), require_verified=True) is False
    assert cme.classify_session(datetime(2026, 11, 25, 16, 30, tzinfo=CME_TZ), require_verified=True) == "MAINTENANCE_BREAK"


# ------------------------------------------------------------------ P2-1, P2-2, P2-3: Provenance, Versions, Nasdaq URL
def test_p2_1_2_3_provenance_year_versions_and_nasdaq_url() -> None:
    assert VERIFIED_CALENDAR_SPECS[("us_equity", 2026)].source_published_at == "2024-11-08"
    assert VERIFIED_CALENDAR_SPECS[("us_equity", 2027)].source_published_at == "2024-11-08"
    assert VERIFIED_CALENDAR_SPECS[("us_equity", 2028)].source_published_at == "2025-12-23"

    # Nasdaq has independent URL and does NOT copy NYSE publication date
    nas_2026 = VERIFIED_CALENDAR_SPECS[("nasdaq", 2026)]
    assert nas_2026.source_published_at == ""
    assert nas_2026.verification_status == "PARTIALLY_VERIFIED"
    assert "nasdaq.com" in nas_2026.source_url

    nyse_2028 = USEquityCalendarAdapter(calendar_id="XNYS", effective_year=2028)
    assert nyse_2028.metadata.calendar_version == "2028.1"
    assert nyse_2028.metadata.source_url == VERIFIED_CALENDAR_SPECS[("us_equity", 2028)].source_url
    assert nyse_2028.version_for_year(2027, require_verified=True) == "2027.1"

    nas_adp = USEquityCalendarAdapter(calendar_id="XNAS", effective_year=2027)
    assert nas_adp.metadata.calendar_version == "2027.1"
    assert nas_adp.metadata.source_url == VERIFIED_CALENDAR_SPECS[("nasdaq", 2027)].source_url

    with pytest.raises(USCalendarError):
        USEquityCalendarAdapter(calendar_id="XNAS", effective_year=2028)
    with pytest.raises(USCalendarError):
        nyse_2028.version_for_year(2029, require_verified=True)

    # Audit rejects exchange/source mismatch
    bad_nas = VerifiedCalendarSpec(
        **{**nas_2026.__dict__, "source_url": "https://www.nyse.com/trade/hours-calendars"}
    )
    errs = _validate_spec_contents(bad_nas)
    assert any("exchange/source mismatch" in e for e in errs)


# ------------------------------------------------------------------ P2-4: Full 64-char SHA-256 Partition Hash
def test_p2_4_full_64char_sha256_partition_hash(tmp_path: Path) -> None:
    inst = _eq()
    t0 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    c0 = _c(inst, t0, "100")
    c1 = _c(inst, t0 + timedelta(minutes=1), "101")

    reg = DatasetRegistry(str(tmp_path / "ds.sqlite"))
    store = CanonicalCandleStore(
        canonical_root=str(tmp_path / "candles"),
        manifest_root=str(tmp_path / "manifests"),
        registry=reg,
    )
    m1 = store.write_partitioned([c0, c1], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=2))
    fname = os.path.basename(m1.file_paths[0])
    m = re.match(r"^part-v1-([0-9a-f]{64})\.parquet$", fname)
    assert m is not None, f"Expected 64-char SHA-256 in {fname}"

    # Shuffled identical input -> identical hash
    m1_shuf = store.write_partitioned([c1, c0], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=2))
    assert m1_shuf.file_paths == m1.file_paths

    # Changed content -> different 64-char hash in v2, conflict in v1
    c1_chg = _c(inst, t0 + timedelta(minutes=1), "102")
    with pytest.raises(DatasetVersionConflictError):
        store.write_partitioned([c0, c1_chg], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=2))
    m2 = store.write_partitioned([c0, c1_chg], dataset_id="us_eq", dataset_version="v2", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=2))
    assert os.path.basename(m2.file_paths[0]) != fname


# ------------------------------------------------------------------ P2-5: Extended-Hours Resampling Anchors
def test_p2_5_extended_hours_and_dst_resampling_anchors() -> None:
    inst = _eq()
    us_cal = USEquityCalendarAdapter(calendar_id="XNYS")

    # 1. Premarket on 2026-01-05 (EST): 04:00 ET = 09:00 UTC; missing 04:00 bar, start at 04:01 -> bucket starts 04:00 ET
    d_est = date(2026, 1, 5)
    pre_0401 = datetime(2026, 1, 5, 4, 1, tzinfo=NY_TZ)
    res_pre = resample_candles([_c(inst, pre_0401, trading_date=d_est, trading_session="PRE_MARKET")], "5m", calendar=us_cal)
    assert res_pre[0].timestamp_start_utc == datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    assert "partial_bucket" in res_pre[0].quality_flags

    # 2. Postmarket on normal day (16:00 ET = 21:00 UTC) and early-close day 2026-11-27 (13:00 ET = 18:00 UTC)
    post_1602 = datetime(2026, 1, 5, 16, 2, tzinfo=NY_TZ)
    res_post = resample_candles([_c(inst, post_1602, trading_date=d_est, trading_session="POST_MARKET")], "5m", calendar=us_cal)
    assert res_post[0].timestamp_start_utc == datetime(2026, 1, 5, 21, 0, tzinfo=UTC)

    d_early = date(2026, 11, 27)
    post_early_1302 = datetime(2026, 11, 27, 13, 2, tzinfo=NY_TZ)
    res_early = resample_candles([_c(inst, post_early_1302, trading_date=d_early, trading_session="POST_MARKET")], "5m", calendar=us_cal)
    assert res_early[0].timestamp_start_utc == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)

    # 3. DST transition (2026-03-09 EDT, UTC-4): 09:30 EDT = 13:30 UTC
    d_edt = date(2026, 3, 9)
    reg_0931_edt = datetime(2026, 3, 9, 9, 31, tzinfo=NY_TZ)
    res_edt = resample_candles([_c(inst, reg_0931_edt, trading_date=d_edt, trading_session="REGULAR")], "5m", calendar=us_cal)
    assert res_edt[0].timestamp_start_utc == datetime(2026, 3, 9, 13, 30, tzinfo=UTC)

    # 4. Unknown session type explicitly marked unaligned_anchor
    res_unk = resample_candles([_c(inst, pre_0401, trading_date=d_est, trading_session="AUCTION_UNKNOWN")], "5m", calendar=us_cal)
    assert "unaligned_anchor" in res_unk[0].quality_flags

    # 5. Mixed dataset_version rejected
    b1 = _c(inst, pre_0401, trading_date=d_est, trading_session="PRE_MARKET", dataset_version="v1")
    b2 = _c(inst, pre_0401 + timedelta(minutes=1), trading_date=d_est, trading_session="PRE_MARKET", dataset_version="v2")
    with pytest.raises(SchemaValidationError):
        resample_candles([b1, b2], "5m", calendar=us_cal)


# ------------------------------------------------------------------ Final Patch: XNAS Partial Verification Consistency
@pytest.mark.parametrize("yr", [2026, 2027])
def test_final_patch_xnas_partial_verification_consistency(yr: int) -> None:
    from ml_data.quality import DataQualityEngine

    aud = audit_calendar("nasdaq", yr)
    assert aud["verification_status"] == "PARTIALLY_VERIFIED"

    nas = USEquityCalendarAdapter(calendar_id="XNAS", effective_year=yr)
    assert nas.metadata.verification_status == "PARTIALLY_VERIFIED"
    assert yr not in nas.metadata.verified_years
    assert nas.metadata.verified_years == frozenset()
    assert nas.is_verified_for_range(date(yr, 1, 5), date(yr, 1, 9)) is False

    with pytest.raises(USCalendarError):
        nas.version_for_year(yr, require_verified=True)
    ord_day = date(yr, 1, 5)
    while ord_day.weekday() >= 5:
        ord_day += timedelta(days=1)
    with pytest.raises(USCalendarError):
        nas.is_trading_day(ord_day, require_verified=True)
    ord_ts = datetime(ord_day.year, ord_day.month, ord_day.day, 10, 0, tzinfo=NY_TZ)
    with pytest.raises(USCalendarError):
        nas.classify_session(ord_ts, require_verified=True)

    # Non-strict classification remains deterministic for documented sessions & known closures
    assert nas.is_trading_day(ord_day, require_verified=False) is True
    assert nas.classify_session(ord_ts, require_verified=False) == "REGULAR"
    assert nas.is_trading_day(date(yr, 1, 1), require_verified=False) is False

    # DataQualityEngine must NOT return VERIFIED_WITH_DATA for a Nasdaq candle in a partially verified year
    inst = _eq()
    qe = DataQualityEngine(calendar=nas)
    c_nas = _c(inst, ord_ts, trading_date=ord_day, trading_session="REGULAR")
    rep = qe.evaluate_candles([c_nas], now_utc=datetime(2027, 12, 31, tzinfo=UTC))
    assert rep.status != "VERIFIED_WITH_DATA"
    assert rep.status == "UNVERIFIED_CALENDAR"


@pytest.mark.parametrize("yr", [2026, 2027, 2028])
def test_final_patch_xnys_remains_fully_verified(yr: int) -> None:
    nyse = USEquityCalendarAdapter(calendar_id="XNYS", effective_year=yr)
    assert nyse.metadata.verification_status == "VERIFIED"
    assert nyse.metadata.verified_years == frozenset({2026, 2027, 2028})
    assert nyse.version_for_year(yr, require_verified=True) == f"{yr}.1"
    ord_day = date(yr, 1, 5)
    while ord_day.weekday() >= 5:
        ord_day += timedelta(days=1)
    assert nyse.is_trading_day(ord_day, require_verified=True) is True
    assert nyse.classify_session(datetime(ord_day.year, ord_day.month, ord_day.day, 10, 0, tzinfo=NY_TZ), require_verified=True) == "REGULAR"
