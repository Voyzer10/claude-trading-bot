"""Historical intraday candle client for Kite Connect (NIFTY/BANKNIFTY) with strict validation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..instruments import AssetClass, InstrumentRegistry
from .config import INTERVAL_MAX_DAYS, IST_TZ, KiteClientWrapper, NSECalendar, UTC_TZ
from .exceptions import KiteAdapterError, KiteInputError

_INTERVAL_MINUTES = {
    "minute": 1,
    "3minute": 3,
    "5minute": 5,
    "10minute": 10,
    "15minute": 15,
    "30minute": 30,
    "60minute": 60,
}


@dataclass(frozen=True)
class HistoricalCandle:
    instrument_id: str
    interval: str
    ts_utc: datetime
    ts_ist: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    oi: Optional[int]
    provider: str
    provider_feed: str
    snapshot_date: Optional[str]


@dataclass
class HistoricalFetchResult:
    instrument_id: str
    interval: str
    candles: List[HistoricalCandle] = field(default_factory=list)
    duplicates_dropped: int = 0
    out_of_range_dropped: int = 0
    checkpoint_dropped_records: int = 0
    missing_timestamps: List[datetime] = field(default_factory=list)
    chunks_completed: int = 0
    calendar_verified: bool = True
    calendar_status: str = "VERIFIED"
    conflicting_duplicates: int = 0
    out_of_session_count: int = 0
    out_of_session_candles: List[HistoricalCandle] = field(default_factory=list)
    invalid_rows: List[Dict[str, Any]] = field(default_factory=list)
    coverage_status: str = "UNVERIFIED_CALENDAR"


def _parse_candle_ts(raw_ts: Any) -> datetime:
    if isinstance(raw_ts, bool) or raw_ts is None or (isinstance(raw_ts, str) and not raw_ts.strip()):
        raise KiteAdapterError(f"Missing or invalid candle timestamp: {raw_ts!r}")
    if isinstance(raw_ts, datetime):
        dt = raw_ts
    else:
        try:
            dt = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
        except ValueError as e:
            raise KiteAdapterError(f"Unparsable candle timestamp: {raw_ts!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST_TZ)
    return dt.astimezone(UTC_TZ)


def _dec(val: Any, name: str) -> Decimal:
    if isinstance(val, bool) or val is None:
        raise KiteAdapterError(f"Malformed OHLC {name}: {val!r}")
    try:
        d = Decimal(str(val).strip())
        if not d.is_finite():
            raise ValueError("non-finite")
        if d <= 0:
            raise ValueError("non-positive")
        return d
    except (InvalidOperation, ValueError) as e:
        raise KiteAdapterError(f"Malformed OHLC {name}: {val!r}") from e


def _non_neg_int(val: Any, name: str, *, allow_none: bool = False) -> Optional[int]:
    if val is None:
        if allow_none:
            return None
        raise KiteAdapterError(f"Missing required integer field {name}")
    if isinstance(val, bool):
        raise KiteAdapterError(f"Malformed {name} (bool not permitted): {val!r}")
    try:
        if isinstance(val, float):
            if not Decimal(str(val)).is_finite() or val != int(val):
                raise ValueError("non-integral float")
            iv = int(val)
        else:
            d = Decimal(str(val).strip())
            if not d.is_finite() or d != int(d):
                raise ValueError("non-integral decimal")
            iv = int(d)
    except (InvalidOperation, ValueError, OverflowError) as e:
        raise KiteAdapterError(f"Malformed {name}: {val!r}") from e
    if iv < 0:
        raise KiteAdapterError(f"Negative {name} not permitted: {iv}")
    return iv


def _normalize_raw_candle(
    raw: Any,
    *,
    instrument_id: str,
    interval: str,
    snapshot_date: Optional[str],
) -> HistoricalCandle:
    if isinstance(raw, dict):
        ts_val = raw.get("date") or raw.get("timestamp") or raw.get("t")
        o_v, h_v, l_v, c_v, v_v = raw.get("open"), raw.get("high"), raw.get("low"), raw.get("close"), raw.get("volume")
        oi_v = raw.get("oi")
    elif isinstance(raw, (list, tuple)) and len(raw) >= 6:
        ts_val, o_v, h_v, l_v, c_v, v_v = raw[0], raw[1], raw[2], raw[3], raw[4], raw[5]
        oi_v = raw[6] if len(raw) >= 7 else None
    else:
        raise KiteAdapterError(f"Malformed Kite candle payload: {raw!r}")

    ts_utc = _parse_candle_ts(ts_val)
    ts_ist = ts_utc.astimezone(IST_TZ)
    o_d = _dec(o_v, "open")
    h_d = _dec(h_v, "high")
    l_d = _dec(l_v, "low")
    c_d = _dec(c_v, "close")
    if h_d < max(o_d, c_d) or l_d > min(o_d, c_d) or h_d < l_d:
        raise KiteAdapterError(f"Invalid OHLC relationship at {ts_utc.isoformat()}: O={o_d} H={h_d} L={l_d} C={c_d}")
    vol = _non_neg_int(v_v, "volume", allow_none=False)
    assert vol is not None
    oi = _non_neg_int(oi_v, "oi", allow_none=True)
    return HistoricalCandle(
        instrument_id=instrument_id,
        interval=interval,
        ts_utc=ts_utc,
        ts_ist=ts_ist,
        open=o_d,
        high=h_d,
        low=l_d,
        close=c_d,
        volume=vol,
        oi=oi,
        provider="kite",
        provider_feed="kite_historical",
        snapshot_date=snapshot_date,
    )


def _same_candle_values(a: HistoricalCandle, b: HistoricalCandle) -> bool:
    return (
        a.open == b.open
        and a.high == b.high
        and a.low == b.low
        and a.close == b.close
        and a.volume == b.volume
        and a.oi == b.oi
    )


def expected_session_timestamps(
    calendar: NSECalendar,
    interval: str,
    from_dt: datetime,
    to_dt: datetime,
    *,
    require_verified: bool = True,
) -> List[datetime]:
    """Generate exact expected UTC candle timestamps within [from_dt, to_dt) using Kite session alignment."""
    if interval not in _INTERVAL_MINUTES:
        raise KiteInputError(f"Unsupported interval: {interval!r}")
    from_ist = from_dt.astimezone(IST_TZ) if from_dt.tzinfo else from_dt.replace(tzinfo=IST_TZ)
    to_ist = to_dt.astimezone(IST_TZ) if to_dt.tzinfo else to_dt.replace(tzinfo=IST_TZ)
    from_utc = from_ist.astimezone(UTC_TZ)
    to_utc = to_ist.astimezone(UTC_TZ)
    step = timedelta(minutes=_INTERVAL_MINUTES[interval])

    expected: List[datetime] = []
    cur_day = from_ist.date()
    end_day = to_ist.date()
    while cur_day <= end_day:
        bounds = calendar.session_bounds(cur_day, require_verified=require_verified)
        if bounds is not None:
            open_utc = bounds[0].astimezone(UTC_TZ)
            close_utc = bounds[1].astimezone(UTC_TZ)
            cur = open_utc
            while cur < close_utc:
                if from_utc <= cur < to_utc:
                    expected.append(cur)
                cur += step
        cur_day += timedelta(days=1)
    return expected


def chunk_date_range(from_dt: datetime, to_dt: datetime, interval: str, max_days: Optional[int] = None) -> List[Tuple[datetime, datetime]]:
    """Split [from_dt, to_dt) into conservative Kite API chunk windows."""
    if interval not in INTERVAL_MAX_DAYS:
        raise KiteInputError(f"Unsupported interval: {interval!r}")
    if to_dt <= from_dt:
        raise KiteInputError("to_datetime must be after from_datetime")
    days = int(max_days or INTERVAL_MAX_DAYS[interval])
    step = timedelta(days=days)
    chunks: List[Tuple[datetime, datetime]] = []
    cur = from_dt
    while cur < to_dt:
        nxt = min(to_dt, cur + step)
        chunks.append((cur, nxt))
        cur = nxt
    return chunks


class KiteHistoricalDataClient:
    """Chunked, checkpointed, rate-limited historical candle client for Kite Connect."""

    def __init__(
        self,
        *,
        client: Optional[KiteClientWrapper] = None,
        registry: Optional[InstrumentRegistry] = None,
        calendar: Optional[NSECalendar] = None,
        interval_max_days: Optional[Dict[str, int]] = None,
        checkpoint_dir: Optional[str] = None,
    ) -> None:
        self.client = client or KiteClientWrapper()
        self.registry = registry
        self.calendar = calendar or NSECalendar()
        self.interval_max_days = dict(interval_max_days or INTERVAL_MAX_DAYS)
        self.checkpoint_dir = checkpoint_dir

    def _resolve_token_and_snapshot(
        self,
        instrument_id: str,
        *,
        as_of: Optional[datetime] = None,
    ) -> Tuple[int, Optional[str], AssetClass]:
        """Resolve historical Kite instrument_token via date-scoped [valid_from, valid_until) mappings."""
        if self.registry is None:
            raise KiteInputError("InstrumentRegistry is required to resolve verified provider token")
        inst = self.registry.get(instrument_id)
        if inst is None:
            raise KiteInputError(f"Unknown canonical instrument_id: {instrument_id}")

        snap_date = (inst.metadata or {}).get("snapshot_date")
        kite_maps = [m for m in self.registry.get_provider_mappings(instrument_id) if m.provider == "kite"]
        if kite_maps and as_of is not None:
            check_ts = as_of.astimezone(UTC_TZ) if as_of.tzinfo else as_of.replace(tzinfo=IST_TZ).astimezone(UTC_TZ)
            # Identify mappings carrying numeric instrument tokens vs legacy symbolic IDs
            token_maps = [
                m for m in kite_maps
                if m.provider_instrument_id and str(m.provider_instrument_id).strip().isdigit()
            ]
            if token_maps:
                active = [
                    m for m in token_maps
                    if (m.valid_from is None or m.valid_from <= check_ts)
                    and (m.valid_until is None or check_ts < m.valid_until)
                ]
                if not active:
                    raise KiteInputError(
                        f"No active Kite provider mapping for {instrument_id} at {check_ts.isoformat()}"
                    )
                chosen = active[-1]
                return int(str(chosen.provider_instrument_id)), snap_date, inst.asset_class

        tok = (inst.metadata or {}).get("instrument_token")
        if tok is None:
            raise KiteInputError(f"No verified instrument_token in metadata for {instrument_id}")
        return int(tok), snap_date, inst.asset_class

    def _ckpt_meta(
        self,
        instrument_id: str,
        interval: str,
        from_utc: datetime,
        to_utc: datetime,
        include_oi: bool,
        snap_date: Optional[str],
        token: int,
    ) -> Dict[str, Any]:
        return {
            "version": 3,
            "instrument_id": instrument_id,
            "interval": interval,
            "from_utc": from_utc.isoformat(),
            "to_utc": to_utc.isoformat(),
            "include_oi": bool(include_oi),
            "snapshot_date": snap_date,
            "instrument_token": int(token),
        }

    def _ckpt_path(self, meta: Dict[str, Any]) -> Optional[str]:
        if not self.checkpoint_dir:
            return None
        safe = str(meta["instrument_id"]).replace(":", "_").replace("#", "_")
        raw_key = json.dumps(meta, sort_keys=True, separators=(",", ":")).encode("utf-8")
        req_hash = hashlib.sha256(raw_key).hexdigest()[:16]
        return os.path.join(self.checkpoint_dir, f"{safe}_{meta['interval']}_{req_hash}.json")

    def _load_ckpt(self, path: Optional[str], expected_meta: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        empty = {"completed_chunks": [], "candles": []}
        if not path or not os.path.isfile(path):
            return empty, 0
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return empty, 0
        if not isinstance(data, dict) or data.get("version") != expected_meta.get("version"):
            return empty, 0
        for k, v in expected_meta.items():
            if data.get(k) != v:
                dropped = len(data.get("candles") or []) if isinstance(data.get("candles"), list) else 0
                return empty, dropped
        if not isinstance(data.get("completed_chunks"), list) or not isinstance(data.get("candles"), list):
            return empty, 0
        return data, 0

    def _save_ckpt(self, path: Optional[str], data: Dict[str, Any]) -> None:
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
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

    def fetch_historical_candles(
        self,
        instrument_id: str,
        interval: str,
        from_datetime: datetime,
        to_datetime: datetime,
        include_oi: bool = True,
        *,
        quarantine_invalid: bool = False,
        reject_out_of_session: bool = False,
    ) -> HistoricalFetchResult:
        if interval not in self.interval_max_days:
            raise KiteInputError(f"Unsupported interval: {interval!r}")
        from_utc = from_datetime.astimezone(UTC_TZ) if from_datetime.tzinfo else from_datetime.replace(tzinfo=IST_TZ).astimezone(UTC_TZ)
        to_utc = to_datetime.astimezone(UTC_TZ) if to_datetime.tzinfo else to_datetime.replace(tzinfo=IST_TZ).astimezone(UTC_TZ)
        if to_utc <= from_utc:
            raise KiteInputError("to_datetime must be strictly after from_datetime")

        token, snap_date, asset_class = self._resolve_token_and_snapshot(instrument_id, as_of=from_utc)
        chunks = chunk_date_range(from_utc, to_utc, interval, max_days=self.interval_max_days[interval])
        ckpt_meta = self._ckpt_meta(instrument_id, interval, from_utc, to_utc, include_oi, snap_date, token)
        ckpt_path = self._ckpt_path(ckpt_meta)
        ckpt, ckpt_dropped = self._load_ckpt(ckpt_path, ckpt_meta)
        done_keys = set(str(x) for x in (ckpt.get("completed_chunks") or []))

        by_ts: Dict[datetime, HistoricalCandle] = {}
        out_of_session_by_ts: Dict[datetime, HistoricalCandle] = {}
        invalid_rows: List[Dict[str, Any]] = []
        out_of_range = 0
        conflicts = 0

        def _ingest(raw: Any, *, from_ckpt: bool) -> None:
            nonlocal out_of_range, duplicates, conflicts, ckpt_dropped
            try:
                hc = _normalize_raw_candle(raw, instrument_id=instrument_id, interval=interval, snapshot_date=snap_date)
            except KiteAdapterError as e:
                if from_ckpt:
                    ckpt_dropped += 1
                    return
                if quarantine_invalid:
                    invalid_rows.append({"raw": raw, "reason": str(e)})
                    return
                raise

            # Strict half-open [from_utc, to_utc): from_utc included, to_utc excluded
            if hc.ts_utc < from_utc or hc.ts_utc >= to_utc:
                out_of_range += 1
                if from_ckpt:
                    ckpt_dropped += 1
                return

            if not self.calendar.is_in_session(hc.ts_utc, require_verified=False):
                if reject_out_of_session:
                    raise KiteAdapterError(
                        f"Out-of-session candle for {instrument_id} at {hc.ts_ist.isoformat()}"
                    )
                prev_oos = out_of_session_by_ts.get(hc.ts_utc)
                if prev_oos is None:
                    out_of_session_by_ts[hc.ts_utc] = hc
                elif not _same_candle_values(prev_oos, hc):
                    conflicts += 1
                    if quarantine_invalid:
                        invalid_rows.append({"raw": raw, "reason": f"Conflicting out-of-session duplicate at {hc.ts_utc.isoformat()}"})
                    else:
                        raise KiteAdapterError(
                            f"Conflicting duplicate out-of-session candle at {hc.ts_utc.isoformat()}"
                        )
                else:
                    duplicates += 1
                return

            prev = by_ts.get(hc.ts_utc)
            if prev is None:
                by_ts[hc.ts_utc] = hc
            elif _same_candle_values(prev, hc):
                duplicates += 1
            else:
                conflicts += 1
                if quarantine_invalid:
                    # Do not keep conflicting record silently: remove ambiguous bar and quarantine both
                    by_ts.pop(hc.ts_utc, None)
                    invalid_rows.append({
                        "raw": raw,
                        "reason": f"Conflicting duplicate candle at {hc.ts_utc.isoformat()}",
                    })
                else:
                    raise KiteAdapterError(
                        f"Conflicting duplicate candle at {hc.ts_utc.isoformat()}: "
                        f"existing=({prev.open},{prev.high},{prev.low},{prev.close},{prev.volume},{prev.oi}) "
                        f"vs incoming=({hc.open},{hc.high},{hc.low},{hc.close},{hc.volume},{hc.oi})"
                    )

        duplicates = 0
        for c_dict in ckpt.get("candles") or []:
            _ingest(c_dict, from_ckpt=True)
        for oos_dict in ckpt.get("out_of_session") or []:
            _ingest(oos_dict, from_ckpt=True)

        for c_start, c_end in chunks:
            ckey = f"{c_start.isoformat()}|{c_end.isoformat()}"
            if ckey in done_keys:
                continue
            chunk_token, _, _ = self._resolve_token_and_snapshot(instrument_id, as_of=c_start)
            raw_rows = self.client.fetch_historical_candles(chunk_token, interval, c_start, c_end, include_oi=include_oi)
            for raw in raw_rows:
                _ingest(raw, from_ckpt=False)
            done_keys.add(ckey)
            self._save_ckpt(
                ckpt_path,
                {
                    **ckpt_meta,
                    "completed_chunks": sorted(done_keys),
                    "candles": [
                        [c.ts_utc.isoformat(), str(c.open), str(c.high), str(c.low), str(c.close), c.volume, c.oi]
                        for c in sorted(by_ts.values(), key=lambda x: x.ts_utc)
                    ],
                    "out_of_session": [
                        [c.ts_utc.isoformat(), str(c.open), str(c.high), str(c.low), str(c.close), c.volume, c.oi]
                        for c in sorted(out_of_session_by_ts.values(), key=lambda x: x.ts_utc)
                    ],
                },
            )

        ordered = sorted(by_ts.values(), key=lambda x: x.ts_utc)
        ordered_oos = sorted(out_of_session_by_ts.values(), key=lambda x: x.ts_utc)
        cal_verified = self.calendar.is_verified_for_range(
            from_utc.astimezone(IST_TZ).date(),
            (to_utc - timedelta(microseconds=1)).astimezone(IST_TZ).date(),
        )
        expected_ts = expected_session_timestamps(self.calendar, interval, from_utc, to_utc, require_verified=False)
        present_ts = {c.ts_utc for c in ordered}
        missing = [ts for ts in expected_ts if ts not in present_ts]

        if ordered_oos:
            cov_status = "OUT_OF_SESSION_DETECTED"
        elif not cal_verified:
            cov_status = "UNVERIFIED_CALENDAR"
        elif not ordered:
            cov_status = "EMPTY_RESPONSE"
        elif expected_ts and not missing:
            cov_status = "COMPLETE"
        elif asset_class == AssetClass.OPTION:
            cov_status = "SPARSE_OPTION_UNKNOWN"
        else:
            cov_status = "PARTIAL_DATA"

        return HistoricalFetchResult(
            instrument_id=instrument_id,
            interval=interval,
            candles=ordered,
            duplicates_dropped=duplicates,
            out_of_range_dropped=out_of_range,
            checkpoint_dropped_records=ckpt_dropped,
            missing_timestamps=missing,
            chunks_completed=len(done_keys),
            calendar_verified=cal_verified,
            calendar_status="VERIFIED" if cal_verified else "UNVERIFIED_CALENDAR",
            conflicting_duplicates=conflicts,
            out_of_session_count=len(ordered_oos),
            out_of_session_candles=ordered_oos,
            invalid_rows=invalid_rows,
            coverage_status=cov_status,
        )

    def _detect_missing(self, candles: Sequence[HistoricalCandle], interval: str) -> List[datetime]:
        if len(candles) < 2:
            return []
        step = timedelta(minutes=_INTERVAL_MINUTES[interval])
        missing: List[datetime] = []
        for prev, curr in zip(candles, candles[1:]):
            if prev.ts_ist.date() != curr.ts_ist.date():
                continue
            cur = prev.ts_utc + step
            while cur < curr.ts_utc:
                if self.calendar.is_in_session(cur):
                    missing.append(cur)
                cur += step
        return missing

    def coverage_preflight(
        self,
        instrument_ids: Sequence[str],
        from_datetime: datetime,
        to_datetime: datetime,
        intervals: Sequence[str] = ("minute", "5minute", "15minute", "60minute"),
    ) -> List[Dict[str, Any]]:
        """Read-only coverage preflight report across a small representative sample."""
        from_ist = from_datetime.astimezone(IST_TZ) if from_datetime.tzinfo else from_datetime.replace(tzinfo=IST_TZ)
        to_ist = to_datetime.astimezone(IST_TZ) if to_datetime.tzinfo else to_datetime.replace(tzinfo=IST_TZ)
        cal_verified = self.calendar.is_verified_for_range(
            from_ist.date(),
            (to_ist - timedelta(microseconds=1)).date() if to_ist > from_ist else to_ist.date(),
        )

        report: List[Dict[str, Any]] = []
        for iid in instrument_ids:
            inst = self.registry.get(iid) if self.registry else None
            tok = (inst.metadata or {}).get("instrument_token") if inst else None
            snap = (inst.metadata or {}).get("snapshot_date") if inst else None
            entry: Dict[str, Any] = {
                "instrument_id": iid,
                "token_available": tok is not None,
                "snapshot_date": snap,
                "data_returned": False,
                "range_covered": False,
                "calendar_verified": cal_verified,
                "oi_available": False,
                "missing_count": 0,
                "out_of_session_count": 0,
                "conflicting_duplicates": 0,
                "intervals": {},
                "earliest": None,
                "latest": None,
                "status": "EMPTY_RESPONSE",
                "coverage_classification": "EMPTY_RESPONSE",
            }
            if inst is None or tok is None:
                entry["status"] = "UNSUPPORTED"
                entry["coverage_classification"] = "UNSUPPORTED"
                report.append(entry)
                continue
            if inst.instrument_status.value == "EXPIRED":
                entry["status"] = "UNAVAILABLE_EXPIRED_CONTRACT"
                entry["coverage_classification"] = "UNAVAILABLE_EXPIRED_CONTRACT"
                report.append(entry)
                continue

            has_data = False
            all_covered = True
            has_auth_err = False
            has_other_err = False
            total_missing = 0
            total_oos = 0
            total_conflicts = 0
            for iv in intervals:
                try:
                    res = self.fetch_historical_candles(iid, iv, from_datetime, to_datetime, include_oi=True)
                    cnt = len(res.candles)
                    iv_oi = any(c.oi is not None for c in res.candles)
                    e0 = res.candles[0].ts_utc.isoformat() if res.candles else None
                    e1 = res.candles[-1].ts_utc.isoformat() if res.candles else None
                    total_oos += res.out_of_session_count
                    total_conflicts += res.conflicting_duplicates

                    if not cal_verified:
                        expected_ts = expected_session_timestamps(
                            self.calendar, iv, from_ist, to_ist, require_verified=False
                        )
                        present_ts = {c.ts_utc for c in res.candles}
                        iv_missing = sum(1 for ts in expected_ts if ts not in present_ts)
                        total_missing += iv_missing
                        iv_covered = False
                        iv_status = "UNVERIFIED_CALENDAR"
                        iv_class = "UNVERIFIED_CALENDAR"
                        all_covered = False
                    else:
                        expected_ts = expected_session_timestamps(
                            self.calendar, iv, from_ist, to_ist, require_verified=True
                        )
                        present_ts = {c.ts_utc for c in res.candles}
                        iv_missing = sum(1 for ts in expected_ts if ts not in present_ts)
                        total_missing += iv_missing
                        iv_covered = len(expected_ts) > 0 and iv_missing == 0 and res.out_of_session_count == 0

                        if cnt == 0 and res.out_of_session_count == 0:
                            iv_status = "EMPTY_RESPONSE"
                            iv_class = "EMPTY_RESPONSE"
                            all_covered = False
                        elif res.out_of_session_count > 0:
                            iv_status = "PARTIAL_DATA"
                            iv_class = "OUT_OF_SESSION_DETECTED"
                            all_covered = False
                        elif iv_covered:
                            iv_status = "VERIFIED_WITH_DATA"
                            iv_class = "COMPLETE"
                        elif inst.asset_class == AssetClass.OPTION:
                            iv_status = "UNKNOWN"
                            iv_class = "SPARSE_OPTION_UNKNOWN"
                            all_covered = False
                        else:
                            iv_status = "PARTIAL_DATA"
                            iv_class = "PARTIAL_DATA"
                            all_covered = False

                    entry["intervals"][iv] = {
                        "candle_count": cnt,
                        "expected_count": len(expected_ts),
                        "data_returned": cnt > 0,
                        "range_covered": iv_covered,
                        "missing_count": iv_missing,
                        "out_of_session_count": res.out_of_session_count,
                        "conflicting_duplicates": res.conflicting_duplicates,
                        "earliest": e0,
                        "latest": e1,
                        "oi_available": iv_oi,
                        "status": iv_status,
                        "coverage_classification": iv_class,
                    }
                    if cnt > 0:
                        has_data = True
                        entry["oi_available"] = entry["oi_available"] or iv_oi
                        entry["earliest"] = min(entry["earliest"], e0) if entry["earliest"] else e0
                        entry["latest"] = max(entry["latest"], e1) if entry["latest"] else e1
                except Exception as e:
                    all_covered = False
                    entry["intervals"][iv] = {
                        "candle_count": 0,
                        "data_returned": False,
                        "range_covered": False,
                        "missing_count": 0,
                        "earliest": None,
                        "latest": None,
                        "oi_available": False,
                        "status": "ERROR",
                        "error": str(e),
                    }
                    if "403" in str(e) or "auth" in str(e).lower() or "tokenexception" in str(e).lower():
                        has_auth_err = True
                    else:
                        has_other_err = True

            entry["data_returned"] = has_data
            entry["range_covered"] = has_data and all_covered and cal_verified
            entry["missing_count"] = total_missing
            entry["out_of_session_count"] = total_oos
            entry["conflicting_duplicates"] = total_conflicts

            if has_auth_err:
                entry["status"] = "BLOCKED_BY_AUTH"
                entry["coverage_classification"] = "BLOCKED_BY_AUTH"
            elif has_other_err:
                entry["status"] = "PARTIAL_ERROR"
                entry["coverage_classification"] = "PARTIAL_ERROR"
            elif not cal_verified:
                entry["status"] = "UNVERIFIED_CALENDAR"
                entry["coverage_classification"] = "UNVERIFIED_CALENDAR"
            elif not has_data and total_oos == 0:
                entry["status"] = "EMPTY_RESPONSE"
                entry["coverage_classification"] = "EMPTY_RESPONSE"
            elif total_oos > 0:
                entry["status"] = "PARTIAL_DATA"
                entry["coverage_classification"] = "OUT_OF_SESSION_DETECTED"
            elif all_covered:
                entry["status"] = "VERIFIED_WITH_DATA"
                entry["coverage_classification"] = "COMPLETE"
            elif any(v.get("status") == "UNKNOWN" for v in entry["intervals"].values()) and not any(
                v.get("status") == "PARTIAL_DATA" for v in entry["intervals"].values()
            ):
                entry["status"] = "UNKNOWN"
                entry["coverage_classification"] = "SPARSE_OPTION_UNKNOWN"
            else:
                entry["status"] = "PARTIAL_DATA"
                entry["coverage_classification"] = "PARTIAL_DATA"
            report.append(entry)
        return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Kite historical intraday candle client (read-only).")
    p.add_argument("--instrument-id", help="Canonical instrument_id to inspect.")
    p.add_argument("--interval", default="5minute", choices=list(INTERVAL_MAX_DAYS.keys()))
    p.parse_args(argv)
    print("Use KiteHistoricalDataClient.coverage_preflight() or fetch_historical_candles() with a populated registry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
