"""Tests for unified cross-market calendars, CanonicalCandle/Parquet/Manifests, QualityEngine, and Reconciliation."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from ml_data.calendars import (
    CryptoCalendarAdapter,
    IndiaNSECalendarAdapter,
    USEquityCalendarAdapter,
    USFuturesCalendarAdapter,
)
from ml_data.instruments import AssetClass, ContractType, Instrument, InstrumentRegistry, Market, Segment
from ml_data.quality import CrossMarketReconciler, DataQualityEngine
from ml_data.storage import (
    CanonicalCandle,
    CanonicalCandleStore,
    CanonicalQuote,
    CanonicalTrade,
    DatasetRegistry,
    IngestionCheckpointStore,
    ManifestError,
    PrecisionLossError,
    read_candles_parquet,
    resample_candles,
    verify_manifest,
    write_candles_parquet,
)
from ml_data.us.config import USCalendar


def _make_candle(iid: str, ts_start: datetime, close_str: str, *, provider: str = "alpaca", feed: str = "iex", market: str = "US", ac: str = "EQUITY", tick_ok: bool = True) -> CanonicalCandle:
    from datetime import timedelta
    o = Decimal("100.00")
    c = Decimal(close_str)
    h = max(o, c) + Decimal("0.50")
    l = min(o, c) - Decimal("0.50")
    return CanonicalCandle(
        instrument_id=iid,
        market=market,
        asset_class=ac,
        segment="US_EQUITY" if market == "US" else "CRYPTO_SPOT",
        exchange="NASDAQ" if market == "US" else "COINBASE",
        provider=provider,
        provider_symbol="AAPL" if market == "US" else "BTC-USD",
        provider_instrument_id="a1",
        timestamp_start_utc=ts_start,
        timestamp_end_utc=ts_start + timedelta(minutes=1),
        event_time_utc=ts_start + timedelta(minutes=1),
        received_at_utc=ts_start + timedelta(minutes=1, seconds=1),
        timeframe="1m",
        trading_date=ts_start.date(),
        trading_session="REGULAR",
        session_id="2026-11-25-REG",
        calendar_id="XNYS" if market == "US" else "CRYPTO_24_7",
        calendar_version="2026.1",
        open=o,
        high=h,
        low=l,
        close=c,
        volume=Decimal("1000"),
        provider_feed=feed,
        source_snapshot_id="snap-1",
        source_record_id=f"rec-{ts_start.isoformat()}",
        dataset_version="v1",
        adjustment_mode="raw",
        retrieval_run_id="run-1",
        quality_status="VERIFIED_WITH_DATA",
    )


def test_parquet_decimal_precision_manifests_resampling_and_registry(tmp_path):
    t0 = datetime(2026, 11, 25, 14, 30, tzinfo=timezone.utc)
    c1 = _make_candle("US:NASDAQ:EQUITY:AAPL#111", t0, "101.25")
    c2 = _make_candle("US:NASDAQ:EQUITY:AAPL#111", datetime(2026, 11, 25, 14, 31, tzinfo=timezone.utc), "102.50")

    # Resample 1m -> 5m without fabricating missing bars
    c5 = resample_candles([c1, c2], "5m")
    assert len(c5) == 1
    assert c5[0].open == Decimal("100.00")
    assert c5[0].close == Decimal("102.50")
    assert c5[0].volume == Decimal("2000")

    # Parquet round-trip preserves exact Decimal
    pq_path = str(tmp_path / "direct.parquet")
    write_candles_parquet([c1, c2], pq_path)
    loaded = read_candles_parquet(pq_path)
    assert loaded[0].close == Decimal("101.25") and isinstance(loaded[0].close, Decimal)

    # Precision loss (>12 decimals) must raise, never silently round
    c_hi_prec = _make_candle("US:NASDAQ:EQUITY:AAPL#111", t0, "101.1234567890123")
    with pytest.raises(PrecisionLossError):
        write_candles_parquet([c_hi_prec], str(tmp_path / "fail.parquet"))

    # Partitioned store + manifest SHA-256 verification + tamper detection
    store = CanonicalCandleStore(canonical_root=str(tmp_path / "canonical"), manifest_root=str(tmp_path / "manifests"))
    man = store.write_partitioned(
        [c1, c2, c1],  # duplicate c1 deduplicated idempotently
        dataset_id="us_eq_1m",
        dataset_version="v1",
        requested_start_utc=t0,
        requested_end_utc=datetime(2026, 11, 25, 14, 35, tzinfo=timezone.utc),
        duplicate_count=1,
    )
    assert man.row_count == 2
    man_file = str(tmp_path / "manifests" / "us_eq_1m" / "v1.json")
    assert verify_manifest(man_file).row_count == 2

    # Tampering Parquet file invalidates manifest checksum
    with open(man.file_paths[0], "ab") as fh:
        fh.write(b"tamper")
    with pytest.raises(ManifestError):
        verify_manifest(man_file)

    # DatasetRegistry & CheckpointStore
    dreg = DatasetRegistry(str(tmp_path / "dreg.sqlite3"))
    assert dreg.schema_version() == 1
    dreg.register_manifest(man)
    assert dreg.get_manifest("us_eq_1m", "v1")["row_count"] == 2
    dreg.close()

    ckpt = IngestionCheckpointStore(str(tmp_path / "ckpts"))
    kf = {"instrument_id": c1.instrument_id, "tf": "1m", "feed": "iex", "adj": "raw"}
    ckpt.save(kf, {"done": True})
    assert ckpt.load(kf)["state"]["done"] is True

    # CanonicalQuote & CanonicalTrade Decimal invariants
    q = CanonicalQuote(
        instrument_id=c1.instrument_id, event_time_utc=t0, received_at_utc=t0,
        bid_price=Decimal("101.20"), ask_price=Decimal("101.25"),
        bid_size=Decimal("10"), ask_size=Decimal("20"),
        exchange="NASDAQ", provider="alpaca", feed="iex",
    )
    tr = CanonicalTrade(
        instrument_id=c1.instrument_id, trade_id="t1", event_time_utc=t0, received_at_utc=t0,
        price=Decimal("101.22"), quantity=Decimal("5"),
        exchange="NASDAQ", provider="alpaca", feed="iex", source_id="src1",
    )
    assert q.ask_price > q.bid_price and tr.price == Decimal("101.22")


def test_quality_engine_reconciliation_and_calendars(tmp_path):
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    aapl = Instrument(
        instrument_id="", market=Market.US, asset_class=AssetClass.EQUITY, segment=Segment.US_EQUITY,
        exchange="NASDAQ", canonical_symbol="AAPL", trading_symbol="AAPL", display_name="Apple",
        price_currency="USD", tick_size=Decimal("0.01"), contract_type=ContractType.EQUITY,
    )
    reg.upsert(aapl)

    t0 = datetime(2026, 11, 25, 14, 30, tzinfo=timezone.utc)
    c_ok = _make_candle(aapl.instrument_id, t0, "101.25", provider="alpaca", feed="iex")
    c_other_feed = _make_candle(aapl.instrument_id, t0, "101.30", provider="alpaca", feed="sip")
    c_bad_tick = _make_candle(aapl.instrument_id, datetime(2026, 11, 25, 14, 31, tzinfo=timezone.utc), "101.255")

    cal = USEquityCalendarAdapter(USCalendar(verified_years=frozenset({2026})))
    qe = DataQualityEngine(registry=reg, calendar=cal)
    qr = qe.evaluate_candles([c_ok, c_bad_tick], now_utc=datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc))
    assert qr.valid_count == 1 and qr.rejected_count == 1
    assert qr.status == "PARTIAL_DATA"
    assert "tick_size_violation" in qr.rejected_records[0].reason

    # Reconciliation detects multi-feed discrepancy without hiding either observation
    rec = CrossMarketReconciler(registry=reg).reconcile_candles([c_ok, c_other_feed], expected_count=1)
    assert len(rec.price_discrepancies) == 1
    assert rec.price_discrepancies[0].abs_diff == Decimal("0.05")

    # Cross-market calendars remain independent
    assert CryptoCalendarAdapter().classify_session(t0) == "CONTINUOUS_24_7"
    assert IndiaNSECalendarAdapter().metadata.timezone == "Asia/Kolkata"
    assert USFuturesCalendarAdapter().metadata.timezone == "America/Chicago"
    reg.close()
