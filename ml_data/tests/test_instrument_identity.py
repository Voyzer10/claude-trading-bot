"""Tests for deterministic canonical instrument identity (v2)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ml_data.instruments import (
    AssetClass,
    ContractType,
    IDENTITY_VERSION,
    Instrument,
    Market,
    OptionRight,
    Segment,
    build_instrument_id,
)
from ml_data.tests.fixtures import build_all_fixtures


def test_same_contract_across_providers_maps_to_same_id():
    id_alpaca = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol="AAPL261218C00220000",
        underlying_instrument_id="US:NASDAQ:EQUITY:AAPL#abc123",
        expiry_date=date(2026, 12, 18),
        strike_price=Decimal("220.00"),
        option_right=OptionRight.CALL,
        deliverable_shares=Decimal("100"),
        deliverable_type="STANDARD",
    )
    id_other = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol=" aapl261218c00220000 ",
        underlying_instrument_id="US:NASDAQ:EQUITY:AAPL#abc123",
        expiry_date=date(2026, 12, 18),
        strike_price=Decimal("220"),
        option_right="C",
        deliverable_shares=Decimal("100"),
        deliverable_type="STANDARD",
    )
    assert id_alpaca == id_other
    assert len(id_alpaca.split("#")[1]) == 32


def test_adjusted_options_same_strike_expiry_right_do_not_collide():
    adj1 = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol="AAPL1261218C00220000",
        underlying_instrument_id="US:NASDAQ:EQUITY:AAPL#abc123",
        expiry_date=date(2026, 12, 18),
        strike_price=Decimal("220"),
        option_right=OptionRight.CALL,
        deliverable_shares=Decimal("100"),
        deliverable_type="ADJUSTED_CASH_1",
    )
    adj2 = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol="AAPL2261218C00220000",
        underlying_instrument_id="US:NASDAQ:EQUITY:AAPL#abc123",
        expiry_date=date(2026, 12, 18),
        strike_price=Decimal("220"),
        option_right=OptionRight.CALL,
        deliverable_shares=Decimal("100"),
        deliverable_type="ADJUSTED_CASH_2",
    )
    assert adj1 != adj2


def test_execution_venue_never_overrides_listing_exchange():
    i1 = Instrument(
        instrument_id="",
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        segment=Segment.US_EQUITY,
        exchange="NASDAQ",
        venue="IEX",
        canonical_symbol="AAPL",
        trading_symbol="AAPL",
        display_name="Apple Inc.",
        price_currency="USD",
        contract_type=ContractType.EQUITY,
    )
    i2 = Instrument(
        instrument_id="",
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        segment=Segment.US_EQUITY,
        exchange="NASDAQ",
        venue="ARCA",
        canonical_symbol="AAPL",
        trading_symbol="AAPL",
        display_name="Apple Inc.",
        price_currency="USD",
        contract_type=ContractType.EQUITY,
    )
    assert i1.instrument_id == i2.instrument_id
    assert i1.identity_version == IDENTITY_VERSION


def test_different_exchanges_do_not_collide():
    id_binance = build_instrument_id(
        market=Market.CRYPTO,
        asset_class=AssetClass.CRYPTO_SPOT,
        exchange="BINANCE",
        canonical_symbol="BTC/USDT",
        base_currency="BTC",
        quote_currency="USDT",
    )
    id_coinbase = build_instrument_id(
        market=Market.CRYPTO,
        asset_class=AssetClass.CRYPTO_SPOT,
        exchange="COINBASE",
        canonical_symbol="BTC/USDT",
        base_currency="BTC",
        quote_currency="USDT",
    )
    id_nasdaq = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        exchange="NASDAQ",
        canonical_symbol="ABC",
    )
    id_nyse = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        exchange="NYSE",
        canonical_symbol="ABC",
    )
    assert id_binance != id_coinbase
    assert id_nasdaq != id_nyse


def test_same_ticker_different_underlying_and_deliverables_distinct():
    std_opt = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol="XYZ261218C00100000",
        underlying_instrument_id="US:NYSE:EQUITY:XYZ#111",
        expiry_date=date(2026, 12, 18),
        strike_price=Decimal("100"),
        option_right=OptionRight.CALL,
        deliverable_shares=Decimal("100"),
        deliverable_type="STANDARD",
    )
    adj_opt = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol="XYZ261218C00100000",
        underlying_instrument_id="US:NYSE:EQUITY:XYZ#111",
        expiry_date=date(2026, 12, 18),
        strike_price=Decimal("100"),
        option_right=OptionRight.CALL,
        deliverable_shares=Decimal("50"),
        deliverable_type="ADJUSTED",
    )
    other_und = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange="OPRA",
        canonical_symbol="XYZ261218C00100000",
        underlying_instrument_id="US:NASDAQ:EQUITY:XYZ#222",
        expiry_date=date(2026, 12, 18),
        strike_price=Decimal("100"),
        option_right=OptionRight.CALL,
        deliverable_shares=Decimal("100"),
        deliverable_type="STANDARD",
    )
    assert std_opt != adj_opt
    assert std_opt != other_und


def test_different_options_produce_distinct_ids():
    fixtures = build_all_fixtures()
    assert fixtures["nifty_ce"].instrument_id != fixtures["nifty_pe"].instrument_id
    assert fixtures["bn_ce"].instrument_id != fixtures["bn_pe"].instrument_id


def test_crypto_linear_vs_inverse_and_settlement_currencies_distinct():
    lin = build_instrument_id(
        market=Market.CRYPTO,
        asset_class=AssetClass.CRYPTO_PERPETUAL,
        exchange="BINANCE",
        canonical_symbol="BTCUSDT",
        base_currency="BTC",
        quote_currency="USDT",
        settlement_currency="USDT",
        contract_multiplier=Decimal("1"),
        is_inverse=False,
    )
    lin_alt_prod = build_instrument_id(
        market=Market.CRYPTO,
        asset_class=AssetClass.CRYPTO_PERPETUAL,
        exchange="BINANCE",
        canonical_symbol="BTCUSDT_1000X",
        base_currency="BTC",
        quote_currency="USDT",
        settlement_currency="USDT",
        contract_multiplier=Decimal("1000"),
        is_inverse=False,
    )
    inv = build_instrument_id(
        market=Market.CRYPTO,
        asset_class=AssetClass.CRYPTO_PERPETUAL,
        exchange="BINANCE",
        canonical_symbol="BTCUSD",
        base_currency="BTC",
        quote_currency="USD",
        settlement_currency="BTC",
        contract_multiplier=Decimal("1"),
        is_inverse=True,
    )
    usdc = build_instrument_id(
        market=Market.CRYPTO,
        asset_class=AssetClass.CRYPTO_PERPETUAL,
        exchange="BINANCE",
        canonical_symbol="BTCUSDC",
        base_currency="BTC",
        quote_currency="USDC",
        settlement_currency="USDC",
        contract_multiplier=Decimal("1"),
        is_inverse=False,
    )
    assert len({lin, lin_alt_prod, inv, usdc}) == 4


def test_symbol_normalization_matches():
    a = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        exchange="nasdaq",
        canonical_symbol=" aapl ",
    )
    b = build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        exchange="NASDAQ",
        canonical_symbol="AAPL",
    )
    assert a == b
