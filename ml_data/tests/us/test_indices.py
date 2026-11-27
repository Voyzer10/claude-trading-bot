"""Tests for AlpacaIndexDiscovery and SPX/SPXW index option family probing."""
from __future__ import annotations

from ml_data.instruments import AssetClass, InstrumentRegistry, Market, Segment
from ml_data.us import AlpacaDataClient, AlpacaIndexDiscovery
from ml_data.tests.us.fixtures import FakeAlpacaTransport, TEST_CRED


def test_index_discovery_and_option_family_probing(tmp_path):
    import os
    tr = FakeAlpacaTransport()
    client = AlpacaDataClient(credential=TEST_CRED, transport=tr)
    idx_disc = AlpacaIndexDiscovery(
        client=client,
        raw_root=str(tmp_path / "raw_idx"),
        manifest_root=str(tmp_path / "man_idx"),
    )
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))

    rep = idx_disc.discover_indices(registry=reg)
    assert len(rep.indices) == 1
    assert rep.snapshot_path is not None and os.path.isfile(rep.snapshot_path)
    spx = rep.indices[0]
    assert spx.market == Market.US
    assert spx.asset_class == AssetClass.INDEX
    assert spx.segment == Segment.US_INDEX
    assert spx.is_tradable is False

    caps = idx_disc.probe_index_option_families(("SPX", "SPXW"), discovered_indices=rep.indices)
    assert caps["SPX"].contract_master_support is True
    assert caps["SPX"].snapshot_support == "SUPPORTED"
    # Contract master + 1 snapshot alone must keep overall status UNVERIFIED until bars/quotes/realtime verified
    assert caps["SPX"].historical_bars_support == "UNVERIFIED"
    assert caps["SPX"].status == "UNVERIFIED"
    assert caps["SPXW"].contract_master_support is False
    assert caps["SPXW"].status == "UNSUPPORTED"
    reg.close()


def test_indices_immutable_snapshot_provenance_revisions_and_recovery(monkeypatch, tmp_path):
    import gzip
    import hashlib
    import json
    import os
    from datetime import date
    import pytest
    from ml_data.us import AlpacaAdapterError, AlpacaHTTPResponse
    from ml_data.tests.us.fixtures import US_INDICES

    state = {"rows": [dict(x) for x in US_INDICES]}

    def _tr(method, url, headers, params, timeout):
        return AlpacaHTTPResponse(200, state["rows"], {})

    client = AlpacaDataClient(credential=TEST_CRED, transport=_tr)
    idx_disc = AlpacaIndexDiscovery(
        client=client,
        raw_root=str(tmp_path / "raw_idx"),
        manifest_root=str(tmp_path / "man_idx"),
    )
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    d0 = date(2026, 11, 27)

    # 1. Initial discovery snapshot + SHA/file/manifest consistency + separate retrieved_at_utc
    r1 = idx_disc.discover_indices(registry=reg, snap_date=d0)
    assert r1.snapshot_revision == 1
    assert r1.retrieved_at_utc is not None
    assert r1.snapshot_path and os.path.isfile(r1.snapshot_path)
    assert r1.manifest_path and os.path.isfile(r1.manifest_path)
    with gzip.open(r1.snapshot_path, "rt", encoding="utf-8") as fh:
        assert hashlib.sha256(fh.read().encode("utf-8")).hexdigest() == r1.snapshot_sha256
    with open(r1.manifest_path, encoding="utf-8") as fh:
        m1 = json.load(fh)
    assert m1["sha256"] == r1.snapshot_sha256
    assert m1["snapshot_file"] == os.path.basename(r1.snapshot_path)
    assert m1["snapshot_date"] == d0.isoformat()
    assert m1["retrieved_at_utc"] == r1.retrieved_at_utc.isoformat()

    # 2. Repeated identical retrieval (discover_indices & force_refresh=True) is idempotent
    r1_repeat = idx_disc.discover_indices(registry=reg, snap_date=d0)
    s1_forced_same = idx_disc.download_snapshot(snap_date=d0, force_refresh=True)
    assert r1_repeat.snapshot_sha256 == r1.snapshot_sha256 and r1_repeat.snapshot_path == r1.snapshot_path
    assert s1_forced_same.sha256 == r1.snapshot_sha256 and s1_forced_same.manifest_path == r1.manifest_path
    assert len(idx_disc.list_snapshots(d0)) == 1

    # 3. Same-day changed retrieval stores new immutable revision & keeps r1 intact (never SHA/file mismatch!)
    state["rows"].append({
        "id": "idx-ndx-0002",
        "class": "us_index",
        "exchange": "INDEX",
        "symbol": "NDX",
        "name": "Nasdaq-100 Index",
        "status": "active",
        "tradable": False,
        "has_options": True,
        "options_late_close": True,
    })
    r2 = idx_disc.discover_indices(registry=reg, snap_date=d0)
    assert r2.snapshot_revision == 2
    assert r2.snapshot_sha256 != r1.snapshot_sha256
    assert r2.snapshot_path != r1.snapshot_path
    assert r2.manifest_path != r1.manifest_path
    assert idx_disc.load_snapshot(d0, revision=1).sha256 == r1.snapshot_sha256
    assert idx_disc.load_snapshot(d0).sha256 == r2.snapshot_sha256
    with gzip.open(r2.snapshot_path, "rt", encoding="utf-8") as fh:
        assert hashlib.sha256(fh.read().encode("utf-8")).hexdigest() == r2.snapshot_sha256
    with open(r2.manifest_path, encoding="utf-8") as fh:
        m2 = json.load(fh)
    assert m2["sha256"] == r2.snapshot_sha256
    assert m2["snapshot_file"] == os.path.basename(r2.snapshot_path)

    # 4. Interrupted write recovery
    d1 = date(2026, 11, 28)
    monkeypatch.setattr(idx_disc, "_atomic_write_json", lambda *_a, **_kw: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        idx_disc.download_snapshot(snap_date=d1)
    assert idx_disc.load_snapshot(d1) is None
    assert not any((tmp_path / "raw_idx" / f"date={d1.isoformat()}").glob("*.json.gz"))
    assert not any((tmp_path / "man_idx" / f"date={d1.isoformat()}").glob("*.json"))

    monkeypatch.undo()
    s_d1 = idx_disc.download_snapshot(snap_date=d1)
    assert idx_disc.load_snapshot(d1).sha256 == s_d1.sha256

    # 5. Legacy indices.json.gz + indices_manifest.json remains readable
    d_leg = date(2026, 11, 26)
    leg_sdir = tmp_path / "raw_idx" / f"date={d_leg.isoformat()}"
    leg_mdir = tmp_path / "man_idx" / f"date={d_leg.isoformat()}"
    leg_sdir.mkdir(parents=True, exist_ok=True)
    leg_mdir.mkdir(parents=True, exist_ok=True)
    leg_text = json.dumps(US_INDICES, sort_keys=True)
    leg_sha = hashlib.sha256(leg_text.encode("utf-8")).hexdigest()
    with gzip.open(leg_sdir / "indices.json.gz", "wt", encoding="utf-8") as fh:
        fh.write(leg_text)
    (leg_mdir / "indices_manifest.json").write_text(json.dumps({
        "snapshot_date": d_leg.isoformat(),
        "retrieved_at_utc": "2026-11-26T15:00:00+00:00",
        "sha256": leg_sha,
        "count": len(US_INDICES),
    }), encoding="utf-8")
    loaded_leg = idx_disc.load_snapshot(d_leg)
    assert loaded_leg is not None and loaded_leg.sha256 == leg_sha

    with gzip.open(s_d1.raw_gz_path, "wt", encoding="utf-8") as fh:
        fh.write("[]")
    with pytest.raises(AlpacaAdapterError):
        idx_disc.load_snapshot(d1)
    reg.close()
