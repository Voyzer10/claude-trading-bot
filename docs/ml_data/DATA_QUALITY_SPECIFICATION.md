# Cross-Market Data Quality & Reconciliation (`ml_data/quality`)

## 1. Quality Statuses
- `VERIFIED_WITH_DATA`, `PARTIAL_DATA`, `UNKNOWN`, `EMPTY_RESPONSE`, `BLOCKED_BY_AUTH`, `BLOCKED_BY_SUBSCRIPTION`, `UNSUPPORTED`, `UNVERIFIED_CALENDAR`, `PAGINATION_INCOMPLETE`, `INVALID_DATA`.

## 2. Market-Aware Rules
- **Structural & OHLC**: Unknown instrument rejection, duplicate detection, `high >= max(open, close, low)`, `low <= min(open, close, high)`, non-negative volume, tick-size compliance (`px % tick_size == 0`).
- **Temporal**: Future event timestamp rejection, negative receive latency flagging, calendar verification checks.
- **Market-Specific**: Option missing-OI flags & sparse no-trade `UNKNOWN` status, crypto inverse contract provenance, funding timestamp presence.
- **Reconciliation (`CrossMarketReconciler`)**: Detects unregistered instruments, non-UTC timestamps, missing counts, and multi-provider price discrepancies without silently picking one feed.
