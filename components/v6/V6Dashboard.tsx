"use client";

// V6 modules (PAPER TRADING): reads /api/py/v6/* and shows NOT CONNECTED / NOT ACTIVE / NOT READY states
// instead of numbers whenever the backend has none.
import { Fragment, useCallback, useEffect, useState } from "react";
import { errText, v6Get } from "@/lib/v6/api";
import type { BookDetail, BookStatus, DataHealth, Performance, Signal, Status, Trade } from "@/lib/v6/types";
import Backtests from "@/components/v6/Backtests";

const TABS = ["Overview", "Accounts", "Positions", "Trades", "Agentic Workflow", "Signals", "Data health",
  "Performance", "Backtesting", "System"] as const;
type Tab = (typeof TABS)[number];
const BOOK_ORDER = ["INDIA", "FNO", "US", "USFNO", "CRYPTO"];

const NA = <span className="muted">—</span>;
const m = (v: string | null | undefined, cur?: string) =>
  v === null || v === undefined ? NA : <span className="mono">{cur ? `${v} ${cur}` : v}</span>;

function StateNotice({ label, reason }: { label: string; reason?: string | null }) {
  const cls = label === "V6 SMC Scanner" ? "ok" : "bad";
  return (
    <div className={`notice ${cls}`} role="status">
      <b>{label}</b>{reason ? <> · {reason}</> : null}
    </div>
  );
}

function Table({ rows, cols }: { rows: Record<string, unknown>[]; cols: string[] }) {
  if (!rows.length) return <p className="muted small">No records.</p>;
  return (
    <div className="tablewrap">
      <table>
        <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{cols.map((c) => {
              const v = r[c];
              return <td key={c} className="mono small">{v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v)}</td>;
            })}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BookCard({ b }: { b: BookStatus }) {
  const s = b.summary;
  return (
    <section className="panel">
      <div className="panel-head">
        <h3>{b.label} <span className="chip">{b.book_id}</span></h3>
        <span className={`chip ${b.state === "LOADED" ? "good" : "warn"}`}>{b.state === "LOADED" ? "LOADED" : b.state === "NOT_INITIALISED" ? "NOT INITIALISED" : "NOT READY"}</span>
      </div>
      <div className="grid-2 small">
        <div>Budget</div><div>{m(b.starting_budget, b.currency)}</div>
        {s ? (
          <>
            <div>Equity</div><div>{m(s.equity, b.currency)}{s.mtm_status !== "OK" ? <span className="muted"> ({s.mtm_status})</span> : null}</div>
            <div>Cash</div><div>{m(s.cash, b.currency)}</div>
            <div>Available balance</div><div>{m(s.available_balance, b.currency)}</div>
            <div>Committed</div><div>{m(s.committed_capital, b.currency)}</div>
            <div>Realized P&amp;L</div><div>{m(s.realized_pnl, b.currency)}</div>
            <div>Unrealized P&amp;L</div><div>{m(s.unrealized_pnl, b.currency)}</div>
            <div>Daily P&amp;L</div><div>{m(s.daily_pnl, b.currency)}</div>
            <div>Fees</div><div>{m(s.fees_total, b.currency)}</div>
            <div>Open / closed</div><div className="mono">{s.open_positions} / {s.closed_trades}</div>
            <div>Win rate</div><div>{s.win_rate_pct === null ? NA : m(`${s.win_rate_pct}%`)}</div>
            <div>Open position</div><div>{s.open_position_side ?? NA}</div>
            {Object.entries(s.by_side ?? {}).map(([k, v]) => (
              <Fragment key={k}>
                <div>{k} realized ({v.closed_trades} trades, {v.eod_flatten} EOD)</div><div>{m(v.realized_pnl, b.currency)}</div>
              </Fragment>
            ))}
            <div>Max drawdown</div><div>{m(`${s.max_drawdown_pct}%`)}</div>
          </>
        ) : (
          <><div>Status</div><div className="muted">{b.reason}</div></>
        )}
      </div>
      <p className="muted small">Budget decision: {b.budget_decision}</p>
    </section>
  );
}

export default function V6Dashboard() {
  const [tab, setTab] = useState<Tab>("Overview");
  const [status, setStatus] = useState<Status | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [book, setBook] = useState("US");
  const [detail, setDetail] = useState<BookDetail | null>(null);
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [health, setHealth] = useState<DataHealth | null>(null);
  const [perf, setPerf] = useState<Performance | null>(null);

  const load = useCallback(async () => {
    try {
      const [st, d, sg, h, p] = await Promise.all([
        v6Get<Status>("/status"), v6Get<BookDetail>(`/books/${book}`), v6Get<Signal[]>(`/signals/${book}?limit=200`),
        v6Get<DataHealth>("/data-health"), v6Get<Performance>(`/performance/${book}`),
      ]);
      setStatus(st); setDetail(d); setSignals(sg); setHealth(h); setPerf(p); setErr(null);
    } catch (e) {
      setErr(errText(e)); setStatus(null);
    }
  }, [book]);

  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  const label = err ? "V6 NOT CONNECTED" : status?.scanner.label ?? "V6 NOT CONNECTED";
  const reason = err ? `V6 API unreachable: ${err}` : status?.scanner.reason;
  const books = status ? BOOK_ORDER.map((b) => status.books[b]).filter(Boolean) : [];
  const trades: Trade[] = detail?.trades ?? [];
  const open = trades.filter((t) => t.status === "OPEN");
  const closed = trades.filter((t) => t.status !== "OPEN");

  return (
    <>
      <div className="seg" role="tablist" aria-label="V6 sections">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      <StateNotice label={label} reason={reason} />

        {["Positions", "Trades", "Signals", "Performance"].includes(tab) && (
          <div className="seg" role="tablist" aria-label="Book">
            {BOOK_ORDER.map((b) => (
              <button key={b} role="tab" aria-selected={book === b} onClick={() => setBook(b)}>{b}</button>
            ))}
          </div>
        )}

        <div className="pane">
          {tab === "Overview" && (
            <>
              {status && (
                <section className="panel">
                  <div className="panel-head"><h3>Readiness</h3></div>
                  {Object.values(status.readiness).map((r) => (
                    <div key={r.book_id} className={`notice ${r.ready ? "ok" : "bad"}`}>
                      <b>{r.book_id}: {r.ready ? "READY" : "NOT READY"}</b>
                      {!r.ready && <ul className="small">{r.blockers.map((x) => <li key={x}>{x}</li>)}</ul>}
                      {r.short_blockers && r.short_blockers.length > 0 && (
                        <>
                          <div className="small"><b>Short side: NOT READY</b> (SELL entries refused; the long side is unaffected)</div>
                          <ul className="small">{r.short_blockers.map((x) => <li key={x}>{x}</li>)}</ul>
                        </>
                      )}
                    </div>
                  ))}
                  <p className="small muted">NYSE calendar: {status.calendar.verified ? "verified" : "NOT VERIFIED"}</p>
                </section>
              )}
              <div className="grid-2">{books.map((b) => <BookCard key={b.book_id} b={b} />)}</div>
            </>
          )}
          {tab === "Accounts" && <div className="grid-2">{books.map((b) => <BookCard key={b.book_id} b={b} />)}</div>}
          {tab === "Positions" && (
            detail?.state !== "LOADED" ? <p className="muted">{book}: {detail?.state ?? "NOT CONNECTED"} · no positions shown.</p>
              : <Table rows={open} cols={["setup_id", "instrument", "position_side", "quantity", "entry_fill", "sl", "tp", "entry_fee", "entry_fee_components", "entry_ts", "data_source"]} />
          )}
          {tab === "Trades" && (
            detail?.state !== "LOADED" ? <p className="muted">{book}: {detail?.state ?? "NOT CONNECTED"} · no trades shown.</p>
              : <>
                <Table rows={closed} cols={["setup_id", "instrument", "position_side", "quantity", "entry_fill", "exit_fill", "exit_reason", "exit_detail", "gross_pnl", "entry_fee", "exit_fee", "exit_fee_components", "realized_pnl"]} />
                <h4>Rejected by book gates</h4>
                <Table rows={detail.rejections ?? []} cols={["setup_id", "instrument", "code", "detail", "at"]} />
              </>
          )}
          {tab === "Agentic Workflow" && status && (
            <section className="panel">
              <div className="panel-head"><h3>Scanner identity (verified by the V6 backend)</h3></div>
              <div className="grid-2 small">
                <div>Label</div><div><b>{label}</b></div>
                <div>Scanner</div><div>{status.scanner.scanner_name ?? NA}</div>
                <div>Version</div><div>{status.scanner.scanner_version ?? NA}</div>
                <div>Mode</div><div>{status.scanner.execution_mode ?? NA}</div>
                <div>Paper only</div><div>{String(status.scanner.paper_only)}</div>
                <div>Places orders</div><div>{String(status.scanner.places_orders)}</div>
                <div>Package SHA-256</div><div className="mono">{status.scanner.package_sha256 ?? NA}</div>
                <div>Runner</div><div>{status.runner.state}{status.runner.reason ? ` · ${status.runner.reason}` : ""}</div>
              </div>
              {status.scanner.pipeline && <p className="small">Pipeline: {status.scanner.pipeline.join(" → ")}</p>}
            </section>
          )}
          {tab === "Signals" && (signals && signals.length
            ? <Table rows={signals} cols={["ts_utc", "instrument", "timeframe", "stage", "direction", "entry_reference", "stop_loss", "target", "result", "rejection_reason", "data_quality", "data_source", "book_decision", "shadow"]} />
            : <p className="muted">No V6 signals recorded for {book}.</p>)}
          {tab === "Data health" && (
            <section className="panel">
              <p>Runner: <b>{health?.runner ?? "NOT CONNECTED"}</b>{health?.reason ? ` · ${health.reason}` : ""}</p>
              <p className="small">Data source: <span className="mono">{health?.data_source ?? "—"}</span>. IEX is a single venue, not the consolidated tape; a missing bar is never filled in, it interrupts the stream.</p>
              <Table rows={Object.values(health?.feeds ?? {}).map((f) => ({ ...f, counts: f.counts }))} cols={["symbol", "state", "last_bar_start", "last_poll", "gaps", "missing_bars", "max_consecutive_missing", "fetch_errors", "last_fetch_error", "counts"]} />
            </section>
          )}
          {tab === "Performance" && (perf?.state === "LOADED" && perf.instruments
            ? <Table rows={Object.entries(perf.instruments).map(([k, v]) => ({ instrument: k, ...v }))} cols={["instrument", "trades", "wins", "win_rate_pct", "realized_pnl", "fees"]} />
            : <p className="muted">{book}: {perf?.state ?? "NOT CONNECTED"} · no performance figures.</p>)}
          {tab === "Backtesting" && <Backtests />}
          {tab === "System" && status && (
            <section className="panel small">
              <p>Data root: <span className="mono">{status.data_root.path}</span> ({status.data_root.exists ? "exists" : "missing"})</p>
              <p>paper_only={String(status.paper_only)} · places_orders={String(status.places_orders)}</p>
              <p>Generated: <span className="mono">{status.generated_at}</span></p>
            </section>
          )}
      </div>
    </>
  );
}
