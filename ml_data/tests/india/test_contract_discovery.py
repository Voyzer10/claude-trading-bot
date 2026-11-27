"""Tests for exact NIFTY/BANKNIFTY contract discovery, Identity v3, and IndiaKiteAdapter."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

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
