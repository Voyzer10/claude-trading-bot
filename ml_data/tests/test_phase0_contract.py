"""Phase 0 Step 1: Canonical Market-Data Contract validation tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ml_data.india.config import IST_TZ
from ml_data.instruments import (
    AssetClass,
    ContractType,
    Instrument,
    InstrumentValidationError,
    Market,
    OptionRight,
    ProviderInstrumentMapping,
    Segment,
    SettlementType,
)
from ml_data.storage import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalCandle,
    CanonicalQuote,
    CanonicalTrade,
    SchemaValidationError,
)

UTC = timezone.utc


def test_phase0_instrument_identity_mapping_and_json_roundtrip() -> None:
    eq = Instrument(
        instrument_id="",
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        segment=Segment.US_EQUITY,
        exchange="NASDAQ",
        canonical_symbol="AAPL",
        trading_symbol="AAPL",
        display_name="Apple Inc.",
        price_currency="USD",
        primary_provider="alpaca",
        tick_size=Decimal("0.01"),
        trading_calendar="XNAS",
        timezone="America/New_York",
    )
    assert eq.identity_version == "v3"
    assert eq.schema_version == "1.0.0"
    assert eq.instrument_id.startswith("US:NASDAQ:EQUITY:AAPL#")
    assert Instrument.from_json(eq.to_json()).instrument_id == eq.instrument_id

    mapping = ProviderInstrumentMapping(
        instrument_id=eq.instrument_id,
        provider="ALPACA",
        provider_symbol="AAPL",
        provider_exchange="nasdaq",
        provider_feed="IEX",
        is_primary=True,
    )
    assert mapping.provider == "alpaca"
    assert mapping.provider_exchange == "NASDAQ"
    assert mapping.provider_feed == "iex"
    assert len(mapping.mapping_id) > 0

    # Illustrative India NIFTY option example (effective-dated spec values are synthetic)
    idx = Instrument(
        instrument_id="",
        market=Market.IN,
        asset_class=AssetClass.INDEX,
        segment=Segment.IN_INDEX,
        exchange="NSE",
        canonical_symbol="NIFTY",
        trading_symbol="NIFTY",
        display_name="NIFTY 50",
        price_currency="INR",
        is_tradable=False,
    )
    opt = Instrument(
        instrument_id="",
        market=Market.IN,
        asset_class=AssetClass.OPTION,
        segment=Segment.IN_INDEX_OPTIONS,
        exchange="NFO",
        canonical_symbol="NIFTY26MAR24000CE",
        trading_symbol="NIFTY26MAR24000CE",
        display_name="NIFTY 24000 CE",
        price_currency="INR",
        underlying_instrument_id=idx.instrument_id,
        expiry_date=date(2026, 3, 26),
        strike_price=Decimal("24000.00"),
        option_right="CE",
        contract_multiplier=Decimal("75"),
        contract_type=ContractType.OPTION,
        settlement_type=SettlementType.CASH,
    )
    assert opt.option_right == OptionRight.CALL
    assert ":24000:CALL:" in opt.instrument_id


def test_phase0_invalid_identity_version_and_float_rejected() -> None:
    with pytest.raises(InstrumentValidationError):
        Instrument(
            instrument_id="",
            market=Market.US,
            asset_class=AssetClass.EQUITY,
            segment=Segment.US_EQUITY,
            exchange="NASDAQ",
            canonical_symbol="AAPL",
            trading_symbol="AAPL",
            display_name="Apple Inc.",
            price_currency="USD",
            identity_version="v2",
        )
    with pytest.raises(InstrumentValidationError):
        Instrument(
            instrument_id="",
            market=Market.US,
            asset_class=AssetClass.EQUITY,
            segment=Segment.US_EQUITY,
            exchange="NASDAQ",
            canonical_symbol="AAPL",
            trading_symbol="AAPL",
            display_name="Apple Inc.",
            price_currency="USD",
            tick_size=0.01,  # type: ignore[arg-type]
        )


def test_phase0_candle_validation_invariants_and_json_roundtrip() -> None:
    iid = "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c"
    t0_ist = datetime(2026, 1, 5, 20, 0, tzinfo=IST_TZ)  # 14:30 UTC
    t1_ist = t0_ist + timedelta(minutes=5)

    c = CanonicalCandle(
        instrument_id=iid,
        market="US",
        asset_class="EQUITY",
        segment="US_EQUITY",
        exchange="NASDAQ",
        provider="alpaca",
        provider_symbol="AAPL",
        provider_instrument_id="AAPL",
        timestamp_start_utc=t0_ist,
        timestamp_end_utc=t1_ist,
        event_time_utc=t1_ist,
        received_at_utc=t1_ist,
        timeframe="5m",
        trading_date=date(2026, 1, 5),
        trading_session="REGULAR",
        session_id="XNAS_2026-01-05",
        calendar_id="XNAS",
        calendar_version="2026.1",
        open=Decimal("185.10"),
        high=Decimal("185.45"),
        low=Decimal("185.00"),
        close=Decimal("185.30"),
        volume=Decimal("12450"),
        trade_count=142,
        provider_feed="iex",
        source_snapshot_id="snap-1",
        source_record_id="rec-1",
        dataset_version="v1",
        adjustment_mode="RAW",
        retrieval_run_id="run-1",
        quality_status="VERIFIED",
        quality_flags=("partial_bucket",),
    )
    assert c.schema_version == CANONICAL_SCHEMA_VERSION == "1.0.0"
    assert c.timestamp_start_utc.tzinfo == UTC
    assert c.timestamp_start_utc == datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    assert c.open_interest is None and c.funding_rate is None

    # JSON round-trip preserves exact Decimals, UTC instants, tuples, and None
    c_rt = CanonicalCandle.from_json(c.to_json())
    assert c_rt == c

    # Partial bucket (< 5m) is permitted
    c_partial = CanonicalCandle(**{**c.__dict__, "timestamp_end_utc": t0_ist + timedelta(minutes=2)})
    assert (c_partial.timestamp_end_utc - c_partial.timestamp_start_utc) == timedelta(minutes=2)

    # Interval exceeding timeframe rejected
    with pytest.raises(SchemaValidationError):
        CanonicalCandle(**{**c.__dict__, "timestamp_end_utc": t0_ist + timedelta(minutes=10)})

    # Unsupported schema_version, unsupported timeframe, negative/bool trade_count, empty str rejected
    with pytest.raises(SchemaValidationError):
        CanonicalCandle(**{**c.__dict__, "schema_version": "2.0.0"})
    with pytest.raises(SchemaValidationError):
        CanonicalCandle(**{**c.__dict__, "timeframe": "3m"})
    with pytest.raises(SchemaValidationError):
        CanonicalCandle(**{**c.__dict__, "trade_count": -1})
    with pytest.raises(SchemaValidationError):
        CanonicalCandle(**{**c.__dict__, "trade_count": True})  # type: ignore[arg-type]
    with pytest.raises(SchemaValidationError):
        CanonicalCandle(**{**c.__dict__, "provider_feed": "   "})
    with pytest.raises(SchemaValidationError):
        CanonicalCandle(**{**c.__dict__, "high": Decimal("185.20")})
    with pytest.raises(SchemaValidationError):
        CanonicalCandle(**{**c.__dict__, "open": 185.10})  # type: ignore[arg-type]


def test_phase0_quote_and_trade_validation_and_json_roundtrip() -> None:
    iid = "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c"
    t0_ist = datetime(2026, 1, 5, 20, 0, tzinfo=IST_TZ)

    q = CanonicalQuote(
        instrument_id=iid,
        event_time_utc=t0_ist,
        received_at_utc=t0_ist,
        bid_price=Decimal("185.10"),
        ask_price=Decimal("185.12"),
        bid_size=Decimal("200"),
        ask_size=Decimal("300"),
        exchange="NASDAQ",
        provider="alpaca",
        feed="iex",
        quality_flags=("iex_top_of_book",),
    )
    assert q.event_time_utc.tzinfo == UTC
    assert q.depth_json is None and q.sequence_id is None
    assert CanonicalQuote.from_json(q.to_json()) == q
    with pytest.raises(SchemaValidationError):
        CanonicalQuote(**{**q.__dict__, "bid_size": Decimal("-1")})
    with pytest.raises(SchemaValidationError):
        CanonicalQuote(**{**q.__dict__, "feed": ""})

    tr = CanonicalTrade(
        instrument_id=iid,
        trade_id="trd-1",
        event_time_utc=t0_ist,
        received_at_utc=t0_ist,
        price=Decimal("185.12"),
        quantity=Decimal("50"),
        exchange="NASDAQ",
        provider="alpaca",
        feed="iex",
        source_id="alpaca-iex",
        conditions=("@",),
    )
    assert tr.event_time_utc.tzinfo == UTC
    assert tr.aggressor_side is None and tr.quote_quantity is None
    assert CanonicalTrade.from_json(tr.to_json()) == tr
    with pytest.raises(SchemaValidationError):
        CanonicalTrade(**{**tr.__dict__, "quantity": Decimal("-5")})
    with pytest.raises(SchemaValidationError):
        CanonicalTrade(**{**tr.__dict__, "trade_id": "  "})


def test_phase0_micro_fixes_trading_date_iana_tz_and_tuple_normalization() -> None:
    # 1. Instrument IANA timezone validation
    for valid_tz in ("UTC", "America/New_York", "Asia/Kolkata"):
        inst = Instrument(
            instrument_id="",
            market=Market.US,
            asset_class=AssetClass.EQUITY,
            segment=Segment.US_EQUITY,
            exchange="NASDAQ",
            canonical_symbol="AAPL",
            trading_symbol="AAPL",
            display_name="Apple Inc.",
            price_currency="USD",
            timezone=valid_tz,
        )
        assert inst.timezone == valid_tz
    with pytest.raises(InstrumentValidationError):
        Instrument(
            instrument_id="",
            market=Market.US,
            asset_class=AssetClass.EQUITY,
            segment=Segment.US_EQUITY,
            exchange="NASDAQ",
            canonical_symbol="AAPL",
            trading_symbol="AAPL",
            display_name="Apple Inc.",
            price_currency="USD",
            timezone="Mars/Olympus_Mons",
        )

    # 2. CanonicalCandle.trading_date strict datetime.date validation
    iid = "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c"
    t0 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=5)
    base = CanonicalCandle(
        instrument_id=iid, market="US", asset_class="EQUITY", segment="US_EQUITY",
        exchange="NASDAQ", provider="alpaca", provider_symbol="AAPL", provider_instrument_id="AAPL",
        timestamp_start_utc=t0, timestamp_end_utc=t1, event_time_utc=t1, received_at_utc=t1,
        timeframe="5m", trading_date=date(2026, 1, 5), trading_session="REGULAR",
        session_id="XNAS_2026-01-05", calendar_id="XNAS", calendar_version="2026.1",
        open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100.5"),
        volume=Decimal("10"), provider_feed="iex", source_snapshot_id="s1", source_record_id="r1",
        dataset_version="v1", adjustment_mode="RAW", retrieval_run_id="run-1", quality_status="VERIFIED",
        quality_flags=["list_flag"],  # type: ignore[arg-type]
    )
    assert isinstance(base.quality_flags, tuple) and base.quality_flags == ("list_flag",)
    assert CanonicalCandle.from_json(base.to_json()) == base

    for bad_td in ("2026-01-05", datetime(2026, 1, 5, tzinfo=UTC), None):
        with pytest.raises(SchemaValidationError):
            CanonicalCandle(**{**base.__dict__, "trading_date": bad_td})  # type: ignore[arg-type]

    # 3. Tuple normalization & optional str validation on Candle, Quote, Trade
    for bad_flags in ("plain_str", [123]):
        with pytest.raises(SchemaValidationError):
            CanonicalCandle(**{**base.__dict__, "quality_flags": bad_flags})  # type: ignore[arg-type]

    q = CanonicalQuote(
        instrument_id=iid, event_time_utc=t0, received_at_utc=t0,
        bid_price=Decimal("100"), ask_price=Decimal("101"), bid_size=Decimal("1"), ask_size=Decimal("1"),
        exchange="NASDAQ", provider="alpaca", feed="iex", quality_flags=["q_flag"],  # type: ignore[arg-type]
    )
    assert isinstance(q.quality_flags, tuple) and q.quality_flags == ("q_flag",)
    assert CanonicalQuote.from_json(q.to_json()) == q
    with pytest.raises(SchemaValidationError):
        CanonicalQuote(**{**q.__dict__, "quality_flags": "bad"})  # type: ignore[arg-type]
    with pytest.raises(SchemaValidationError):
        CanonicalQuote(**{**q.__dict__, "sequence_id": 123})  # type: ignore[arg-type]
    with pytest.raises(SchemaValidationError):
        CanonicalQuote(**{**q.__dict__, "depth_json": {"bids": []}})  # type: ignore[arg-type]

    tr = CanonicalTrade(
        instrument_id=iid, trade_id="t1", event_time_utc=t0, received_at_utc=t0,
        price=Decimal("100"), quantity=Decimal("1"), exchange="NASDAQ", provider="alpaca",
        feed="iex", source_id="s1", conditions=["@"],  # type: ignore[arg-type]
    )
    assert isinstance(tr.conditions, tuple) and tr.conditions == ("@",)
    assert CanonicalTrade.from_json(tr.to_json()) == tr
    with pytest.raises(SchemaValidationError):
        CanonicalTrade(**{**tr.__dict__, "conditions": "bad"})  # type: ignore[arg-type]
    with pytest.raises(SchemaValidationError):
        CanonicalTrade(**{**tr.__dict__, "aggressor_side": 1})  # type: ignore[arg-type]
