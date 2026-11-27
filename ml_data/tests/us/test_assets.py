"""Tests for AlpacaAssetsDiscovery: equities/ETFs, active/inactive, non-tradable retention, snapshots, Identity v3."""
from __future__ import annotations

from datetime import date

from ml_data.instruments import AssetClass, InstrumentRegistry, InstrumentStatus, Market
from ml_data.us import AlpacaAssetsDiscovery, AlpacaDataClient, diff_asset_snapshots
from ml_data.tests.us.fixtures import FakeAlpacaTransport, TEST_CRED


def test_assets_discovery_snapshots_diff_and_registry(tmp_path):
    tr = FakeAlpacaTransport()
    client = AlpacaDataClient(credential=TEST_CRED, transport=tr)
    disc = AlpacaAssetsDiscovery(
        client=client,
        raw_root=str(tmp_path / "raw"),
        manifest_root=str(tmp_path / "manifests"),
    )
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))

    d0 = date(2026, 11, 27)
    snap = disc.download_snapshot(snap_date=d0)
    rep = disc.discover(snapshot=snap, registry=reg)

    # 3 equities (AAPL, MSFT, BRK.A + OLDCO inactive = 4) and 1 ETF (SPY)
    assert len(rep.equities) == 4
    assert len(rep.etfs) == 1
    assert rep.etfs[0].asset_class == AssetClass.ETF
    assert rep.etfs[0].metadata["options_late_close"] is True

    # Non-tradable BRK.A retained for data availability, but availability is UNVERIFIED until feed-tested
    brka = next(e for e in rep.equities if e.canonical_symbol == "BRK.A")
    assert brka.is_tradable is False
    assert brka.metadata["in_alpaca_asset_master"] is True
    assert brka.metadata["data_availability"] == "UNVERIFIED"
    assert rep.etfs[0].metadata["etf_classification_source"] == "alpaca_attribute"
    assert rep.etfs[0].metadata["etf_classification_verified"] is True

    # Feed-neutral mapping
    assert all(m.provider_feed is None for m in rep.mappings)

    # Inactive OLDCO retained
    oldco = next(e for e in rep.equities if e.canonical_symbol == "OLDCO")
    assert oldco.instrument_status == InstrumentStatus.INACTIVE
    assert oldco.is_active is False

    # Identity v3 & registry persistence
    for inst in rep.equities + rep.etfs:
        assert inst.market == Market.US
        assert inst.identity_version == "v3"
        assert reg.get(inst.instrument_id) is not None

    # Snapshot diff
    modified = [dict(x) for x in snap.raw_assets]
    modified[0]["tradable"] = False
    diff = diff_asset_snapshots(snap.raw_assets, modified)
    assert diff["changed"][0]["symbol"] == "AAPL"
    reg.close()


def test_txse_and_unknown_exchange_mapping(tmp_path):
    from ml_data.us.assets import AssetSnapshot
    from datetime import datetime, timezone

    disc = AlpacaAssetsDiscovery(raw_root=str(tmp_path / "r"), manifest_root=str(tmp_path / "m"))
    snap = AssetSnapshot(
        snapshot_date=date(2026, 11, 27),
        retrieved_at_utc=datetime.now(timezone.utc),
        sha256="abc",
        raw_count=2,
        raw_gz_path="",
        manifest_path="",
        raw_assets=(
            {"id": "tx1", "symbol": "TXCO", "name": "Texas Corp", "exchange": "TXSE", "status": "active", "tradable": True},
            {"id": "un1", "symbol": "UNCO", "name": "Unknown Ex Corp", "exchange": "MYSTERY_EX", "status": "active", "tradable": False},
        ),
    )
    rep = disc.discover(snapshot=snap, dry_run=True)
    txco = next(e for e in rep.equities if e.canonical_symbol == "TXCO")
    unco = next(e for e in rep.equities if e.canonical_symbol == "UNCO")
    assert txco.exchange_mic == "TXSE" and txco.trading_calendar == "TXSE" and txco.metadata["exchange_verified"] is True
    assert unco.exchange == "MYSTERY_EX" and unco.exchange_mic is None and unco.trading_calendar == "UNKNOWN"
    assert unco.metadata["exchange_verified"] is False
