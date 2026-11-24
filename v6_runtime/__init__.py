"""V6 PAPER-ONLY runtime: books and ledger, portfolio orchestration around Modules A-E, market data adapters and
readiness. Isolated from V4: it never imports V4 modules, never reads V4 data (trader/paper, trader/live) or V4
secrets, and has no order path. Persistent data lives only under the V6 data root (default /var/lib/trader-v6)."""
