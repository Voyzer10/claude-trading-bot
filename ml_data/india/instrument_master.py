"""Kite Connect instrument master downloader, validator, and snapshot archiver."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import IST_TZ, KiteClientWrapper
from .exceptions import InstrumentMasterError

MANDATORY_COLUMNS = (
    "instrument_token",
    "exchange_token",
    "tradingsymbol",
    "name",
    "last_price",
    "expiry",
    "strike",
    "tick_size",
    "lot_size",
    "instrument_type",
    "segment",
    "exchange",
)

DEFAULT_MASTER_ROOT = os.path.join("data", "raw", "india", "kite", "instrument_master")


@dataclass(frozen=True)
class MasterSnapshot:
    snapshot_date: date
    exchange: str
    downloaded_at_utc: datetime
    downloaded_at_ist: datetime
    sha256: str
    row_count: int
    csv_gz_path: str
    manifest_path: str
    rows: Tuple[Dict[str, str], ...]


def parse_instrument_master_csv(csv_text: str) -> Tuple[Dict[str, str], ...]:
    """Parse and strictly validate a Kite instrument master CSV dump."""
    if not csv_text or not csv_text.strip():
        raise InstrumentMasterError("Empty instrument master CSV")
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise InstrumentMasterError("Missing CSV header in instrument master")
    missing_cols = [c for c in MANDATORY_COLUMNS if c not in reader.fieldnames]
    if missing_cols:
        raise InstrumentMasterError(f"Instrument master missing mandatory columns: {missing_cols}")

    rows: List[Dict[str, str]] = []
    for idx, row in enumerate(reader, start=2):
        tok = (row.get("instrument_token") or "").strip()
        tsym = (row.get("tradingsymbol") or "").strip()
        ex = (row.get("exchange") or "").strip()
        itype = (row.get("instrument_type") or "").strip()
        if not tok or not tok.isdigit() or not tsym or not ex or not itype:
            raise InstrumentMasterError(f"Malformed instrument master row at line {idx}: {row!r}")
        rows.append({k: (v or "").strip() for k, v in row.items() if k is not None})
    if not rows:
        raise InstrumentMasterError("Instrument master CSV contains zero rows")
    return tuple(rows)


def diff_snapshots(
    prev_rows: Sequence[Dict[str, str]],
    curr_rows: Sequence[Dict[str, str]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Detect added, removed, and changed contracts between two snapshots keyed by (exchange, tradingsymbol)."""
    prev_map = {(r["exchange"], r["tradingsymbol"]): r for r in prev_rows}
    curr_map = {(r["exchange"], r["tradingsymbol"]): r for r in curr_rows}

    added = [curr_map[k] for k in sorted(curr_map.keys() - prev_map.keys())]
    removed = [prev_map[k] for k in sorted(prev_map.keys() - curr_map.keys())]
    changed: List[Dict[str, Any]] = []
    tracked_fields = ("instrument_token", "lot_size", "tick_size", "expiry", "strike", "instrument_type", "segment")
    for k in sorted(prev_map.keys() & curr_map.keys()):
        p, c = prev_map[k], curr_map[k]
        diffs = {f: {"old": p.get(f), "new": c.get(f)} for f in tracked_fields if p.get(f) != c.get(f)}
        if diffs:
            changed.append({"exchange": k[0], "tradingsymbol": k[1], "changes": diffs})
    return {"added": added, "removed": removed, "changed": changed}


class InstrumentMasterDownloader:
    """Downloads, validates, checksums, and archives daily Kite instrument master snapshots."""

    def __init__(
        self,
        client: Optional[KiteClientWrapper] = None,
        root_dir: str = DEFAULT_MASTER_ROOT,
    ) -> None:
        self.client = client or KiteClientWrapper()
        self.root_dir = root_dir

    def _snapshot_dir(self, snap_date: date, exchange: str) -> str:
        return os.path.join(self.root_dir, f"date={snap_date.isoformat()}", exchange.upper())

    def _snapshot_paths(self, sdir: str, revision: int = 0) -> Tuple[str, str]:
        if revision == 0:
            return os.path.join(sdir, "instruments.csv.gz"), os.path.join(sdir, "manifest.json")
        return os.path.join(sdir, f"instruments.rev{revision}.csv.gz"), os.path.join(sdir, f"manifest.rev{revision}.json")

    def _latest_revision(self, sdir: str) -> Optional[int]:
        base_gz, base_man = self._snapshot_paths(sdir, 0)
        if not (os.path.isfile(base_gz) and os.path.isfile(base_man)):
            return None
        rev = 0
        while True:
            nxt_gz, nxt_man = self._snapshot_paths(sdir, rev + 1)
            if os.path.isfile(nxt_gz) and os.path.isfile(nxt_man):
                rev += 1
            else:
                break
        return rev

    def load_snapshot(self, snap_date: date, exchange: str, *, revision: Optional[int] = None) -> Optional[MasterSnapshot]:
        ex = exchange.strip().upper()
        sdir = self._snapshot_dir(snap_date, ex)
        rev = revision if revision is not None else self._latest_revision(sdir)
        if rev is None:
            return None
        gz_path, man_path = self._snapshot_paths(sdir, rev)
        if not (os.path.isfile(gz_path) and os.path.isfile(man_path)):
            return None
        with open(man_path, encoding="utf-8") as fh:
            man = json.load(fh)
        with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
            raw_csv = fh.read()
        sha = hashlib.sha256(raw_csv.encode("utf-8")).hexdigest()
        if sha != man.get("sha256"):
            raise InstrumentMasterError(f"Checksum mismatch in snapshot {gz_path}")
        rows = parse_instrument_master_csv(raw_csv)
        return MasterSnapshot(
            snapshot_date=snap_date,
            exchange=ex,
            downloaded_at_utc=datetime.fromisoformat(man["downloaded_at_utc"]),
            downloaded_at_ist=datetime.fromisoformat(man["downloaded_at_ist"]),
            sha256=sha,
            row_count=len(rows),
            csv_gz_path=gz_path,
            manifest_path=man_path,
            rows=rows,
        )

    @staticmethod
    def _atomic_write_gz(path: str, text: str) -> None:
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise

    @staticmethod
    def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise

    def download_snapshot(
        self,
        exchange: str,
        *,
        snap_date: Optional[date] = None,
        dry_run: bool = False,
        force_refresh: bool = False,
    ) -> MasterSnapshot:
        """Fetch and persist an immutable daily snapshot; force_refresh creates a new immutable revision if content changed."""
        ex = exchange.strip().upper()
        now_utc = datetime.now(timezone.utc)
        now_ist = now_utc.astimezone(IST_TZ)
        target_date = snap_date or now_ist.date()

        existing = self.load_snapshot(target_date, ex)
        if existing is not None and not force_refresh:
            return existing

        raw_csv = self.client.fetch_instruments_csv(ex)
        rows = parse_instrument_master_csv(raw_csv)
        sha = hashlib.sha256(raw_csv.encode("utf-8")).hexdigest()

        if existing is not None and existing.sha256 == sha:
            return existing

        sdir = self._snapshot_dir(target_date, ex)
        latest_rev = self._latest_revision(sdir)
        new_rev = 0 if latest_rev is None else latest_rev + 1
        gz_path, man_path = self._snapshot_paths(sdir, new_rev)

        if not dry_run:
            if os.path.exists(gz_path) or os.path.exists(man_path):
                raise InstrumentMasterError(
                    f"Refusing to overwrite existing instrument master snapshot: {gz_path}"
                )
            os.makedirs(sdir, exist_ok=True)
            manifest = {
                "snapshot_date": target_date.isoformat(),
                "exchange": ex,
                "revision": new_rev,
                "downloaded_at_utc": now_utc.isoformat(),
                "downloaded_at_ist": now_ist.isoformat(),
                "sha256": sha,
                "row_count": len(rows),
            }
            self._atomic_write_gz(gz_path, raw_csv)
            try:
                self._atomic_write_json(man_path, manifest)
            except Exception:
                if os.path.exists(gz_path):
                    try:
                        os.remove(gz_path)
                    except OSError:
                        pass
                raise

        return MasterSnapshot(
            snapshot_date=target_date,
            exchange=ex,
            downloaded_at_utc=now_utc,
            downloaded_at_ist=now_ist,
            sha256=sha,
            row_count=len(rows),
            csv_gz_path=gz_path,
            manifest_path=man_path,
            rows=rows,
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Download Kite instrument master daily snapshot (read-only).")
    p.add_argument("--exchange", default="NFO", choices=["NSE", "NFO"])
    p.add_argument("--dry-run", action="store_true", help="Fetch and validate without writing files.")
    args = p.parse_args(argv)
    dl = InstrumentMasterDownloader()
    snap = dl.download_snapshot(args.exchange, dry_run=args.dry_run)
    print(json.dumps({
        "snapshot_date": snap.snapshot_date.isoformat(),
        "exchange": snap.exchange,
        "row_count": snap.row_count,
        "sha256": snap.sha256,
        "dry_run": args.dry_run,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
