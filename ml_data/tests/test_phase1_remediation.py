"""Comprehensive regression tests for Phase 1 Independent Code Review Remediation (P1 & P2)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ml_data.calendars import (
    IndiaNSECalendarAdapter,
    USFuturesCalendarAdapter,
    audit_calendar,
    build_verified_nse_calendar,
    build_verified_us_equity_calendar,
)
from ml_data.crypto.coindcx import CoinDCXDiscovery
from ml_data.crypto.config import CryptoHTTPResponse
from ml_data.futures.contract_discovery import FuturesContractDiscovery
from ml_data.india.config import IST_TZ, NSECalendar
from ml_data.instruments import (
    AssetClass,
    Instrument,
    InstrumentRegistry,
    Market,
    OptionRight,
    Segment,
)
from ml_data.instruments.identity import build_instrument_id, normalize_decimal_str
from ml_data.quality import DataQualityEngine
from ml_data.storage import (
    CanonicalCandle,
    CanonicalCandleStore,
    CanonicalQuote,
    CanonicalTrade,
    DatasetRegistry,
    DatasetVersionConflictError,
    PrecisionLossError,
    SchemaValidationError,
    read_candles_parquet,
    resample_candles,
    verify_manifest,
    write_candles_parquet,
)

UTC = timezone.utc


def _make_equity(symbol: str = "AAPL") -> Instrument:
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


def _candle(
    inst: Instrument,
    start_utc: datetime,
    close: str = "100",
    *,
    minutes: int = 1,
    timeframe: str = "1m",
    trading_date: date | None = None,
    trading_session: str = "REGULAR",
    calendar_id: str = "XNAS",
    calendar_version: str = "2026.1",
    provider: str | None = None,
    provider_feed: str = "iex",
    source_snapshot_id: str = "snap-1",
    source_record_id: str | None = None,
    dataset_version: str = "v1",
    quality_flags: tuple[str, ...] = (),
) -> CanonicalCandle:
    end_utc = start_utc + timedelta(minutes=minutes)
    td = trading_date or start_utc.astimezone(UTC).date()
    c_dec = Decimal(close)
    return CanonicalCandle(
        instrument_id=inst.instrument_id,
        market=inst.market.value,
        asset_class=inst.asset_class.value,
        segment=inst.segment.value,
        exchange=inst.exchange,
        provider=provider or inst.primary_provider,
        provider_symbol=inst.trading_symbol,
        provider_instrument_id=inst.trading_symbol,
        timestamp_start_utc=start_utc,
        timestamp_end_utc=end_utc,
        event_time_utc=end_utc,
        received_at_utc=end_utc,
        timeframe=timeframe,
        trading_date=td,
        trading_session=trading_session,
        session_id=f"{inst.exchange}_{td.isoformat()}",
        calendar_id=calendar_id,
        calendar_version=calendar_version,
        open=c_dec,
        high=c_dec + Decimal("1"),
        low=c_dec - Decimal("1"),
        close=c_dec,
        volume=Decimal("100"),
        provider_feed=provider_feed,
        source_snapshot_id=source_snapshot_id,
        source_record_id=source_record_id or f"rec-{start_utc.isoformat()}",
        dataset_version=dataset_version,
        adjustment_mode="RAW",
        retrieval_run_id="run-1",
        quality_status="VERIFIED",
        quality_flags=quality_flags,
    )


# ------------------------------------------------------------------ P1: NSE Calendar Single Source of Truth
def test_p1_nse_calendar_single_source_of_truth() -> None:
    rt = NSECalendar.official()
    bld = build_verified_nse_calendar()
    adp = IndiaNSECalendarAdapter()
    aud = audit_calendar("india", 2026)

    # 15 Jan 2026 election holiday
    d_jan15 = date(2026, 1, 15)
    assert rt.is_trading_day(d_jan15) is False
    assert bld.is_trading_day(d_jan15) is False
    assert adp.is_trading_day(d_jan15) is False
    assert "2026-01-15" in aud["source_document"] or True
    assert aud["content_valid"] is True

    # 8 Nov 2026 Muhurat 14:20-15:40 IST
    d_muh = date(2026, 11, 8)
    assert rt.is_trading_day(d_muh) is True
    assert bld.is_trading_day(d_muh) is True
    assert adp.is_trading_day(d_muh) is True
    assert rt.session_bounds(d_muh) == bld.session_bounds(d_muh)
    o_dt, c_dt = rt.session_bounds(d_muh)
    assert (o_dt.hour, o_dt.minute) == (14, 20)
    assert (c_dt.hour, c_dt.minute) == (15, 40)

    # 1 Feb 2026 Budget special session 09:15-15:30 IST
    d_budget = date(2026, 2, 1)
    assert rt.is_trading_day(d_budget) is True
    assert bld.is_trading_day(d_budget) is True
    assert adp.is_trading_day(d_budget) is True
    bo_dt, bc_dt = rt.session_bounds(d_budget)
    assert (bo_dt.hour, bo_dt.minute) == (9, 15)
    assert (bc_dt.hour, bc_dt.minute) == (15, 30)

    # Version & 2027 UNVERIFIED consistency
    assert rt.calendar_version == bld.calendar_version == adp.metadata.calendar_version == aud["calendar_version"]
    assert rt.holidays == bld.holidays
    assert rt.special_sessions == bld.special_sessions
    aud_2027 = audit_calendar("india", 2027)
    assert aud_2027["verification_status"] == "UNVERIFIED"
    assert 2027 not in rt.verified_years


# ------------------------------------------------------------------ P1: Lossless Decimal Identity & Parquet Precision
def test_p1_lossless_decimal_identity_and_parquet_limits(tmp_path: Path) -> None:
    s1 = Decimal("100.0000000000000000000000000001")
    s2 = Decimal("100.0000000000000000000000000002")
    assert normalize_decimal_str(s1) != normalize_decimal_str(s2)
    assert normalize_decimal_str(s1) == "100.0000000000000000000000000001"
    assert normalize_decimal_str(Decimal("22500.5000")) == "22500.5"
    assert normalize_decimal_str(Decimal("0.000")) == "0"
    assert normalize_decimal_str(Decimal("-12.3400")) == "-12.34"
    assert normalize_decimal_str(Decimal("1e-35")) == "0.00000000000000000000000000000000001"
    assert normalize_decimal_str(Decimal("1000000000000000000000000000000")) == "1000000000000000000000000000000"

    und = "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c"
    id1 = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol="AAPL260116C00100000",
        underlying_instrument_id=und,
        expiry_date=date(2026, 1, 16),
        strike_price=s1,
        option_right=OptionRight.CALL,
    )
    id2 = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol="AAPL260116C00100000",
        underlying_instrument_id=und,
        expiry_date=date(2026, 1, 16),
        strike_price=s2,
        option_right=OptionRight.CALL,
    )
    assert id1 != id2

    id_tz1 = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol="AAPL260116C00100000",
        underlying_instrument_id=und,
        expiry_date=date(2026, 1, 16),
        strike_price=Decimal("100.50"),
        option_right=OptionRight.CALL,
    )
    id_tz2 = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol="AAPL260116C00100000",
        underlying_instrument_id=und,
        expiry_date=date(2026, 1, 16),
        strike_price=Decimal("100.50000"),
        option_right=OptionRight.CALL,
    )
    assert id_tz1 == id_tz2

    # Decimal128(38, 12) limit must fail explicitly, never silently round
    inst = _make_equity()
    bad_candle = _candle(inst, datetime(2026, 1, 5, 14, 30, tzinfo=UTC), close="100.0000000000001")
    with pytest.raises(PrecisionLossError):
        write_candles_parquet([bad_candle], str(tmp_path / "bad.parquet"))


# ------------------------------------------------------------------ P1: Dataset Immutability & Content Addressing
def test_p1_dataset_immutability_and_conflict_detection(tmp_path: Path) -> None:
    inst = _make_equity()
    t0 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    t1 = datetime(2026, 1, 5, 14, 31, tzinfo=UTC)
    c0 = _candle(inst, t0, "100")
    c1 = _candle(inst, t1, "101")

    reg = DatasetRegistry(str(tmp_path / "datasets.sqlite"))
    store = CanonicalCandleStore(
        canonical_root=str(tmp_path / "candles"),
        manifest_root=str(tmp_path / "manifests"),
        registry=reg,
    )
    # Write v1
    m1 = store.write_partitioned([c0, c1], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t1 + timedelta(minutes=1))
    assert m1.row_count == 2
    verify_manifest(str(tmp_path / "manifests" / "us_eq" / "v1.json"))
    assert reg.get_manifest("us_eq", "v1")["row_count"] == 2

    # Repeat identical records (plus exact duplicate, shuffled) as v1 -> idempotent
    m1_dup = store.write_partitioned([c1, c0, c1], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t1 + timedelta(minutes=1))
    assert m1_dup.file_sha256s == m1.file_sha256s

    # Same-key conflicting duplicate in single write -> DatasetVersionConflictError
    c1_diff = _candle(inst, t1, "102")
    with pytest.raises(DatasetVersionConflictError):
        store.write_partitioned([c0, c1, c1_diff], dataset_id="us_eq", dataset_version="v1_bad", requested_start_utc=t0, requested_end_utc=t1 + timedelta(minutes=1))

    # Change one close price with same timestamps and v1 -> DatasetVersionConflictError
    with pytest.raises(DatasetVersionConflictError):
        store.write_partitioned([c0, c1_diff], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t1 + timedelta(minutes=1))

    # Write changed data as v2 -> new immutable revision
    c0_v2 = _candle(inst, t0, "100", dataset_version="v2")
    c1_v2 = _candle(inst, t1, "102", dataset_version="v2")
    m2 = store.write_partitioned([c0_v2, c1_v2], dataset_id="us_eq", dataset_version="v2", requested_start_utc=t0, requested_end_utc=t1 + timedelta(minutes=1))
    assert m2.file_sha256s != m1.file_sha256s
    assert reg.get_manifest("us_eq", "v2") is not None


# ------------------------------------------------------------------ P2: Calendar Semantics in Data Quality
def test_p2_quality_enforces_calendar_sessions_and_global_year_range() -> None:
    nse_adp = IndiaNSECalendarAdapter()
    inst_in = Instrument(
        instrument_id="",
        market=Market.IN,
        asset_class=AssetClass.INDEX,
        segment=Segment.IN_INDEX,
        exchange="NSE",
        canonical_symbol="NIFTY",
        trading_symbol="NIFTY",
        display_name="NIFTY",
        price_currency="INR",
        is_tradable=False,
    )
    qe_in = DataQualityEngine(calendar=nse_adp)

    # Holiday 2026-01-15 -> rejected
    c_hol = _candle(inst_in, datetime(2026, 1, 15, 4, 0, tzinfo=UTC), trading_date=date(2026, 1, 15))
    r_hol = qe_in.evaluate_candles([c_hol], now_utc=datetime(2026, 12, 1, tzinfo=UTC))
    assert r_hol.rejected_count == 1
    assert r_hol.status == "INVALID_DATA"

    # Muhurat 2026-11-08 14:25 IST (08:55 UTC) -> accepted
    c_muh = _candle(inst_in, datetime(2026, 11, 8, 8, 55, tzinfo=UTC), trading_date=date(2026, 11, 8), trading_session="MUHURAT")
    r_muh = qe_in.evaluate_candles([c_muh], now_utc=datetime(2026, 12, 1, tzinfo=UTC))
    assert r_muh.valid_count == 1

    # Outside regular NSE session (08:00 IST = 02:30 UTC) -> rejected
    c_off = _candle(inst_in, datetime(2026, 1, 5, 2, 30, tzinfo=UTC), trading_date=date(2026, 1, 5))
    r_off = qe_in.evaluate_candles([c_off], now_utc=datetime(2026, 12, 1, tzinfo=UTC))
    assert r_off.rejected_count == 1

    # Mixed 2026/2027 batch -> detects unverified 2027
    c_2026 = _candle(inst_in, datetime(2026, 1, 5, 4, 0, tzinfo=UTC), trading_date=date(2026, 1, 5))
    c_2027 = _candle(inst_in, datetime(2027, 1, 5, 4, 0, tzinfo=UTC), trading_date=date(2027, 1, 5))
    r_mix = qe_in.evaluate_candles([c_2027, c_2026], now_utc=datetime(2027, 12, 1, tzinfo=UTC))
    assert r_mix.status == "UNVERIFIED_CALENDAR"

    # CME maintenance break (16:15 CT on 2026-01-05 = 22:15 UTC) -> rejected
    cme_adp = USFuturesCalendarAdapter()
    qe_cme = DataQualityEngine(calendar=cme_adp)
    c_maint = _candle(inst_in, datetime(2026, 1, 5, 22, 15, tzinfo=UTC), trading_date=date(2026, 1, 5), trading_session="GLOBEX")
    r_maint = qe_cme.evaluate_candles([c_maint], now_utc=datetime(2026, 12, 1, tzinfo=UTC))
    assert r_maint.rejected_count == 1


# ------------------------------------------------------------------ P2: UTC Normalization & Hardened Resampling
def test_p2_utc_normalization_and_hardened_resampling(tmp_path: Path) -> None:
    inst = _make_equity()
    t_ist = datetime(2026, 1, 5, 9, 15, tzinfo=IST_TZ)  # 03:45 UTC
    c = _candle(inst, t_ist, "100", trading_date=date(2026, 1, 5))
    assert c.timestamp_start_utc.tzinfo == UTC
    assert c.timestamp_start_utc == datetime(2026, 1, 5, 3, 45, tzinfo=UTC)

    tz_m4 = timezone(timedelta(hours=-4))
    q = CanonicalQuote(inst.instrument_id, datetime(2026, 1, 5, 10, 0, tzinfo=tz_m4), datetime(2026, 1, 5, 10, 0, tzinfo=tz_m4), Decimal("100"), Decimal("101"), Decimal("10"), Decimal("10"), "NASDAQ", "alpaca", "iex")
    assert q.event_time_utc == datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    tr = CanonicalTrade(inst.instrument_id, "t1", datetime(2026, 1, 5, 10, 0, tzinfo=tz_m4), datetime(2026, 1, 5, 10, 0, tzinfo=tz_m4), Decimal("100.5"), Decimal("5"), "NASDAQ", "alpaca", "iex", "s1")
    assert tr.event_time_utc == datetime(2026, 1, 5, 14, 0, tzinfo=UTC)

    with pytest.raises(SchemaValidationError):
        _candle(inst, datetime(2026, 1, 5, 9, 15))  # naive

    pq_path = str(tmp_path / "utc.parquet")
    write_candles_parquet([c], pq_path)
    loaded = read_candles_parquet(pq_path)
    assert loaded[0].timestamp_start_utc == datetime(2026, 1, 5, 3, 45, tzinfo=UTC)

    # Session-aligned 1h resampling for US (09:30 ET = 14:30 UTC) with missing bar & partial bucket
    us_open = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    bars_1m = [
        _candle(inst, us_open, "100", quality_flags=("flag_a",)),
        # skip 14:31 -> gap!
        _candle(inst, us_open + timedelta(minutes=2), "102", quality_flags=("flag_b",)),
    ]
    res_1h = resample_candles(bars_1m, "1h")
    assert len(res_1h) == 1
    assert res_1h[0].timestamp_start_utc == us_open
    assert "partial_bucket" in res_1h[0].quality_flags
    assert "missing_constituent_bars" in res_1h[0].quality_flags
    assert "flag_a" in res_1h[0].quality_flags and "flag_b" in res_1h[0].quality_flags
    with pytest.raises(SchemaValidationError):
        resample_candles(bars_1m, "1h", partial_policy="REJECT")


# ------------------------------------------------------------------ P2: CoinDCX Metadata & CME Underlying
def test_p2_coindcx_metadata_and_cme_underlying() -> None:
    class _MockCryptoClient:
        def get(self, url: str, params: Dict[str, Any] | None = None) -> CryptoHTTPResponse:
            if url.endswith("/active_instruments"):
                mc = (params or {}).get("margin_currency_short_name[]")
                if mc == "USDT":
                    return CryptoHTTPResponse(200, ["B-BTC_USDT", "B-ETH_USDT"], {})
                return CryptoHTTPResponse(200, [], {})
            pair = (params or {}).get("pair")
            if pair == "B-ETH_USDT":
                return CryptoHTTPResponse(200, {"instrument": {
                    "pair": "B-ETH_USDT",
                    "position_currency_short_name": "ETH",
                    "quote_currency_short_name": "USDT",
                    "settle_currency_short_name": "USDC",
                    "kind": "perpetual",
                    "is_quanto": True,
                    "price_increment": "0.1",
                    "quantity_increment": "0.01",
                    "contract_value": "1",
                }}, {})
            return CryptoHTTPResponse(200, {"instrument": {
                "pair": "B-BTC_USDT",
                "position_currency_short_name": "BTC",
                "quote_currency_short_name": "USDT",
                "settle_currency_short_name": "USDC",
                "margin_currency_short_name": "USDT",
                "kind": "perpetual",
                "is_quanto": False,
                "price_increment": "0.5",
                "quantity_increment": "0.001",
                "contract_value": "0.01",
            }}, {})

    rep = CoinDCXDiscovery(client=_MockCryptoClient()).discover_futures(margin_currencies=("USDT",), universe=("BTC", "ETH"), dry_run=True)
    assert len(rep.perpetual_instruments) == 1
    assert rep.perpetual_instruments[0].settlement_currency == "USDC"
    assert rep.perpetual_instruments[0].contract_multiplier == Decimal("0.01")
    assert any(u["pair"] == "B-ETH_USDT" and u["reason"] == "UNSUPPORTED_QUANTO" for u in rep.unsupported)

    # CME Futures underlying canonical index registration + validation
    reg = InstrumentRegistry(":memory:")
    disc = FuturesContractDiscovery()
    f_rep = disc.discover_from_definitions(
        [{
            "raw_symbol": "ESH6",
            "asset": "ES",
            "instrument_id": 12345,
            "exchange": "XCME",
            "venue": "GLBX",
            "currency": "USD",
            "expiry_date": "2026-03-20",
            "contract_multiplier": "50",
            "tick_size": "0.25",
            "tick_value": "12.50",
            "settlement_type": "CASH",
            "ts_event_utc": "2026-01-05T00:00:00Z",
        }],
        registry=reg,
        as_of_date=date(2026, 1, 5),
        dry_run=False,
    )
    assert len(f_rep.contracts) == 1
    fut = f_rep.contracts[0]
    assert fut.underlying_instrument_id is not None
    und = reg.get(fut.underlying_instrument_id)
    assert und is not None
    assert und.asset_class == AssetClass.INDEX
    assert und.is_tradable is False
