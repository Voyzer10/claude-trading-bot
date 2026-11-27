"""Active NIFTY/BANKNIFTY option contract archival before expiry."""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..instruments import AssetClass, Instrument, InstrumentRegistry, InstrumentStatus, Market, Segment
from .config import IST_TZ, NSECalendar, UTC_TZ
from .contract_discovery import parse_kite_nfo_symbol
from .exceptions import KiteAdapterError, KiteInputError
from .historical import (
    _INTERVAL_MINUTES,
    HistoricalCandle,
    HistoricalFetchResult,
    KiteHistoricalDataClient,
    expected_session_timestamps,
)

ARCHIVE_STATUS_COMPLETE = "COMPLETE"
ARCHIVE_STATUS_PARTIAL = "PARTIAL"
ARCHIVE_STATUS_UNKNOWN = "UNKNOWN"
ARCHIVE_STATUS_UNAVAILABLE = "UNAVAILABLE"

ALLOWED_ARCHIVE_UNDERLYINGS = frozenset({"NIFTY", "BANKNIFTY"})


@dataclass(frozen=True)
class ContractSelectionPolicy:
    """Explicit policy controlling which active NIFTY/BANKNIFTY option contracts are archived."""

    underlyings: Tuple[str, ...] = ("NIFTY", "BANKNIFTY")
    min_strike: Optional[Decimal] = None
    max_strike: Optional[Decimal] = None
    max_days_to_expiry: Optional[int] = None
    include_expiries: Optional[Sequence[date]] = None
    allow_unbounded: bool = False

    def __post_init__(self) -> None:
        normalized = tuple(u.strip().upper() for u in self.underlyings)
        if not normalized or any(u not in ALLOWED_ARCHIVE_UNDERLYINGS for u in normalized):
            raise KiteInputError(
                f"ContractSelectionPolicy underlyings must be a non-empty subset of {sorted(ALLOWED_ARCHIVE_UNDERLYINGS)}; got {self.underlyings!r}"
            )


class OptionContractArchive:
    """Preserves intraday OHLCV+OI and token provenance for active option contracts before expiry."""

    def __init__(
        self,
        *,
        archive_db_path: str,
        registry: InstrumentRegistry,
        historical_client: KiteHistoricalDataClient,
        calendar: Optional[NSECalendar] = None,
    ) -> None:
        self.archive_db_path = archive_db_path
        self.registry = registry
        self.historical = historical_client
        self.calendar = calendar or NSECalendar()
        os.makedirs(os.path.dirname(os.path.abspath(archive_db_path)), exist_ok=True)
        self._conn = sqlite3.connect(archive_db_path, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS archived_contracts (
                    instrument_id TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    expiry_date TEXT NOT NULL,
                    last_trade_date TEXT,
                    instrument_token INTEGER,
                    snapshot_date TEXT,
                    final_session_archived INTEGER NOT NULL DEFAULT 0,
                    coverage_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                    calendar_verified INTEGER NOT NULL DEFAULT 0,
                    requested_from_utc TEXT,
                    requested_to_utc TEXT,
                    missing_count INTEGER NOT NULL DEFAULT 0,
                    first_candle_utc TEXT,
                    last_candle_utc TEXT,
                    candle_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, interval)
                );

                CREATE TABLE IF NOT EXISTS archived_candles (
                    instrument_id TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    ts_ist TEXT NOT NULL,
                    open TEXT NOT NULL,
                    high TEXT NOT NULL,
                    low TEXT NOT NULL,
                    close TEXT NOT NULL,
                    volume INTEGER NOT NULL,
                    oi INTEGER,
                    snapshot_date TEXT,
                    PRIMARY KEY (instrument_id, interval, ts_utc)
                );
                """
            )
            self._migrate_schema()

    def _migrate_schema(self) -> None:
        applied = {
            r[0] for r in self._conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        now_iso = datetime.now(timezone.utc).isoformat()
        if 1 not in applied:
            self._conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)", (now_iso,)
            )
        if 2 not in applied:
            existing_cols = {
                r[1] for r in self._conn.execute("PRAGMA table_info(archived_contracts)").fetchall()
            }
            v2_cols = {
                "coverage_status": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
                "calendar_verified": "INTEGER NOT NULL DEFAULT 0",
                "requested_from_utc": "TEXT",
                "requested_to_utc": "TEXT",
                "missing_count": "INTEGER NOT NULL DEFAULT 0",
                "first_candle_utc": "TEXT",
                "last_candle_utc": "TEXT",
            }
            for col, col_def in v2_cols.items():
                if col not in existing_cols:
                    self._conn.execute(f"ALTER TABLE archived_contracts ADD COLUMN {col} {col_def}")
            self._conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (2, ?)", (now_iso,)
            )

    def close(self) -> None:
        self._conn.close()

    def _validate_in_scope_option(
        self,
        inst: Instrument,
        *,
        ref_date: Optional[date] = None,
        require_active: bool = False,
    ) -> str:
        """Strictly validate that inst is a NIFTY/BANKNIFTY IN option via underlying_instrument_id and symbol root."""
        if (
            inst.market != Market.IN
            or inst.asset_class != AssetClass.OPTION
            or inst.segment != Segment.IN_INDEX_OPTIONS
            or inst.exchange != "NFO"
        ):
            raise KiteInputError(f"Out-of-scope option for India archive: {inst.instrument_id}")
        if not inst.underlying_instrument_id:
            raise KiteInputError(f"Option missing underlying_instrument_id: {inst.instrument_id}")
        und = self.registry.get(inst.underlying_instrument_id)
        if und is None:
            raise KiteInputError(
                f"Option underlying_instrument_id not found in registry: {inst.underlying_instrument_id}"
            )
        if (
            und.market != Market.IN
            or und.asset_class != AssetClass.INDEX
            or und.segment != Segment.IN_INDEX
            or und.canonical_symbol not in ALLOWED_ARCHIVE_UNDERLYINGS
        ):
            raise KiteInputError(
                f"Option underlying {und.canonical_symbol!r} is outside NIFTY/BANKNIFTY scope: {inst.instrument_id}"
            )
        itype = "CE" if (inst.option_right and inst.option_right.value == "CALL") else "PE"
        parsed = parse_kite_nfo_symbol(inst.trading_symbol or inst.canonical_symbol, und.canonical_symbol, itype)
        if parsed is None or parsed.root != und.canonical_symbol:
            raise KiteInputError(
                f"Option symbol {inst.canonical_symbol!r} does not match underlying {und.canonical_symbol!r}"
            )
        if require_active:
            if not inst.is_active or inst.instrument_status == InstrumentStatus.EXPIRED:
                raise KiteInputError(f"Inactive or expired option rejected: {inst.instrument_id}")
            check_date = ref_date or datetime.now(IST_TZ).date()
            exp = inst.last_trade_date or inst.expiry_date
            if exp is not None and exp < check_date:
                raise KiteInputError(f"Expired option ({exp.isoformat()} < {check_date.isoformat()}) rejected: {inst.instrument_id}")
        return und.canonical_symbol

    def select_contracts(
        self,
        policy: Optional[ContractSelectionPolicy] = None,
        *,
        as_of_date: Optional[date] = None,
    ) -> List[Instrument]:
        """Select active IN NIFTY/BANKNIFTY option contracts matching the explicit ContractSelectionPolicy."""
        if policy is None:
            raise KiteInputError(
                "Explicit ContractSelectionPolicy is required before archiving options (no unbounded default)"
            )
        ref_date = as_of_date or datetime.now(IST_TZ).date()
        all_opts = [
            i for i in self.registry.list_by_asset_class(AssetClass.OPTION)
            if i.market == Market.IN and i.is_active
        ]
        if (
            not policy.allow_unbounded
            and policy.min_strike is None
            and policy.max_strike is None
            and policy.max_days_to_expiry is None
            and policy.include_expiries is None
        ):
            raise KiteInputError(
                f"Unbounded option archival refused ({len(all_opts)} eligible active options); "
                "specify strike/expiry bounds or set allow_unbounded=True"
            )

        allowed_unds = {u.strip().upper() for u in policy.underlyings}
        selected: List[Instrument] = []
        for opt in all_opts:
            try:
                root = self._validate_in_scope_option(opt, ref_date=ref_date, require_active=True)
            except KiteInputError:
                continue
            if root not in allowed_unds:
                continue
            if policy.min_strike is not None and opt.strike_price < policy.min_strike:
                continue
            if policy.max_strike is not None and opt.strike_price > policy.max_strike:
                continue
            if policy.include_expiries is not None and opt.expiry_date not in set(policy.include_expiries):
                continue
            if policy.max_days_to_expiry is not None and opt.expiry_date is not None:
                if (opt.expiry_date - ref_date).days > policy.max_days_to_expiry:
                    continue
            selected.append(opt)
        return selected

    def dry_run_report(
        self,
        policy: Optional[ContractSelectionPolicy] = None,
        *,
        as_of_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        eligible = [
            i for i in self.registry.list_by_asset_class(AssetClass.OPTION)
            if i.market == Market.IN and i.is_active
        ]
        if policy is None:
            return {
                "eligible_active_options": len(eligible),
                "selected_count": 0,
                "policy_required": True,
                "message": "Provide a ContractSelectionPolicy to select contracts for archival.",
            }
        chosen = self.select_contracts(policy, as_of_date=as_of_date)
        return {
            "eligible_active_options": len(eligible),
            "selected_count": len(chosen),
            "selected_ids": [c.instrument_id for c in chosen],
            "policy_required": False,
        }

    def archive_contracts(
        self,
        contracts: Sequence[Instrument],
        *,
        interval: str = "minute",
        from_datetime: datetime,
        to_datetime: datetime,
        include_oi: bool = True,
    ) -> List[Dict[str, Any]]:
        from_utc = from_datetime.astimezone(UTC_TZ) if from_datetime.tzinfo else from_datetime.replace(tzinfo=IST_TZ).astimezone(UTC_TZ)
        to_utc = to_datetime.astimezone(UTC_TZ) if to_datetime.tzinfo else to_datetime.replace(tzinfo=IST_TZ).astimezone(UTC_TZ)

        results: List[Dict[str, Any]] = []
        for inst in contracts:
            self._validate_in_scope_option(inst, require_active=False)
            tok = (inst.metadata or {}).get("instrument_token")
            snap_date = (inst.metadata or {}).get("snapshot_date")
            now_iso = datetime.now(timezone.utc).isoformat()
            fetch_error: Optional[str] = None
            try:
                res = self.historical.fetch_historical_candles(
                    inst.instrument_id, interval, from_utc, to_utc, include_oi=include_oi
                )
                candles = res.candles
                coverage_status, final_complete, cal_verified, missing_cnt = self._evaluate_session_coverage(
                    inst, interval, res, from_utc, to_utc
                )
            except KiteAdapterError as e:
                fetch_error = str(e)
                candles = []
                cal_verified = self.calendar.is_verified_for_range(
                    from_utc.astimezone(IST_TZ).date(), to_utc.astimezone(IST_TZ).date()
                )
                coverage_status = ARCHIVE_STATUS_UNAVAILABLE
                final_complete = False
                missing_cnt = 0

            first_utc = candles[0].ts_utc.isoformat() if candles else None
            last_utc = candles[-1].ts_utc.isoformat() if candles else None

            with self._conn:
                if candles:
                    self._conn.executemany(
                        """
                        INSERT OR IGNORE INTO archived_candles (
                            instrument_id, interval, ts_utc, ts_ist, open, high, low, close, volume, oi, snapshot_date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                c.instrument_id,
                                c.interval,
                                c.ts_utc.isoformat(),
                                c.ts_ist.isoformat(),
                                str(c.open),
                                str(c.high),
                                str(c.low),
                                str(c.close),
                                c.volume,
                                c.oi,
                                c.snapshot_date,
                            )
                            for c in candles
                        ],
                    )
                cnt = self._conn.execute(
                    "SELECT COUNT(*) FROM archived_candles WHERE instrument_id = ? AND interval = ?",
                    (inst.instrument_id, interval),
                ).fetchone()[0]
                self._conn.execute(
                    """
                    INSERT INTO archived_contracts (
                        instrument_id, interval, expiry_date, last_trade_date,
                        instrument_token, snapshot_date, final_session_archived,
                        coverage_status, calendar_verified, requested_from_utc, requested_to_utc,
                        missing_count, first_candle_utc, last_candle_utc, candle_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(instrument_id, interval) DO UPDATE SET
                        final_session_archived = excluded.final_session_archived,
                        coverage_status = excluded.coverage_status,
                        calendar_verified = excluded.calendar_verified,
                        requested_from_utc = excluded.requested_from_utc,
                        requested_to_utc = excluded.requested_to_utc,
                        missing_count = excluded.missing_count,
                        first_candle_utc = COALESCE(excluded.first_candle_utc, archived_contracts.first_candle_utc),
                        last_candle_utc = COALESCE(excluded.last_candle_utc, archived_contracts.last_candle_utc),
                        candle_count = excluded.candle_count,
                        updated_at = excluded.updated_at
                    """,
                    (
                        inst.instrument_id,
                        interval,
                        inst.expiry_date.isoformat() if inst.expiry_date else "",
                        inst.last_trade_date.isoformat() if inst.last_trade_date else None,
                        int(tok) if tok is not None else None,
                        snap_date,
                        1 if final_complete else 0,
                        coverage_status,
                        1 if cal_verified else 0,
                        from_utc.isoformat(),
                        to_utc.isoformat(),
                        int(missing_cnt),
                        first_utc,
                        last_utc,
                        int(cnt),
                        now_iso,
                    ),
                )
            item: Dict[str, Any] = {
                "instrument_id": inst.instrument_id,
                "candles_fetched": len(candles),
                "total_archived": int(cnt),
                "final_session_archived": final_complete,
                "coverage_status": coverage_status,
                "calendar_verified": cal_verified,
                "missing_count": int(missing_cnt),
                "requested_from_utc": from_utc.isoformat(),
                "requested_to_utc": to_utc.isoformat(),
            }
            if fetch_error is not None:
                item["error"] = fetch_error
            results.append(item)
        return results

    def _evaluate_session_coverage(
        self,
        inst: Instrument,
        interval: str,
        res: HistoricalFetchResult,
        from_utc: datetime,
        to_utc: datetime,
    ) -> Tuple[str, bool, bool, int]:
        from_ist = from_utc.astimezone(IST_TZ)
        to_ist = to_utc.astimezone(IST_TZ)
        cal_verified = self.calendar.is_verified_for_range(from_ist.date(), to_ist.date())
        if not cal_verified:
            return (ARCHIVE_STATUS_UNKNOWN, False, False, len(res.missing_timestamps))

        last_day = inst.last_trade_date or inst.expiry_date or to_ist.date()
        bounds = self.calendar.session_bounds(last_day, require_verified=True)
        if bounds is None:
            return (ARCHIVE_STATUS_UNKNOWN, False, True, len(res.missing_timestamps))

        day_candles = [c for c in res.candles if c.ts_ist.date() == last_day]
        if not day_candles:
            return (ARCHIVE_STATUS_UNKNOWN, False, True, len(res.missing_timestamps))

        expected_ts = expected_session_timestamps(
            self.calendar, interval, bounds[0], bounds[1], require_verified=True
        )
        expected_open_utc = expected_ts[0]
        expected_last_utc = expected_ts[-1]
        expected_count = len(expected_ts)

        open_utc = bounds[0].astimezone(UTC_TZ)
        close_utc = bounds[1].astimezone(UTC_TZ)
        req_covers_session = (from_utc <= open_utc) and (to_utc >= close_utc)
        has_open = day_candles[0].ts_utc == expected_open_utc
        has_close = day_candles[-1].ts_utc == expected_last_utc
        present_ts = {c.ts_utc for c in day_candles}
        missing_in_session = [ts for ts in expected_ts if ts not in present_ts]

        if req_covers_session and has_open and has_close and not missing_in_session and len(day_candles) >= expected_count:
            return (ARCHIVE_STATUS_COMPLETE, True, True, 0)

        return (ARCHIVE_STATUS_PARTIAL, False, True, len(missing_in_session))

    def get_archived_status(self, instrument_id: str, interval: str = "minute") -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM archived_contracts WHERE instrument_id = ? AND interval = ?",
            (instrument_id, interval),
        ).fetchone()
        return dict(row) if row else None
