"""Tests for exact NIFTY/BANKNIFTY contract discovery, Identity v3, and IndiaKiteAdapter."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ml_data.adapters.india_kite import IndiaKiteAdapter
from ml_data.india import (
    ContractDiscovery,
    InstrumentMasterDownloader,
    KiteClientWrapper,
    parse_kite_nfo_symbol,
)
from ml_data.instruments import AssetClass, InstrumentRegistry, Market, OptionRight
from ml_data.tests.india.fixtures import FakeKiteSDK


def test_exact_root_symbol_parser_rejects_lookalikes_and_stock_fno():
    assert parse_kite_nfo_symbol("NIFTY26DECFUT", "NIFTY", "FUT").root == "NIFTY"
    assert parse_kite_nfo_symbol("BANKNIFTY26DEC52500PE", "BANKNIFTY", "PE").strike == Decimal("52500")
    assert parse_kite_nfo_symbol("FINNIFTY26DECFUT", "FINNIFTY", "FUT") is None
    assert parse_kite_nfo_symbol("NIFTYIT26DECFUT", "NIFTYIT", "FUT") is None
    assert parse_kite_nfo_symbol("RELIANCE26DEC1400CE", "RELIANCE", "CE") is None


def test_contract_discovery_registers_nifty_and_banknifty_with_decimal_and_identity_v3(tmp_path):
    sdk = FakeKiteSDK()
    client = KiteClientWrapper(kite_client=sdk)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "master"))
    d0 = date(2026, 11, 27)
    nse_snap = dl.download_snapshot("NSE", snap_date=d0)
    nfo_snap = dl.download_snapshot("NFO", snap_date=d0)

    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    rep = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse_snap, nfo_snapshot=nfo_snap, registry=reg)

    assert len(rep.indices) == 2
    assert rep.nifty_counts == {"futures": 1, "ce": 1, "pe": 1}
    assert rep.banknifty_counts == {"futures": 1, "ce": 1, "pe": 1}
    assert any(r["tradingsymbol"] == "NIFTYIT26DECFUT" for r in rep.rejected)
    assert all(r.trading_symbol != "RELIANCE26DEC1400CE" for r in rep.futures + rep.options)

    opts = reg.list_by_asset_class(AssetClass.OPTION)
    assert len(opts) == 4
    for o in opts:
        assert isinstance(o.strike_price, Decimal)
        assert isinstance(o.lot_size, Decimal)
        assert isinstance(o.tick_size, Decimal)
        assert o.market == Market.IN
        assert o.identity_version == "v3"
    reg.close()


def test_india_kite_adapter_interface(tmp_path):
    sdk = FakeKiteSDK()
    client = KiteClientWrapper(kite_client=sdk)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "master"))
    adapter = IndiaKiteAdapter(client=client, downloader=dl)

    assert adapter.fetch_equities() == []
    assert len(adapter.fetch_indices()) == 2
    assert len(adapter.fetch_futures("NIFTY")) == 1
    assert len(adapter.fetch_options("BANKNIFTY")) == 2
    assert adapter.fetch_options("FINNIFTY") == []


def test_nse_index_uses_nse_snapshot_provenance_not_nfo(tmp_path):
    sdk = FakeKiteSDK()
    client = KiteClientWrapper(kite_client=sdk)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "master"))
    d_nse = date(2026, 11, 26)
    d_nfo = date(2026, 11, 27)
    nse_snap = dl.download_snapshot("NSE", snap_date=d_nse)
    nfo_snap = dl.download_snapshot("NFO", snap_date=d_nfo)

    rep = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse_snap, nfo_snapshot=nfo_snap)
    for idx in rep.indices:
        assert idx.metadata["snapshot_date"] == "2026-11-26"
        assert idx.metadata["snapshot_sha256"] == nse_snap.sha256
        assert "@2026-11-26" in idx.provider_instrument_id
    for fut in rep.futures:
        assert fut.metadata["snapshot_date"] == "2026-11-27"
        assert fut.metadata["snapshot_sha256"] == nfo_snap.sha256


def test_india_kite_adapter_daily_cache_invalidation_and_refresh(tmp_path):
    from ml_data.tests.india.fixtures import NFO_CSV

    sdk = FakeKiteSDK()
    client = KiteClientWrapper(kite_client=sdk)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "master"))
    adapter = IndiaKiteAdapter(client=client, downloader=dl)

    d1 = date(2026, 11, 27)
    rep1 = adapter.discover(snap_date=d1, dry_run=False)
    assert len(rep1.options) == 4
    calls_after_d1 = len(sdk.calls)

    # Same-day repeated discover uses in-memory cache without re-hitting downloader/SDK
    rep1_cached = adapter.discover(snap_date=d1, dry_run=False)
    assert rep1_cached is rep1
    assert len(sdk.calls) == calls_after_d1

    # Consecutive trading date invalidates cache and loads new day's contracts
    sdk.nfo_csv = NFO_CSV + "100010,399,NIFTY26D1024600CE,NIFTY,120.0,2026-12-10,24600,0.05,75,CE,NFO-OPT,NFO\n"
    d2 = date(2026, 11, 28)
    rep2 = adapter.discover(snap_date=d2, dry_run=False)
    assert rep2.snapshot_date == d2
    assert len(rep2.options) == 5

    # Explicit manual refresh on same date picks up updated CSV
    sdk.nfo_csv = sdk.nfo_csv + "100011,400,NIFTY26D1024600PE,NIFTY,110.0,2026-12-10,24600,0.05,75,PE,NFO-OPT,NFO\n"
    rep2_refreshed = adapter.discover(snap_date=d2, dry_run=False, refresh=True)
    assert len(rep2_refreshed.options) == 6


def test_contract_lifecycle_reassignment_expiry_missing_and_historical_resolution(tmp_path):
    from datetime import datetime
    from ml_data.india import KiteHistoricalDataClient, NSECalendar
    from ml_data.india.config import IST_TZ
    from ml_data.instruments import InstrumentStatus
    from ml_data.tests.india.fixtures import NSE_CSV

    d1 = date(2026, 11, 27)
    d2 = date(2026, 11, 28)
    d_after_exp = date(2026, 12, 4)

    # Snapshot Day 1: NIFTY26D0324500CE (token 100003, exp 2026-12-03) and NIFTY26DEC25000CE (token 100004, exp 2026-12-31)
    nfo_d1 = (
        "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
        "100001,390,NIFTY26DECFUT,NIFTY,24600.0,2026-12-31,0,0.05,75,FUT,NFO-FUT,NFO\n"
        "100003,392,NIFTY26D0324500CE,NIFTY,180.5,2026-12-03,24500,0.05,75,CE,NFO-OPT,NFO\n"
        "100004,393,NIFTY26DEC25000CE,NIFTY,165.0,2026-12-31,25000,0.05,75,CE,NFO-OPT,NFO\n"
    )
    sdk = FakeKiteSDK(nse_csv=NSE_CSV, nfo_csv=nfo_d1)
    client = KiteClientWrapper(kite_client=sdk, sleeper=lambda _: None)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "master"))
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))

    nse1 = dl.download_snapshot("NSE", snap_date=d1)
    nfo1 = dl.download_snapshot("NFO", snap_date=d1)
    rep1 = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse1, nfo_snapshot=nfo1, registry=reg)
    opt_dec03 = next(o for o in rep1.options if o.canonical_symbol == "NIFTY26D0324500CE")
    opt_dec31 = next(o for o in rep1.options if o.canonical_symbol == "NIFTY26DEC25000CE")

    # 1. Consecutive snapshot with same contract & token is idempotent (no duplicate mapping created)
    nfo1_repeat = dl.download_snapshot("NFO", snap_date=d1, force_refresh=True)
    ContractDiscovery().discover_from_snapshots(nse_snapshot=nse1, nfo_snapshot=nfo1_repeat, registry=reg)
    assert len(reg.get_provider_mappings(opt_dec03.instrument_id)) == 1

    # 2. Day 2 (2026-11-28, BEFORE Dec 31 expiry): NIFTY26DEC25000CE temporarily absent from snapshot
    # Mere absence MUST NOT mark it EXPIRED (remains TEMPORARILY_MISSING / UNKNOWN)!
    sdk.nfo_csv = (
        "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
        "100001,390,NIFTY26DECFUT,NIFTY,24600.0,2026-12-31,0,0.05,75,FUT,NFO-FUT,NFO\n"
        "100003,392,NIFTY26D0324500CE,NIFTY,180.5,2026-12-03,24500,0.05,75,CE,NFO-OPT,NFO\n"
    )
    nse2 = dl.download_snapshot("NSE", snap_date=d2)
    nfo2 = dl.download_snapshot("NFO", snap_date=d2)
    rep2 = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse2, nfo_snapshot=nfo2, registry=reg)
    assert opt_dec31.instrument_id in rep2.temporarily_missing
    missing_rec = reg.get(opt_dec31.instrument_id)
    assert missing_rec.instrument_status == InstrumentStatus.UNKNOWN
    assert missing_rec.metadata["lifecycle_state"] == "TEMPORARILY_MISSING"
    assert missing_rec.is_active is False

    # 3. Day after 2026-12-03 expiry (2026-12-04):
    # - NIFTY26D0324500CE (exp 2026-12-03 < 2026-12-04) is marked EXPIRED and its mapping closed.
    # - Kite REASSIGNS recycled token 100003 to a brand-new contract NIFTY26D1024600CE!
    # - NIFTY26DEC25000CE reappears cleanly as ACTIVE with canonical ID preserved.
    sdk.nfo_csv = (
        "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
        "100001,390,NIFTY26DECFUT,NIFTY,24600.0,2026-12-31,0,0.05,75,FUT,NFO-FUT,NFO\n"
        "100003,395,NIFTY26D1024600CE,NIFTY,140.0,2026-12-10,24600,0.05,75,CE,NFO-OPT,NFO\n"
        "100004,393,NIFTY26DEC25000CE,NIFTY,170.0,2026-12-31,25000,0.05,75,CE,NFO-OPT,NFO\n"
    )
    nse3 = dl.download_snapshot("NSE", snap_date=d_after_exp)
    nfo3 = dl.download_snapshot("NFO", snap_date=d_after_exp)
    rep3 = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse3, nfo_snapshot=nfo3, registry=reg)

    opt_dec10 = next(o for o in rep3.options if o.canonical_symbol == "NIFTY26D1024600CE")
    assert opt_dec03.instrument_id in rep3.expired
    assert reg.get(opt_dec03.instrument_id).instrument_status == InstrumentStatus.EXPIRED
    assert reg.get(opt_dec31.instrument_id).instrument_status == InstrumentStatus.ACTIVE
    assert opt_dec03.instrument_id != opt_dec10.instrument_id

    # Temporal [valid_from, valid_until) resolution: token 100003 resolves to OLD contract on Nov 27 and NEW contract on Dec 4
    t_old = datetime(2026, 11, 27, 10, 0, tzinfo=IST_TZ)
    t_new = datetime(2026, 12, 4, 10, 0, tzinfo=IST_TZ)
    assert reg.resolve_provider_instrument_id("kite", "100003", "NFO", as_of=t_old).instrument_id == opt_dec03.instrument_id
    assert reg.resolve_provider_instrument_id("kite", "100003", "NFO", as_of=t_new).instrument_id == opt_dec10.instrument_id

    # Historical client uses date-scoped mapping: Nov 27 fetch on opt_dec03 succeeds via its historical mapping,
    # whereas querying Dec 4+ on opt_dec03 (after mapping valid_until) refuses instead of hitting reassigned token!
    sdk.candles_by_token[(100003, "5minute")] = [
        ["2026-11-27T09:15:00+0530", 180.0, 182.0, 179.0, 181.0, 1000, 50000],
    ]
    hist = KiteHistoricalDataClient(client=client, registry=reg, calendar=NSECalendar.official())
    r_old = hist.fetch_historical_candles(
        opt_dec03.instrument_id, "5minute",
        datetime(2026, 11, 27, 9, 15, tzinfo=IST_TZ),
        datetime(2026, 11, 27, 9, 20, tzinfo=IST_TZ),
    )
    assert len(r_old.candles) == 1
    from ml_data.india import KiteInputError
    with pytest.raises(KiteInputError):
        hist.fetch_historical_candles(
            opt_dec03.instrument_id, "5minute",
            datetime(2026, 12, 4, 9, 15, tzinfo=IST_TZ),
            datetime(2026, 12, 4, 9, 20, tzinfo=IST_TZ),
        )
    reg.close()
