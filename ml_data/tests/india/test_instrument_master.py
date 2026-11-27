"""Tests for Kite InstrumentMasterDownloader, CSV validation, checksums, and snapshot diffs."""
from __future__ import annotations

from datetime import date

import pytest

from ml_data.india import (
    InstrumentMasterDownloader,
    InstrumentMasterError,
    KiteClientWrapper,
)
from ml_data.india.instrument_master import diff_snapshots, parse_instrument_master_csv
from ml_data.tests.india.fixtures import FakeKiteSDK, NFO_CSV, NSE_CSV


def test_parse_and_archive_daily_snapshot(tmp_path):
    sdk = FakeKiteSDK()
    client = KiteClientWrapper(kite_client=sdk)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "master"))
    d0 = date(2026, 11, 27)

    snap = dl.download_snapshot("NFO", snap_date=d0)
    assert snap.row_count == 9
    assert len(snap.sha256) == 64
    assert snap.downloaded_at_ist.tzinfo is not None
    assert snap.downloaded_at_utc.tzinfo is not None

    # Second call on same date uses cached snapshot without hitting API again
    calls_before = len(sdk.calls)
    snap2 = dl.download_snapshot("NFO", snap_date=d0)
    assert snap2.sha256 == snap.sha256
    assert len(sdk.calls) == calls_before


def test_malformed_or_missing_column_csv_rejected():
    with pytest.raises(InstrumentMasterError):
        parse_instrument_master_csv("")
    with pytest.raises(InstrumentMasterError):
        parse_instrument_master_csv("instrument_token,tradingsymbol\n123,NIFTY26DECFUT\n")
    with pytest.raises(InstrumentMasterError):
        parse_instrument_master_csv(NSE_CSV + "BAD_TOK,1,X,X,0,,0,0.05,1,EQ,NSE,NSE\n")


def test_snapshot_diff_detects_added_removed_changed():
    prev = parse_instrument_master_csv(NFO_CSV)
    modified = NFO_CSV.replace(",75,CE,", ",80,CE,").replace(
        "100009,398,RELIANCE26DEC1400CE,RELIANCE,25.0,2026-12-31,1400,0.05,500,CE,NFO-OPT,NFO\n",
        "100010,399,NIFTY26D1024600CE,NIFTY,120.0,2026-12-10,24600,0.05,75,CE,NFO-OPT,NFO\n",
    )
    curr = parse_instrument_master_csv(modified)
    diff = diff_snapshots(prev, curr)
    assert [r["tradingsymbol"] for r in diff["added"]] == ["NIFTY26D1024600CE"]
    assert [r["tradingsymbol"] for r in diff["removed"]] == ["RELIANCE26DEC1400CE"]
    assert diff["changed"][0]["tradingsymbol"] == "NIFTY26D0324500CE"
    assert diff["changed"][0]["changes"]["lot_size"] == {"old": "75", "new": "80"}


def test_http_gzip_plain_and_error_paths(monkeypatch, tmp_path):
    import gzip
    import urllib.request

    class _FakeResp:
        def __init__(self, body: bytes, headers: dict):
            self._body = body
            self.headers = headers

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    client = KiteClientWrapper(max_retries=0)
    monkeypatch.setattr(client, "_auth_headers", lambda: {"Authorization": "token SECRET_KEY:SECRET_TOK"})

    # 1. Valid gzipped CSV with Content-Encoding: gzip
    gz_bytes = gzip.compress(NFO_CSV.encode("utf-8"))
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: _FakeResp(gz_bytes, {"Content-Encoding": "gzip"}))
    assert "NIFTY26DECFUT" in client.fetch_instruments_csv("NFO")

    # 2. Valid gzipped CSV detected by magic bytes even without Content-Encoding header
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: _FakeResp(gz_bytes, {}))
    assert "NIFTY26DECFUT" in client.fetch_instruments_csv("NFO")

    # 3. Plain CSV compatibility
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: _FakeResp(NFO_CSV.encode("utf-8"), {}))
    assert "NIFTY26DECFUT" in client.fetch_instruments_csv("NFO")

    # 4. Invalid compressed data with gzip magic bytes
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: _FakeResp(b"\x1f\x8bcorrupt_gzip_bytes", {}))
    with pytest.raises(InstrumentMasterError) as exc_info:
        client.fetch_instruments_csv("NFO")
    assert "SECRET_TOK" not in str(exc_info.value)

    # 5. Incorrect Content-Encoding: gzip on plain text & unsupported Content-Encoding
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: _FakeResp(NFO_CSV.encode("utf-8"), {"Content-Encoding": "gzip"}))
    with pytest.raises(InstrumentMasterError):
        client.fetch_instruments_csv("NFO")

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: _FakeResp(NFO_CSV.encode("utf-8"), {"Content-Encoding": "deflate"}))
    with pytest.raises(InstrumentMasterError):
        client.fetch_instruments_csv("NFO")


def test_snapshot_force_refresh_revision_and_atomic_interrupted_write(monkeypatch, tmp_path):
    sdk = FakeKiteSDK()
    client = KiteClientWrapper(kite_client=sdk)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "master"))
    d0 = date(2026, 11, 27)

    s0 = dl.download_snapshot("NFO", snap_date=d0)
    assert s0.csv_gz_path.endswith("instruments.csv.gz")

    # Same-day force_refresh with changed CSV creates immutable rev1 without overwriting rev0
    sdk.nfo_csv = NFO_CSV + "100010,399,NIFTY26D1024600CE,NIFTY,120.0,2026-12-10,24600,0.05,75,CE,NFO-OPT,NFO\n"
    s1 = dl.download_snapshot("NFO", snap_date=d0, force_refresh=True)
    assert s1.sha256 != s0.sha256
    assert "rev1" in s1.csv_gz_path
    assert dl.load_snapshot(d0, "NFO", revision=0).sha256 == s0.sha256
    assert dl.load_snapshot(d0, "NFO").sha256 == s1.sha256

    # Interrupted manifest write leaves no orphaned incomplete snapshot
    d1 = date(2026, 11, 28)
    monkeypatch.setattr(dl, "_atomic_write_json", lambda *_a, **_kw: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        dl.download_snapshot("NFO", snap_date=d1)
    assert dl.load_snapshot(d1, "NFO") is None
