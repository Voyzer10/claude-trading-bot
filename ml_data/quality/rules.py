"""Market-aware data quality status constants and validation rules."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from ..instruments import AssetClass, Instrument
from ..storage.canonical_schema import CanonicalCandle

QUALITY_STATUSES = frozenset({
    "VERIFIED_WITH_DATA",
    "PARTIAL_DATA",
    "UNKNOWN",
    "EMPTY_RESPONSE",
    "BLOCKED_BY_AUTH",
    "BLOCKED_BY_SUBSCRIPTION",
    "UNSUPPORTED",
    "UNVERIFIED_CALENDAR",
    "PAGINATION_INCOMPLETE",
    "INVALID_DATA",
})


def check_tick_size_compliance(candle: CanonicalCandle, inst: Optional[Instrument]) -> Optional[str]:
    if inst is None or inst.tick_size is None or inst.tick_size <= 0:
        return None
    tick = inst.tick_size
    for name, px in (("open", candle.open), ("high", candle.high), ("low", candle.low), ("close", candle.close)):
        if (px % tick) != Decimal("0"):
            return f"tick_size_violation:{name}:{px}%{tick}"
    return None


def check_temporal_sanity(candle: CanonicalCandle, *, now_utc: Optional[datetime] = None) -> List[str]:
    flags: List[str] = []
    ref = now_utc or datetime.now(timezone.utc)
    if candle.event_time_utc > ref:
        flags.append("future_event_timestamp")
    if candle.received_at_utc < candle.event_time_utc:
        flags.append("negative_receive_latency")
    return flags


def check_market_specific_rules(candle: CanonicalCandle, inst: Optional[Instrument]) -> List[str]:
    flags: List[str] = []
    if inst is not None and inst.asset_class == AssetClass.OPTION and candle.open_interest is None:
        flags.append("missing_oi")
    if candle.market == "CRYPTO" and inst is not None and inst.is_inverse and "inverse" not in candle.adjustment_mode:
        # Preserve linear/inverse provenance awareness
        flags.append("crypto_inverse_contract")
    if candle.funding_rate is not None and candle.funding_timestamp_utc is None:
        flags.append("funding_missing_timestamp")
    return flags
