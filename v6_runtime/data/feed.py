"""Completed-bar validation between a data provider and the portfolio, per instrument.

A provider bar becomes a Module A Candle only when it is complete (its end + settle time has passed), inside a
trading session, aligned to the session grid (proposed O-1 rule, NOT APPROVED, applied only when configured), newer
than every accepted bar and than the last data event, and valid OHLCV. Everything else is counted and reported, never
passed on. Staleness inside a session produces DATA_INTERRUPTED; the next valid bar produces DATA_RESUMED stamped at
that bar's open, so both events always lie inside the F-D2 window [close of the previous candle, open of the next].
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from scanner_v6.data.candle_models import Candle, CandleError
from scanner_v6.data.integrity import CandleUpdate, CompletedCandleGate
from scanner_v6.data.market_config import SessionCalendar, SessionKind

from .alpaca import Bar

ACCEPT, NOT_COMPLETE, DUPLICATE, REVISION, OUT_OF_SESSION, MISALIGNED, LATE, INVALID, TOO_OLD = (
    "ACCEPT", "NOT_COMPLETE", "DUPLICATE", "REVISION", "OUT_OF_SESSION", "MISALIGNED", "LATE", "INVALID", "TOO_OLD")


@dataclass
class FeedOutput:
    status: str
    candle: Optional[Candle] = None
    events: List[Tuple[str, datetime]] = field(default_factory=list)   # data events to apply BEFORE the candle
    detail: Optional[str] = None


class BarFeed:
    def __init__(self, symbol: str, timeframe: timedelta, session: SessionCalendar, settle_seconds: int,
                 stale_after_bars: int, alignment_rule: Optional[str]):
        if settle_seconds is None or stale_after_bars is None:
            raise ValueError("settle_seconds and stale_after_bars must be configured (owner-approved)")
        if isinstance(settle_seconds, bool) or not isinstance(settle_seconds, int) or settle_seconds < 0:
            raise ValueError("settle_seconds must be a non-negative integer, got %r" % (settle_seconds,))
        if isinstance(stale_after_bars, bool) or not isinstance(stale_after_bars, int) or stale_after_bars < 1:
            raise ValueError("stale_after_bars must be an integer >= 1, got %r" % (stale_after_bars,))
        if alignment_rule not in (None, "session_grid"):
            raise ValueError("unknown alignment rule %r" % alignment_rule)
        self.symbol, self.tf, self.session = symbol, timeframe, session
        self.settle = timedelta(seconds=int(settle_seconds))
        self.stale_after = int(stale_after_bars)
        self.alignment = alignment_rule
        self.gate = CompletedCandleGate()
        self.last: Optional[Bar] = None
        self.last_event_ts: Optional[datetime] = None
        self.interrupted = False
        self.counts: Counter = Counter()
        self.last_poll: Optional[datetime] = None
        self.gaps = 0                        # in-session holes between accepted bars
        self.missing_bars = 0
        self.max_consecutive_missing = 0
        self.last_gap: Optional[Dict[str, object]] = None
        self.fetch_errors = 0
        self.last_fetch_error: Optional[str] = None

    # ------------------------------------------------------------ session helpers
    def _session_of(self, t: datetime) -> Optional[Tuple[datetime, datetime]]:
        if self.session.kind is not SessionKind.EXCHANGE:
            return None
        j = self.session.session_index(t)
        return None if j is None else self.session.sessions[j]

    def resume_from(self, candles: Sequence[Candle], data_changes: Sequence[Any] = ()) -> None:
        """Restore gate, last bar and data-interruption state after replaying a persisted journal."""
        self.gate = CompletedCandleGate()
        self.gate._done = list(candles)
        if candles:
            c = candles[-1]
            self.last = Bar(self.symbol, c.ts, c.open, c.high, c.low, c.close, c.volume)
        else:
            self.last = None
        if data_changes:
            last_ev = data_changes[-1]
            self.last_event_ts = last_ev.ts
            self.interrupted = last_ev.state == "DATA_INTERRUPTED"
        else:
            self.last_event_ts = None
            self.interrupted = False

    def offer(self, bar: Bar, now: datetime) -> FeedOutput:
        self.last_poll = now
        end = bar.start + self.tf
        if now < end + self.settle:
            return self._count(FeedOutput(NOT_COMPLETE))
        if self.last is not None and bar.start <= self.last.start:
            if bar.start == self.last.start:
                same = (bar.open, bar.high, bar.low, bar.close, bar.volume) == (
                    self.last.open, self.last.high, self.last.low, self.last.close, self.last.volume)
                return self._count(FeedOutput(DUPLICATE if same else REVISION, detail=bar.start.isoformat()))
            return self._count(FeedOutput(LATE, detail="older than the last accepted bar"))
        if self.last_event_ts is not None and bar.start < self.last_event_ts:
            return self._count(FeedOutput(LATE, detail="older than the last data event"))
        sess = self._session_of(bar.start)
        if sess is None or end > sess[1]:
            return self._count(FeedOutput(OUT_OF_SESSION, detail=bar.start.isoformat()))
        if self.alignment == "session_grid" and (bar.start - sess[0]) % self.tf != timedelta(0):
            return self._count(FeedOutput(MISALIGNED, detail=bar.start.isoformat()))
        if now - (end + self.settle) > self.tf * self.stale_after:
            # a bar the runner could not have acted on in real time (it was down or the provider was late): never
            # traded retroactively; the hole becomes a data interruption when fresh bars arrive (fail closed)
            return self._count(FeedOutput(TOO_OLD, detail=bar.start.isoformat()))
        try:
            upd = CandleUpdate(bar.start, bar.open, bar.high, bar.low, bar.close, bar.volume, True)
        except CandleError as e:
            return self._count(FeedOutput(INVALID, detail=str(e)))
        events = []
        missing = self._missing_between(bar.start)
        if missing:
            # a bar the session grid expected never arrived (IEX publishes no bar for an interval without IEX trades):
            # nothing is filled in; the hole becomes a data interruption, so a pending entry that needed the missing
            # candle expires and no candle is invented (fail closed)
            self.gaps += 1
            self.missing_bars += missing
            self.max_consecutive_missing = max(self.max_consecutive_missing, missing)
            self.last_gap = {"after": self.last.start.isoformat(), "resumed": bar.start.isoformat(), "missing": missing}
            if not self.interrupted:
                events.append(("DATA_INTERRUPTED", self.last.start + self.tf))
                self.interrupted = True
        if self.interrupted:
            events.append(("DATA_RESUMED", bar.start))
            self.interrupted = False
            self.last_event_ts = bar.start
        c = self.gate.feed(upd)
        self.last = bar
        return self._count(FeedOutput(ACCEPT, candle=c, events=events))

    def _missing_between(self, start: datetime) -> int:
        """Session-grid bar starts strictly between the last accepted bar and `start` (0 for the first bar)."""
        if self.last is None:
            return 0
        if self.session.kind is SessionKind.CONTINUOUS:
            return max(0, (start - self.last.start) // self.tf - 1)
        n = 0
        for o, c in self.session.sessions:
            if o >= start:
                break
            if c <= self.last.start:
                continue
            t = o
            while t + self.tf <= c and t < start:
                if t > self.last.start:
                    n += 1
                t += self.tf
        return n

    def check_stale(self, now: datetime) -> Optional[Tuple[str, datetime]]:
        """DATA_INTERRUPTED (stamped `now`) when, inside a session, more than `stale_after` bars are overdue."""
        if self.interrupted or self.last is None:
            return None
        sess = self._session_of(now)
        if sess is None:
            return None
        expected_from = max(self.last.start + self.tf, sess[0])
        overdue = now - (expected_from + self.tf + self.settle)
        if overdue >= self.tf * self.stale_after:
            self.interrupted = True
            self.last_event_ts = now
            self.counts["STALE"] += 1
            return ("DATA_INTERRUPTED", now)
        return None

    def _count(self, out: FeedOutput) -> FeedOutput:
        self.counts[out.status] += 1
        return out

    def health(self) -> Dict[str, object]:
        return {"symbol": self.symbol, "state": "INTERRUPTED" if self.interrupted else "NORMAL",
                "last_bar_start": self.last.start.isoformat() if self.last else None,
                "last_poll": self.last_poll.isoformat() if self.last_poll else None, "counts": dict(self.counts),
                "gaps": self.gaps, "missing_bars": self.missing_bars,
                "max_consecutive_missing": self.max_consecutive_missing, "last_gap": self.last_gap,
                "fetch_errors": self.fetch_errors, "last_fetch_error": self.last_fetch_error}

    def fetch_failed(self, err: BaseException) -> None:
        """A poll that could not fetch: nothing is accepted; staleness (check_stale) then interrupts the stream."""
        self.fetch_errors += 1
        self.last_fetch_error = "%s: %s" % (type(err).__name__, str(err)[:160])
