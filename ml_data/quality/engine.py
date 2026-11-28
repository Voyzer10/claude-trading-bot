"""Cross-market DataQualityEngine evaluating structural, OHLC, temporal, and market-specific rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from ..calendars.base import ExchangeCalendar
from ..instruments import AssetClass, InstrumentRegistry
from ..storage.canonical_schema import CanonicalCandle
from .rules import check_market_specific_rules, check_temporal_sanity, check_tick_size_compliance


@dataclass(frozen=True)
class RejectedRecord:
    instrument_id: str
    timestamp_start_utc: str
    reason: str


@dataclass
class QualityReport:
    status: str
    total_input: int
    valid_count: int
    rejected_count: int
    duplicate_count: int
    valid_candles: List[CanonicalCandle] = field(default_factory=list)
    rejected_records: List[RejectedRecord] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "total_input": self.total_input,
            "valid_count": self.valid_count,
            "rejected_count": self.rejected_count,
            "duplicate_count": self.duplicate_count,
            "quality_flags": list(self.quality_flags),
        }


class DataQualityEngine:
    """Evaluates CanonicalCandle batches with market-aware calendar and instrument rules."""

    def __init__(
        self,
        *,
        registry: Optional[InstrumentRegistry] = None,
        calendar: Optional[ExchangeCalendar] = None,
    ) -> None:
        self.registry = registry
        self.calendar = calendar

    def evaluate_candles(
        self,
        candles: Sequence[CanonicalCandle],
        *,
        pagination_complete: bool = True,
        expected_count: Optional[int] = None,
        now_utc: Optional[datetime] = None,
        allowed_sessions: Optional[Sequence[str]] = None,
    ) -> QualityReport:
        if not candles:
            status = "PAGINATION_INCOMPLETE" if not pagination_complete else "EMPTY_RESPONSE"
            return QualityReport(
                status=status,
                total_input=0,
                valid_count=0,
                rejected_count=0,
                duplicate_count=0,
            )

        seen_keys = set()
        valid: List[CanonicalCandle] = []
        rejected: List[RejectedRecord] = []
        dups = 0
        all_flags = set()
        ref_now = now_utc or datetime.now(timezone.utc)
        allowed_set = {s.strip().upper() for s in allowed_sessions} if allowed_sessions is not None else None

        for c in sorted(candles, key=lambda x: (x.instrument_id, x.timestamp_start_utc)):
            inst = self.registry.get(c.instrument_id) if self.registry is not None else None
            if self.registry is not None and inst is None:
                rejected.append(RejectedRecord(c.instrument_id, c.timestamp_start_utc.isoformat(), "unknown_instrument"))
                continue

            dkey = (c.instrument_id, c.timeframe, c.adjustment_mode, c.timestamp_start_utc)
            if dkey in seen_keys:
                dups += 1
                continue
            seen_keys.add(dkey)

            t_flags = check_temporal_sanity(c, now_utc=ref_now)
            if "future_event_timestamp" in t_flags:
                rejected.append(RejectedRecord(c.instrument_id, c.timestamp_start_utc.isoformat(), "future_event_timestamp"))
                continue

            tick_err = check_tick_size_compliance(c, inst)
            if tick_err is not None:
                rejected.append(RejectedRecord(c.instrument_id, c.timestamp_start_utc.isoformat(), tick_err))
                continue

            if self.calendar is not None:
                expected_trade_date = self.calendar.trade_date_for(c.timestamp_start_utc)
                if c.trading_date != expected_trade_date:
                    rejected.append(
                        RejectedRecord(
                            c.instrument_id,
                            c.timestamp_start_utc.isoformat(),
                            f"trading_date_mismatch:claimed={c.trading_date.isoformat()},actual={expected_trade_date.isoformat()}",
                        )
                    )
                    continue
                if not self.calendar.is_trading_day(c.trading_date, require_verified=False):
                    rejected.append(RejectedRecord(c.instrument_id, c.timestamp_start_utc.isoformat(), "non_trading_day_or_holiday"))
                    continue
                actual_session = self.calendar.classify_session(c.timestamp_start_utc, require_verified=False)
                if actual_session in ("CLOSED", "MAINTENANCE_BREAK"):
                    rejected.append(RejectedRecord(c.instrument_id, c.timestamp_start_utc.isoformat(), f"closed_or_maintenance_session:{actual_session}"))
                    continue
                if c.trading_session.strip().upper() != actual_session.strip().upper():
                    rejected.append(
                        RejectedRecord(
                            c.instrument_id,
                            c.timestamp_start_utc.isoformat(),
                            f"session_mismatch:claimed={c.trading_session},actual={actual_session}",
                        )
                    )
                    continue
                if allowed_set is not None and actual_session.strip().upper() not in allowed_set:
                    rejected.append(
                        RejectedRecord(
                            c.instrument_id,
                            c.timestamp_start_utc.isoformat(),
                            f"disallowed_session:{actual_session}",
                        )
                    )
                    continue

            m_flags = check_market_specific_rules(c, inst)
            for fl in t_flags + m_flags:
                all_flags.add(fl)
            valid.append(c)

        cal_verified = True
        if self.calendar is not None and valid:
            min_date = min(c.trading_date for c in valid)
            max_date = max(c.trading_date for c in valid)
            cal_verified = self.calendar.is_verified_for_range(min_date, max_date)

        if not valid and rejected:
            status = "INVALID_DATA"
        elif not pagination_complete:
            status = "PAGINATION_INCOMPLETE"
        elif not cal_verified:
            status = "UNVERIFIED_CALENDAR"
        elif expected_count is not None and len(valid) < expected_count:
            # Sparse options may be UNKNOWN (no-trade ambiguity), whereas continuous/equity gaps are PARTIAL_DATA
            first_inst = self.registry.get(valid[0].instrument_id) if (self.registry and valid) else None
            if first_inst is not None and first_inst.asset_class == AssetClass.OPTION:
                status = "UNKNOWN"
            else:
                status = "PARTIAL_DATA"
        elif rejected:
            status = "PARTIAL_DATA"
        else:
            status = "VERIFIED_WITH_DATA"

        return QualityReport(
            status=status,
            total_input=len(candles),
            valid_count=len(valid),
            rejected_count=len(rejected),
            duplicate_count=dups,
            valid_candles=valid,
            rejected_records=rejected,
            quality_flags=sorted(all_flags),
        )
