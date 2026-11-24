"""V6 paper runner (US Stocks first).

    python -m v6_runtime.runner status                       read-only status (no network)
    python -m v6_runtime.runner init-book --book US --owner-authorised
                                                             create ONE fresh book (owner only; refuses if it exists)
    python -m v6_runtime.runner run --book US                live paper loop; refuses unless every gate is met:
        data root exists, runtime/ENABLED_<BOOK> exists (owner switch), the book exists and reconciles,
        us_stocks.json complete and approved, NYSE calendar verified, V6 data-only credential present.

There is no order path: the runner only reads market data (Alpaca data host) and writes the V6 data root.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time as _time
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from . import identity, status as v6status, us_stocks
from .data.alpaca import AlpacaBars, Bar, load_credential
from .data.feed import ACCEPT, BarFeed
from .ledger import BookLedger
from .paths import DataRoot
from .portfolio import Portfolio


class NotReady(RuntimeError):
    pass


def gates(root: DataRoot, book: str) -> List[str]:
    """Every reason the live loop must not start (empty = may start)."""
    if book != "US":
        return ["only the US Stocks book has a runner; %s is not implemented" % book]
    out = []
    if not root.exists():
        return ["V6 data root %s does not exist" % root.root]
    if not os.path.exists(root.path("runtime", "ENABLED_%s" % book)):
        out.append("owner switch runtime/ENABLED_%s is absent (V6 NOT ACTIVE)" % book)
    if not BookLedger.exists(root, book):
        out.append("book %s is not initialised" % book)
    cal = us_stocks.load_calendar()
    cfg = us_stocks.load_config(root)
    out += us_stocks.readiness(cfg, cal, v6status.credential_present()).get("blockers", [])
    return out


class USRunner:
    """One poll cycle at a time; the clock and the data source are injected (tests use fixtures)."""

    def __init__(self, root: DataRoot, cfg: us_stocks.USStocksConfig, cal: Dict, source: Callable[..., List[Bar]],
                 start: date, end: date):
        self.root, self.cfg = root, cfg
        a = cfg.approved
        self.specs = us_stocks.instrument_specs(cfg, cal, start, end)
        self.ledger = BookLedger.load(root, "US")
        self.portfolio = Portfolio(root, self.ledger, self.specs)
        self.portfolio.recover()
        self.source = source
        self.tf = self.specs[0].market.timeframe
        self.feeds = {s.instrument_id: BarFeed(s.instrument_id, self.tf, s.market.session, a["bar_settle_seconds"],
                                               a["stale_after_bars"], a["alignment_rule"]) for s in self.specs}
        for iid, st in self.portfolio.streams.items():      # resume feeds after the journal replay
            if st.candles:
                c = st.candles[-1]
                self.feeds[iid].last = Bar(iid, c.ts, c.open, c.high, c.low, c.close, c.volume)

    def poll_once(self, now: datetime) -> Dict[str, object]:
        out = {"accepted": 0, "events": 0, "signals": 0}
        for iid in sorted(self.feeds):
            feed = self.feeds[iid]
            ev = feed.check_stale(now)
            if ev:
                self.portfolio.on_data_interrupted(iid, ev[1])
                out["events"] += 1
            since = feed.last.start + self.tf if feed.last else now - timedelta(hours=8)
            try:
                bars = self.source(iid, self.cfg.timeframe, since, now)
            except Exception as e:  # noqa: BLE001 - provider down / 403 / timeout: no bar is accepted, nothing is
                feed.fetch_failed(e)  # substituted (no other feed, no delayed fallback); staleness interrupts the stream
                out["fetch_errors"] = out.get("fetch_errors", 0) + 1
                continue
            for bar in bars:
                r = feed.offer(bar, now)
                if r.status != ACCEPT:
                    continue
                for state, ts in r.events:
                    (self.portfolio.on_data_interrupted if state == "DATA_INTERRUPTED"
                     else self.portfolio.on_data_resumed)(iid, ts)
                    out["events"] += 1
                out["signals"] += len(self.portfolio.on_candle(iid, r.candle))
                out["accepted"] += 1
        self.root.write_json_atomic(self.portfolio.mtm or {}, "runtime", "mtm_US.json")
        self.root.write_json_atomic(dict(identity.stamp(), at=now.isoformat(), pid=os.getpid(), book="US",
                                         data_source=us_stocks.feed_label(self.cfg.feed),
                                         feeds={k: f.health() for k, f in self.feeds.items()}),
                                    "runtime", "heartbeat.json")
        return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="v6_runtime.runner")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    ib = sub.add_parser("init-book")
    ib.add_argument("--book", required=True)
    ib.add_argument("--owner-authorised", action="store_true")
    rn = sub.add_parser("run")
    rn.add_argument("--book", required=True)
    rn.add_argument("--poll-seconds", type=int, default=30)
    a = p.parse_args(argv)
    root = DataRoot()
    if a.cmd == "status":
        print(json.dumps(v6status.overall(root), indent=1, default=str))
        return 0
    if a.cmd == "init-book":
        led = BookLedger.create(root, a.book, owner_authorised=a.owner_authorised, created_by="runner init-book")
        print(json.dumps(led.summary(), indent=1))
        return 0
    blockers = gates(root, a.book)
    if blockers:
        print(json.dumps({"status": "NOT READY", "book": a.book, "blockers": blockers}, indent=1))
        return 2
    cal = us_stocks.load_calendar()
    cfg = us_stocks.load_config(root)
    bars = AlpacaBars(load_credential(), cfg.feed)
    today = datetime.now(timezone.utc).date()
    runner = USRunner(root, cfg, cal, bars.fetch, today - timedelta(days=7), today + timedelta(days=7))
    while True:
        if gates(root, a.book):                   # the owner switch can stop the loop at any time
            return 3
        runner.poll_once(datetime.now(timezone.utc))
        _time.sleep(max(5, a.poll_seconds))


if __name__ == "__main__":
    sys.exit(main())
