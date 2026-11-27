"""Tests for persistent SQLite InstrumentRegistry, time-aware mappings, spec history, and underlyings."""
from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from ml_data.instruments import (
    AssetClass,
    ContractType,
    Instrument,
    InstrumentRegistry,
    InstrumentStatus,
    Market,
    ProviderInstrumentMapping,
    RegistryConflictError,
    RegistryError,
    Segment,
)
from ml_data.tests.fixtures import TS, build_all_fixtures, build_supporting_underlyings


def _register_all_with_underlyings(reg: InstrumentRegistry):
    for u in build_supporting_underlyings().values():
        reg.upsert(u)
    fixtures = build_all_fixtures()
    # Register base/index/spot first, then derivatives
    ordered = sorted(fixtures.values(), key=lambda i: 1 if i.underlying_instrument_id else 0)
    for inst in ordered:
        reg.upsert(inst)
    return fixtures


def test_idempotent_upsert_persistence_and_queries(tmp_path):
    db = str(tmp_path / "instruments.sqlite3")
    reg = InstrumentRegistry(db)
    assert reg.schema_version() == 2
    fixtures = _register_all_with_underlyings(reg)
    # Second upsert of identical data must be idempotent
    ordered = sorted(fixtures.values(), key=lambda i: 1 if i.underlying_instrument_id else 0)
    for inst in ordered:
        reg.upsert(inst)
    reg.close()

    # Reopen after restart
    reg2 = InstrumentRegistry(db)
    assert len(reg2.list_by_market(Market.US)) == 6  # 5 core + spx_idx
    assert len(reg2.list_by_market(Market.IN)) == 8
    assert len(reg2.list_by_market(Market.CRYPTO)) == 5  # 4 core + eth_spot
    assert len(reg2.list_by_asset_class(AssetClass.OPTION)) == 6
    assert len(reg2.list_by_segment(Segment.IN_INDEX_OPTIONS)) == 4
    assert len(reg2.get_options_for_underlying(fixtures["nifty_idx"].instrument_id)) == 2
    assert len(reg2.get_futures_for_underlying(fixtures["banknifty_idx"].instrument_id)) == 1
    assert len(reg2.list_by_expiry(date(2026, 12, 18))) == 3
    assert reg2.get_by_exchange_symbol("NASDAQ", "AAPL")[0].instrument_id == fixtures["aapl"].instrument_id
    reg2.close()


def test_expired_instruments_retained_even_if_underlying_inactive(tmp_path):
    db = str(tmp_path / "exp.sqlite3")
    reg = InstrumentRegistry(db)
    spx = build_supporting_underlyings()["spx_idx"]
    reg.register(spx)

    d = build_all_fixtures()["es_fut"].to_dict()
    d["instrument_status"] = InstrumentStatus.EXPIRED.value
    d["is_active"] = False
    exp_inst = Instrument.from_dict(d)
    reg.register(exp_inst)

    # Underlying becomes inactive later; historical derivative remains intact
    spx_inact = Instrument.from_dict({**spx.to_dict(), "is_active": False, "instrument_status": "INACTIVE"})
    reg.upsert(spx_inact)

    assert len(reg.list_expired()) == 1
    assert reg.get(exp_inst.instrument_id) == exp_inst
    reg.close()


def test_specification_version_history_separates_effective_from_recorded(tmp_path):
    db = str(tmp_path / "spec.sqlite3")
    reg = InstrumentRegistry(db)
    fixtures = build_all_fixtures()
    reg.upsert(fixtures["banknifty_idx"])

    # 1. Unknown initial effective date (must remain None, never fabricated from last_verified_at)
    bn_fut = fixtures["banknifty_fut"]
    reg.upsert(bn_fut)
    # Repeated identical specification update must be idempotent
    reg.upsert(bn_fut)
    hist0 = reg.get_spec_history(bn_fut.instrument_id)
    assert len(hist0) == 1
    assert hist0[0].effective_from is None
    assert hist0[0].effective_to is None

    # 2. Forward-dated spec change closes unknown initial record cleanly
    eff_2 = datetime(2026, 11, 20, 3, 45, 0, tzinfo=timezone.utc)
    d2 = bn_fut.to_dict()
    d2["lot_size"] = "35"
    d2["quantity_step"] = "35"
    d2["minimum_order_quantity"] = "35"
    d2["effective_from"] = eff_2.isoformat()
    reg.upsert(Instrument.from_dict(d2))

    # 3. Backdated historical spec discovered later (2026-11-10 < 2026-11-20)
    eff_back = datetime(2026, 11, 10, 3, 45, 0, tzinfo=timezone.utc)
    d_back = bn_fut.to_dict()
    d_back["lot_size"] = "25"
    d_back["quantity_step"] = "25"
    d_back["minimum_order_quantity"] = "25"
    d_back["effective_from"] = eff_back.isoformat()
    reg.upsert(Instrument.from_dict(d_back))

    hist = reg.get_spec_history(bn_fut.instrument_id)
    assert len(hist) == 3
    # Unknown-start initial record first, then chronological dated versions
    assert hist[0].effective_from is None and hist[0].effective_to == eff_2
    assert hist[1].effective_from == eff_back and hist[1].effective_to == eff_2
    assert hist[1].specification["lot_size"] == "25"
    assert hist[2].effective_from == eff_2 and hist[2].effective_to is None
    assert hist[2].recorded_at > eff_2
    assert hist[2].specification["lot_size"] == "35"

    # 4. Duplicate effective_from with different spec must be rejected
    d_dup = bn_fut.to_dict()
    d_dup["lot_size"] = "40"
    d_dup["quantity_step"] = "40"
    d_dup["minimum_order_quantity"] = "40"
    d_dup["effective_from"] = eff_2.isoformat()
    with pytest.raises(RegistryConflictError):
        reg.upsert(Instrument.from_dict(d_dup))
    reg.close()


def test_provider_identifier_case_normalization(tmp_path):
    db = str(tmp_path / "norm.sqlite3")
    reg = InstrumentRegistry(db)
    aapl = build_all_fixtures()["aapl"]
    spy = build_all_fixtures()["spy"]
    reg.register(aapl)
    reg.register(spy)

    m = ProviderInstrumentMapping(
        instrument_id=aapl.instrument_id,
        provider="Alpaca",
        provider_symbol="AAPL",
        provider_exchange="nasdaq",
        provider_feed="SIP",
    )
    assert m.provider == "alpaca"
    assert m.provider_exchange == "NASDAQ"
    assert m.provider_feed == "sip"
    reg.add_provider_mapping(m)

    assert reg.resolve_provider_symbol("ALPACA", "AAPL", "NASDAQ", "sip").instrument_id == aapl.instrument_id
    assert reg.resolve_provider_symbol("alpaca", "AAPL", "nasdaq", "SIP").instrument_id == aapl.instrument_id

    # Case-variant conflicting mapping must be rejected
    with pytest.raises(RegistryConflictError):
        reg.add_provider_mapping(
            ProviderInstrumentMapping(
                instrument_id=spy.instrument_id,
                provider="ALPACA",
                provider_symbol="AAPL",
                provider_exchange="NASDAQ",
                provider_feed="sip",
            )
        )
    reg.close()


def test_time_aware_provider_mappings_reuse_and_conflicts(tmp_path):
    db = str(tmp_path / "maps.sqlite3")
    reg = InstrumentRegistry(db)
    fixtures = build_all_fixtures()
    aapl = fixtures["aapl"]
    spy = fixtures["spy"]
    reg.register(aapl)
    reg.register(spy)

    t1 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    # Historical mapping for "OLD_SYM" -> AAPL [2024, 2025), then reused by SPY [2025, inf)
    m_old = ProviderInstrumentMapping(
        instrument_id=aapl.instrument_id,
        provider="alpaca",
        provider_symbol="OLD_SYM",
        provider_exchange="NASDAQ",
        provider_feed="sip",
        valid_from=t1,
        valid_until=t2,
    )
    m_new = ProviderInstrumentMapping(
        instrument_id=spy.instrument_id,
        provider="alpaca",
        provider_symbol="OLD_SYM",
        provider_exchange="NASDAQ",
        provider_feed="sip",
        valid_from=t2,
        valid_until=None,
    )
    # Multiple feeds on same canonical instrument
    m_iex = ProviderInstrumentMapping(
        instrument_id=aapl.instrument_id,
        provider="alpaca",
        provider_symbol="AAPL",
        provider_exchange="NASDAQ",
        provider_feed="iex",
        valid_from=t1,
    )
    m_sip = ProviderInstrumentMapping(
        instrument_id=aapl.instrument_id,
        provider="alpaca",
        provider_symbol="AAPL",
        provider_exchange="NASDAQ",
        provider_feed="sip",
        valid_from=t1,
    )
    reg.add_provider_mapping(m_old)
    reg.add_provider_mapping(m_new)
    reg.add_provider_mapping(m_iex)
    reg.add_provider_mapping(m_sip)

    # Historical resolution
    assert reg.resolve_provider_symbol("alpaca", "OLD_SYM", "NASDAQ", "sip", as_of=datetime(2024, 6, 1, tzinfo=timezone.utc)).instrument_id == aapl.instrument_id
    # Current resolution (after 2025)
    assert reg.resolve_provider_symbol("alpaca", "OLD_SYM", "NASDAQ", "sip", as_of=t3).instrument_id == spy.instrument_id
    # Expired mapping rejected when no replacement exists
    m_exp = ProviderInstrumentMapping(
        instrument_id=aapl.instrument_id,
        provider="polygon",
        provider_symbol="AAPL_OLD",
        provider_exchange="XNAS",
        valid_from=t1,
        valid_until=t2,
    )
    reg.add_provider_mapping(m_exp)
    assert reg.resolve_provider_symbol("polygon", "AAPL_OLD", "XNAS", as_of=t3) is None

    # Overlapping conflict rejected
    overlap = ProviderInstrumentMapping(
        instrument_id=spy.instrument_id,
        provider="alpaca",
        provider_symbol="AAPL",
        provider_exchange="NASDAQ",
        provider_feed="iex",
        valid_from=t2,
    )
    with pytest.raises(RegistryConflictError):
        reg.add_provider_mapping(overlap)
    reg.close()


def test_underlying_relationship_enforced_in_registry(tmp_path):
    db = str(tmp_path / "und.sqlite3")
    reg = InstrumentRegistry(db)
    fixtures = build_all_fixtures()

    # Missing underlying rejected
    with pytest.raises(RegistryError):
        reg.register(fixtures["aapl_call"])

    # Wrong market/asset_class underlying rejected (e.g. CRYPTO spot cannot be US option underlying)
    reg.register(fixtures["btc_spot"])
    bad_opt = Instrument(
        instrument_id="",
        market=Market.US,
        asset_class=AssetClass.OPTION,
        segment=Segment.US_OPTIONS,
        exchange="OPRA",
        canonical_symbol="BTC261218C00100000",
        trading_symbol="BTC261218C00100000",
        display_name="Invalid Cross-Market Option",
        underlying_instrument_id=fixtures["btc_spot"].instrument_id,
        price_currency="USD",
        expiry_date=date(2026, 12, 18),
        strike_price=Decimal("100"),
        option_right="CALL",
        contract_multiplier=Decimal("100"),
        contract_type=ContractType.OPTION,
    )
    with pytest.raises(RegistryConflictError):
        reg.register(bad_opt)
    reg.close()


def test_concurrent_reads_and_writes_and_json_export_import(tmp_path):
    db = str(tmp_path / "conc.sqlite3")
    reg = InstrumentRegistry(db)
    for u in build_supporting_underlyings().values():
        reg.upsert(u)
    items = sorted(build_all_fixtures().values(), key=lambda i: 1 if i.underlying_instrument_id else 0)
    # Register non-derivatives first so concurrent derivative inserts have valid underlyings
    base_items = [i for i in items if not i.underlying_instrument_id]
    deriv_items = [i for i in items if i.underlying_instrument_id]
    for b in base_items:
        reg.upsert(b)

    errors = []

    def _writer(sub):
        try:
            for inst in sub:
                reg.upsert(inst)
        except Exception as e:
            errors.append(e)

    def _reader():
        try:
            for _ in range(10):
                _ = reg.list_active()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=_writer, args=(deriv_items[:5],)),
        threading.Thread(target=_writer, args=(deriv_items[5:],)),
        threading.Thread(target=_reader),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    exported = reg.export_json()
    reg2 = InstrumentRegistry(str(tmp_path / "reimport.sqlite3"))
    count = reg2.import_json(exported)
    assert count == 19
    assert reg2.export_json() == exported
    reg.close()
    reg2.close()
