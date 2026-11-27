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


def test_assets_immutable_snapshot_provenance_revisions_and_recovery(monkeypatch, tmp_path):
    import gzip
    import hashlib
    import json
    import os
    import pytest
    from ml_data.us import AlpacaAdapterError, AlpacaHTTPResponse
    from ml_data.tests.us.fixtures import ACTIVE_EQUITIES, INACTIVE_EQUITIES

    state = {"active": [dict(x) for x in ACTIVE_EQUITIES], "inactive": [dict(x) for x in INACTIVE_EQUITIES]}

    def _tr(method, url, headers, params, timeout):
        if (params or {}).get("status") == "inactive":
            return AlpacaHTTPResponse(200, state["inactive"], {})
        return AlpacaHTTPResponse(200, state["active"], {})

    client = AlpacaDataClient(credential=TEST_CRED, transport=_tr)
    disc = AlpacaAssetsDiscovery(
        client=client,
        raw_root=str(tmp_path / "raw"),
        manifest_root=str(tmp_path / "manifests"),
    )
    d0 = date(2026, 11, 27)

    # 1. Initial snapshot + SHA/file/manifest consistency + separate retrieved_at_utc
    s1 = disc.download_snapshot(snap_date=d0)
    assert s1.revision == 1
    assert os.path.isfile(s1.raw_gz_path) and os.path.isfile(s1.manifest_path)
    with gzip.open(s1.raw_gz_path, "rt", encoding="utf-8") as fh:
        assert hashlib.sha256(fh.read().encode("utf-8")).hexdigest() == s1.sha256
    with open(s1.manifest_path, encoding="utf-8") as fh:
        m1 = json.load(fh)
    assert m1["sha256"] == s1.sha256
    assert m1["snapshot_file"] == os.path.basename(s1.raw_gz_path)
    assert m1["snapshot_date"] == d0.isoformat()
    assert m1["retrieved_at_utc"] == s1.retrieved_at_utc.isoformat()

    # 2. Repeated identical retrieval and force_refresh with unchanged content are idempotent
    s1_cached = disc.download_snapshot(snap_date=d0)
    s1_forced_same = disc.download_snapshot(snap_date=d0, force_refresh=True)
    assert s1_cached.sha256 == s1.sha256 and s1_cached.raw_gz_path == s1.raw_gz_path
    assert s1_forced_same.sha256 == s1.sha256 and s1_forced_same.manifest_path == s1.manifest_path
    assert len(disc.list_snapshots(d0)) == 1

    # 3. Same-day changed content on force_refresh creates new immutable revision without overwriting rev 1
    state["active"][0] = {**state["active"][0], "tradable": False}
    s2 = disc.download_snapshot(snap_date=d0, force_refresh=True)
    assert s2.revision == 2
    assert s2.sha256 != s1.sha256
    assert s2.raw_gz_path != s1.raw_gz_path
    assert s2.manifest_path != s1.manifest_path
    assert disc.load_snapshot(d0, revision=1).sha256 == s1.sha256
    assert disc.load_snapshot(d0).sha256 == s2.sha256
    with gzip.open(s1.raw_gz_path, "rt", encoding="utf-8") as fh:
        assert hashlib.sha256(fh.read().encode("utf-8")).hexdigest() == s1.sha256
    with gzip.open(s2.raw_gz_path, "rt", encoding="utf-8") as fh:
        assert hashlib.sha256(fh.read().encode("utf-8")).hexdigest() == s2.sha256

    # 4. Interrupted write recovery leaves no orphaned file or valid-looking manifest
    d1 = date(2026, 11, 28)
    monkeypatch.setattr(disc, "_atomic_write_json", lambda *_a, **_kw: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        disc.download_snapshot(snap_date=d1)
    assert disc.load_snapshot(d1) is None
    assert not any((tmp_path / "raw" / f"date={d1.isoformat()}").glob("*.json.gz"))
    assert not any((tmp_path / "manifests" / f"date={d1.isoformat()}").glob("*.json"))

    monkeypatch.undo()
    s_d1 = disc.download_snapshot(snap_date=d1)
    assert disc.load_snapshot(d1).sha256 == s_d1.sha256

    # 5. Existing legacy snapshot (assets.json.gz + assets_manifest.json) remains readable and preserved
    d_leg = date(2026, 11, 26)
    leg_sdir = tmp_path / "raw" / f"date={d_leg.isoformat()}"
    leg_mdir = tmp_path / "manifests" / f"date={d_leg.isoformat()}"
    leg_sdir.mkdir(parents=True, exist_ok=True)
    leg_mdir.mkdir(parents=True, exist_ok=True)
    leg_text = json.dumps(ACTIVE_EQUITIES, sort_keys=True)
    leg_sha = hashlib.sha256(leg_text.encode("utf-8")).hexdigest()
    with gzip.open(leg_sdir / "assets.json.gz", "wt", encoding="utf-8") as fh:
        fh.write(leg_text)
    (leg_mdir / "assets_manifest.json").write_text(json.dumps({
        "snapshot_date": d_leg.isoformat(),
        "retrieved_at_utc": "2026-11-26T15:00:00+00:00",
        "sha256": leg_sha,
        "raw_count": len(ACTIVE_EQUITIES),
    }), encoding="utf-8")
    loaded_leg = disc.load_snapshot(d_leg)
    assert loaded_leg is not None and loaded_leg.sha256 == leg_sha

    # Same-day force refresh preserves legacy assets.json.gz while storing new revision independently
    s_leg_2 = disc.download_snapshot(snap_date=d_leg, force_refresh=True)
    assert s_leg_2.sha256 != leg_sha
    assert os.path.isfile(leg_sdir / "assets.json.gz")
    assert len(disc.list_snapshots(d_leg)) == 2

    # Checksum corruption fails closed
    with gzip.open(s_d1.raw_gz_path, "wt", encoding="utf-8") as fh:
        fh.write("[]")
    with pytest.raises(AlpacaAdapterError):
        disc.load_snapshot(d1)
