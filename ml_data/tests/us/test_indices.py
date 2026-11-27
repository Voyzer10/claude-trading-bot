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
