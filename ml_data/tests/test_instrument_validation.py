"""Tests for category-specific instrument validation and compatibility matrix."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ml_data.instruments import (
    AssetClass,
    ContractType,
    Instrument,
    InstrumentStatus,
    InstrumentValidationError,
    Market,
    OptionRight,
    Segment,
)
from ml_data.tests.fixtures import build_all_fixtures


def test_equity_cannot_have_expiry_or_strike():
    d = build_all_fixtures()["aapl"].to_dict()
    d["expiry_date"] = "2026-12-18"
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d)


def test_index_is_not_tradable():
    d = build_all_fixtures()["nifty_idx"].to_dict()
    d["is_tradable"] = True
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d)


@pytest.mark.parametrize(
    "market,segment,asset_class",
    [
        (Market.US, Segment.US_EQUITY, AssetClass.OPTION),
        (Market.US, Segment.US_OPTIONS, AssetClass.EQUITY),
        (Market.US, Segment.IN_INDEX, AssetClass.INDEX),
        (Market.IN, Segment.IN_INDEX, AssetClass.EQUITY),
        (Market.IN, Segment.US_EQUITY, AssetClass.EQUITY),
        (Market.CRYPTO, Segment.CRYPTO_SPOT, AssetClass.CRYPTO_PERPETUAL),
        (Market.CRYPTO, Segment.CRYPTO_PERPETUALS, AssetClass.CRYPTO_FUTURE),
    ],
)
def test_invalid_market_segment_asset_class_combinations_rejected(market, segment, asset_class):
    with pytest.raises(InstrumentValidationError):
        Instrument(
            instrument_id="",
            market=market,
            asset_class=asset_class,
            segment=segment,
            exchange="TEST",
            canonical_symbol="TEST",
            trading_symbol="TEST",
            display_name="Invalid Combo",
            price_currency="USD",
        )


@pytest.mark.parametrize("bad_symbol", ["NIFTYIT", "FINNIFTY", "NIFTYMIDCAP", "BANKNIFTYJR", "RELIANCE"])
def test_indian_substring_and_non_nifty_banknifty_rejected(bad_symbol):
    with pytest.raises(InstrumentValidationError):
        Instrument(
            instrument_id="",
            market=Market.IN,
            asset_class=AssetClass.INDEX,
            segment=Segment.IN_INDEX,
            exchange="NSE",
            canonical_symbol=bad_symbol,
            trading_symbol=bad_symbol,
            display_name=bad_symbol,
            price_currency="INR",
            is_tradable=False,
        )


def test_indian_stock_fno_rejected_outside_scope():
    with pytest.raises(InstrumentValidationError):
        Instrument(
            instrument_id="",
            market=Market.IN,
            asset_class=AssetClass.OPTION,
            segment=Segment.IN_INDEX_OPTIONS,
            exchange="NFO",
            canonical_symbol="RELIANCE26DEC1400CE",
            trading_symbol="RELIANCE26DEC1400CE",
            display_name="Reliance Option",
            underlying_instrument_id="IN:NSE:EQUITY:RELIANCE",
            price_currency="INR",
            expiry_date=date(2026, 12, 31),
            strike_price=Decimal("1400"),
            option_right=OptionRight.CALL,
            contract_multiplier=Decimal("1"),
            lot_size=Decimal("500"),
            tick_size=Decimal("0.05"),
        )


def test_contract_type_mismatch_rejected():
    d = build_all_fixtures()["aapl"].to_dict()
    d["contract_type"] = ContractType.PERPETUAL.value
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d)


def test_option_requires_underlying_strike_expiry_right():
    d = build_all_fixtures()["aapl_call"].to_dict()
    d["underlying_instrument_id"] = None
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d)

    d2 = build_all_fixtures()["aapl_call"].to_dict()
    d2["strike_price"] = "-5"
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d2)


def test_perpetual_forbids_expiry_and_dated_future_requires_expiry():
    d_perp = build_all_fixtures()["btc_perp"].to_dict()
    d_perp["expiry_date"] = "2026-12-25"
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d_perp)

    d_fut = build_all_fixtures()["btc_fut"].to_dict()
    d_fut["expiry_date"] = None
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d_fut)


def test_expired_instrument_cannot_be_active():
    d = build_all_fixtures()["es_fut"].to_dict()
    d["instrument_status"] = InstrumentStatus.EXPIRED.value
    d["is_active"] = True
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d)
