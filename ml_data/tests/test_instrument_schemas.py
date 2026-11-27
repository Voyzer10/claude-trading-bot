"""Tests for Universal Instrument Schema, Decimal precision, normalization, and ID validation."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ml_data.instruments import (
    AssetClass,
    ContractType,
    Instrument,
    InstrumentValidationError,
    Market,
    Segment,
)
from ml_data.tests.fixtures import build_all_fixtures


def test_all_17_synthetic_fixtures_create_and_roundtrip_json():
    fixtures = build_all_fixtures()
    assert len(fixtures) == 17
    for key, inst in fixtures.items():
        payload = inst.to_json()
        restored = Instrument.from_json(payload)
        assert restored == inst, f"round-trip mismatch for {key}"
        assert restored.to_json() == payload


def test_decimal_precision_never_uses_float():
    fixtures = build_all_fixtures()
    btc = fixtures["btc_spot"]
    assert isinstance(btc.tick_size, Decimal)
    assert isinstance(btc.quantity_step, Decimal)
    assert btc.quantity_step == Decimal("0.00001")

    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict({**fixtures["aapl"].to_dict(), "tick_size": 0.01})
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict({**fixtures["aapl_call"].to_dict(), "strike_price": 220.5})


def test_timezone_aware_timestamps_required_and_normalized_to_utc():
    d = build_all_fixtures()["aapl"].to_dict()
    d["last_verified_at"] = datetime(2026, 11, 27, 9, 0, 0).isoformat()  # naive
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d)

    # Direct construction with IST (+05:30) must normalize to UTC
    ist = timezone(timedelta(hours=5, minutes=30))
    inst = Instrument(
        instrument_id="",
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        segment=Segment.US_EQUITY,
        exchange="NASDAQ",
        canonical_symbol="MSFT",
        trading_symbol="MSFT",
        display_name="Microsoft Corp.",
        price_currency="USD",
        contract_type=ContractType.EQUITY,
        last_verified_at=datetime(2026, 11, 27, 14, 30, 0, tzinfo=ist),
    )
    assert inst.last_verified_at.tzinfo == timezone.utc
    assert inst.last_verified_at.hour == 9


def test_expiry_date_uses_date_object():
    aapl_call = build_all_fixtures()["aapl_call"]
    assert isinstance(aapl_call.expiry_date, date)
    assert not isinstance(aapl_call.expiry_date, datetime)


def test_supplied_inconsistent_instrument_id_rejected():
    d = build_all_fixtures()["aapl"].to_dict()
    d["instrument_id"] = "US:NASDAQ:EQUITY:ARBITRARY_FAKE_ID"
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d)


def test_metadata_is_immutable_and_booleans_strictly_checked():
    inst = build_all_fixtures()["aapl"]
    with pytest.raises(TypeError):
        inst.metadata["injected"] = True  # type: ignore[index]

    d = inst.to_dict()
    d["is_active"] = "yes"
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d)


def test_invalid_currency_rejected():
    d = build_all_fixtures()["aapl"].to_dict()
    d["price_currency"] = "usd"
    with pytest.raises(InstrumentValidationError):
        Instrument.from_dict(d)


def test_identity_version_validated_and_128bit_digest():
    aapl = build_all_fixtures()["aapl"]
    assert aapl.identity_version == "v3"
    prefix, digest = aapl.instrument_id.split("#")
    assert len(digest) == 32  # 128-bit hex digest

    for old_ver in ("v1", "v2"):
        d = aapl.to_dict()
        d["identity_version"] = old_ver
        with pytest.raises(InstrumentValidationError):
            Instrument.from_dict(d)
