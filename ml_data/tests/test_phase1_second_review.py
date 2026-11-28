"""Focused regression tests for Phase 1 Second Independent Review Remediation (P1-A..D, P2-A..F)."""
from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest

from ml_data.calendars import (
    IndiaNSECalendarAdapter,
    USEquityCalendarAdapter,
    USFuturesCalendarAdapter,
    audit_calendar,
)
from ml_data.calendars.audit import _validate_spec_contents
from ml_data.calendars.verified_schedules import VerifiedCalendarSpec
from ml_data.crypto.coindcx import CoinDCXDiscovery
from ml_data.crypto.config import CryptoHTTPResponse
from ml_data.futures.config import CME_TZ
from ml_data.futures.exceptions import FuturesInputError
from ml_data.india.config import IST_TZ
from ml_data.instruments import AssetClass, Instrument, MarginType, Market, Segment
from ml_data.quality import DataQualityEngine
from ml_data.storage import (
    CanonicalCandle,
    CanonicalCandleStore,
    DatasetRegistry,
    DatasetVersionConflictError,
    PrecisionLossError,
    SchemaValidationError,
    read_candles_parquet,
    resample_candles,
    write_candles_parquet,
)
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
    received_at_utc: datetime | None = None,
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
        received_at_utc=received_at_utc or end_utc,
        timeframe=timeframe,
        trading_date=td,
        trading_session=trading_session,
        session_id=f"{inst.exchange}_{td.isoformat()}",
        calendar_id=f"{inst.exchange}_CAL",
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


# ------------------------------------------------------------------ P1-A: Default US Equity & CME Calendar Wiring
def test_p1a_default_adapters_are_verified_and_fail_closed() -> None:
    us_nyse = USEquityCalendarAdapter()
    us_nasdaq = USEquityCalendarAdapter(calendar_id="XNAS")
    assert us_nyse.is_trading_day(date(2026, 7, 3), require_verified=True) is False  # Independence Day observed
    assert us_nyse.is_trading_day(date(2026, 7, 6), require_verified=True) is True
    assert us_nyse.metadata.verified_years == frozenset({2026, 2027, 2028})
    assert us_nasdaq.metadata.verified_years == frozenset()
    assert us_nasdaq.metadata.verification_status == "PARTIALLY_VERIFIED"
    with pytest.raises(USCalendarError):
        us_nyse.is_trading_day(date(2029, 1, 5), require_verified=True)

    cme = USFuturesCalendarAdapter()
    assert cme.is_trading_day(date(2026, 12, 25), require_verified=True) is False
    assert cme.metadata.verified_years == frozenset({2026})
    assert cme.classify_session(datetime(2026, 11, 25, 16, 30, tzinfo=CME_TZ)) == "MAINTENANCE_BREAK"
    assert cme.classify_session(datetime(2026, 11, 27, 13, 0, tzinfo=CME_TZ)) == "CLOSED"  # Early close 12:15 CT
    with pytest.raises(FuturesInputError):
        cme.is_trading_day(date(2027, 1, 4), require_verified=True)


# ------------------------------------------------------------------ P1-B: Data Quality Trading-Date Consistency
def test_p1b_quality_trading_date_consistency() -> None:
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
    ts_ist = datetime(2026, 1, 5, 9, 30, tzinfo=IST_TZ)  # 04:00 UTC

    # Wrong trading_date 2026-01-06 -> rejected
    bad = _c(inst_in, ts_ist, trading_date=date(2026, 1, 6))
    rep_bad = qe_in.evaluate_candles([bad], now_utc=datetime(2026, 12, 1, tzinfo=UTC))
    assert rep_bad.rejected_count == 1
    assert "trading_date_mismatch" in rep_bad.rejected_records[0].reason

    # Correct trading_date 2026-01-05 -> accepted
    ok = _c(inst_in, ts_ist, trading_date=date(2026, 1, 5))
    rep_ok = qe_in.evaluate_candles([ok], now_utc=datetime(2026, 12, 1, tzinfo=UTC))
    assert rep_ok.valid_count == 1

    # CME Sunday evening 18:00 CT on 2026-01-04 -> Globex trade date 2026-01-05
    cme_adp = USFuturesCalendarAdapter()
    qe_cme = DataQualityEngine(calendar=cme_adp)
    cme_sun = datetime(2026, 1, 4, 18, 0, tzinfo=CME_TZ)
    c_cme_ok = _c(inst_in, cme_sun, trading_date=date(2026, 1, 5), trading_session="ETH")
    c_cme_bad = _c(inst_in, cme_sun, trading_date=date(2026, 1, 4), trading_session="ETH")
    assert qe_cme.evaluate_candles([c_cme_ok], now_utc=datetime(2026, 12, 1, tzinfo=UTC)).valid_count == 1
    assert qe_cme.evaluate_candles([c_cme_bad], now_utc=datetime(2026, 12, 1, tzinfo=UTC)).rejected_count == 1


# ------------------------------------------------------------------ P1-C & P1-D: Full Signature & Manifest Immutability
def test_p1c_p1d_full_candle_signature_and_manifest_immutability(tmp_path: Path) -> None:
    inst = _eq()
    t0 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    c0 = _c(inst, t0, "100", received_at_utc=t0 + timedelta(seconds=1))
    c0_diff_recv = _c(inst, t0, "100", received_at_utc=t0 + timedelta(seconds=5))

    reg = DatasetRegistry(str(tmp_path / "ds.sqlite"))
    store = CanonicalCandleStore(
        canonical_root=str(tmp_path / "candles"),
        manifest_root=str(tmp_path / "manifests"),
        registry=reg,
    )
    m1 = store.write_partitioned([c0], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=1))

    # Different received_at_utc must conflict on same v1
    with pytest.raises(DatasetVersionConflictError):
        store.write_partitioned([c0_diff_recv], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=1))

    # Conflicting duplicates in either order fail
    with pytest.raises(DatasetVersionConflictError):
        store.write_partitioned([c0, c0_diff_recv], dataset_id="us_eq", dataset_version="v1_dup_a", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=1))
    with pytest.raises(DatasetVersionConflictError):
        store.write_partitioned([c0_diff_recv, c0], dataset_id="us_eq", dataset_version="v1_dup_b", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=1))

    # Identical semantic metadata is idempotent
    m1_idem = store.write_partitioned([c0], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=1))
    assert m1_idem.file_sha256s == m1.file_sha256s

    # Changing pagination_complete / quality_summary / requested_end_utc on v1 must conflict
    with pytest.raises(DatasetVersionConflictError):
        store.write_partitioned([c0], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=1), pagination_complete=False)
    with pytest.raises(DatasetVersionConflictError):
        store.write_partitioned([c0], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=1), quality_summary={"status": "DIFF"})
    with pytest.raises(DatasetVersionConflictError):
        store.write_partitioned([c0], dataset_id="us_eq", dataset_version="v1", requested_start_utc=t0, requested_end_utc=t0 + timedelta(minutes=2))


# ------------------------------------------------------------------ P2-A: Decimal128 Trailing-Zero Handling
def test_p2a_decimal128_trailing_zeros_and_overflow(tmp_path: Path) -> None:
    inst = _eq()
    t0 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    c_tz = CanonicalCandle(
        **{
            **_c(inst, t0).__dict__,
            "open": Decimal("100.0000000000000"),
            "high": Decimal("101.23000000000000"),
            "low": Decimal("99.500000000000000"),
            "close": Decimal("100.0000000000000"),
        }
    )
    pq_path = str(tmp_path / "tz.parquet")
    write_candles_parquet([c_tz], pq_path)
    loaded = read_candles_parquet(pq_path)
    assert loaded[0].open == Decimal("100")
    assert loaded[0].high == Decimal("101.23")

    c_bad = _c(inst, t0, close="1.23000000000001")
    with pytest.raises(PrecisionLossError):
        write_candles_parquet([c_bad], str(tmp_path / "bad_scale.parquet"))


# ------------------------------------------------------------------ P2-B: Session-Aligned Resampling Anchor
def test_p2b_session_aligned_resampling_when_opening_bar_missing() -> None:
    inst = _eq()
    # US 2026-01-05 (EST, UTC-5): 09:30 ET = 14:30 UTC. Missing 14:30 bar; start at 14:31!
    t_0931 = datetime(2026, 1, 5, 14, 31, tzinfo=UTC)
    bars = [
        _c(inst, t_0931, "100", trading_date=date(2026, 1, 5)),
        _c(inst, t_0931 + timedelta(minutes=1), "101", trading_date=date(2026, 1, 5)),
    ]
    res_5m = resample_candles(bars, "5m")
    assert len(res_5m) == 1
    assert res_5m[0].timestamp_start_utc == datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    assert "partial_bucket" in res_5m[0].quality_flags

    # Mixed dataset_version / retrieval_run_id rejected
    b_mix = _c(inst, t_0931 + timedelta(minutes=2), "102", trading_date=date(2026, 1, 5), retrieval_run_id="run-2")
    with pytest.raises(SchemaValidationError):
        resample_candles([bars[0], b_mix], "5m")


# ------------------------------------------------------------------ P2-C: Calendar Publication Provenance Validation
def test_p2c_calendar_provenance_chronological_validation() -> None:
    future_spec = VerifiedCalendarSpec(
        calendar_id="TEST",
        market="US",
        venue="TEST",
        product_group="TEST",
        timezone="UTC",
        year=2027,
        sessions={"regular": "09:30-16:00"},
        holidays=(),
        early_closes={},
        special_sessions={},
        source_url="https://example.com",
        source_document_reference="DOC-1",
        source_published_at="2027-01-01",
        retrieved_at="2026-11-28T00:00:00Z",
        verified_at="2026-11-28T00:00:00Z",
        calendar_version="2027.1",
        verification_status="VERIFIED_OFFICIAL",
    )
    errs = _validate_spec_contents(future_spec, now_utc=datetime(2026, 11, 28, tzinfo=UTC))
    assert any("future source_published_at" in e for e in errs)
    assert audit_calendar("us_futures", 2027)["verification_status"] == "PARTIALLY_VERIFIED"


# ------------------------------------------------------------------ P2-E: Decouple Calendar CLI from kite_ticker
def test_p2e_importing_calendars_does_not_import_kite_ticker() -> None:
    proc = subprocess.run(
        [sys.executable, "-B", "-c", "import sys, ml_data.calendars; assert 'kite_ticker' not in sys.modules"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


# ------------------------------------------------------------------ P2-F: CoinDCX unit_contract_value & Missing Contract Value
def test_p2f_coindcx_unit_contract_value_and_missing_value_rejected() -> None:
    class _MockClient:
        def get(self, url: str, params: Dict[str, Any] | None = None) -> CryptoHTTPResponse:
            if url.endswith("/active_instruments"):
                return CryptoHTTPResponse(200, ["B-BTC_USDT", "B-SOL_USDT"], {})
            pair = (params or {}).get("pair")
            if pair == "B-SOL_USDT":
                return CryptoHTTPResponse(200, {"instrument": {
                    "pair": "B-SOL_USDT",
                    "position_currency_short_name": "SOL",
                    "quote_currency_short_name": "USDT",
                    "settle_currency_short_name": "USDT",
                    "kind": "perpetual",
                    "is_quanto": False,
                    "price_increment": "0.01",
                    "quantity_increment": "0.1",
                }}, {})
            return CryptoHTTPResponse(200, {"instrument": {
                "pair": "B-BTC_USDT",
                "position_currency_short_name": "BTC",
                "quote_currency_short_name": "USDT",
                "settle_currency_short_name": "USDT",
                "margin_currency_short_name": "USDT",
                "kind": "perpetual",
                "is_inverse": False,
                "is_quanto": False,
                "price_increment": "0.1",
                "quantity_increment": "0.001",
                "unit_contract_value": "0.001",
            }}, {})

    rep = CoinDCXDiscovery(client=_MockClient()).discover_futures(margin_currencies=("USDT",), universe=("BTC", "SOL"), dry_run=True)
    assert len(rep.perpetual_instruments) == 1
    assert rep.perpetual_instruments[0].contract_multiplier == Decimal("0.001")
    assert rep.perpetual_instruments[0].margin_type == MarginType.LINEAR
    assert any(u["pair"] == "B-SOL_USDT" and u["reason"] == "MISSING_CONTRACT_VALUE" for u in rep.unsupported)
