"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Coin, CoinProfile, Decision, Position, Snapshot, SnapshotResponse } from "@/lib/types";
import { ago, currencyOf, duration, money, pct, price, timeIST } from "@/lib/format";
import ControlPanel from "@/components/ControlPanel";
import Performance from "@/components/Performance";
import Settings from "@/components/Settings";
import Operations, { useCommands } from "@/components/Operations";
import Backtest from "@/components/Backtest";
import Alerts from "@/components/Alerts";
import Agents from "@/components/Agents";
import SymbolIcon from "@/components/SymbolIcon";
import Zerodha from "@/components/Zerodha";
import { INDIA, useLiveTicks, type LiveTicks } from "@/lib/live";
import { errText } from "@/lib/api";

const POLL_MS = 30_000;
const STALE_MIN = 12; // the runner pushes every 5 minutes; silence beyond this means it stopped or the PC slept

// ------------------------------------------------------------------ page

export default function Dashboard() {
  const live = useLiveTicks();
  const [data, setData] = useState<SnapshotResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/py/snapshot", { cache: "no-store" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setData(await r.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const changed = useCallback(() => {
    load();
    setRefreshKey((k) => k + 1);
  }, [load]);

  useEffect(() => {
    load();
    const id = setInterval(() => { load(); setRefreshKey((k) => k + 1); }, POLL_MS);
    const t = setInterval(() => setTick((x) => x + 1), 15_000);
    return () => {
      clearInterval(id);
      clearInterval(t);
    };
  }, [load]);

  const snap = data?.snapshot ?? null;
  const nowSec = (data?.now ?? Math.floor(Date.now() / 1000)) + tick * 0; // re-render on tick
  const ageSec = data?.received ? Math.floor(Date.now() / 1000) - data.received : null;

  return (
    <div className="wrap">
      <header className="topbar">
        <div className="titleblock">
          <h1>Trader Bot Dashboard</h1>
          <div className="muted small">Testing phase: paper trading (no broker connected yet) · times in IST</div>
        </div>
        <div className="topbar-cta topbar-actions">
          <a className="btn" href="/api/py/ops/download/all.zip">Download all data</a>
          <a className="btn primary" href="#backtest">Run a backtest</a>
        </div>
      </header>
      <nav className="nav" aria-label="Sections">
          <a href="#performance">Performance</a>
          <a href="#control">Control</a>
          <a href="#runner">Runner</a>
          <a href="#agents">Agents</a>
          <a href="#ledger">Positions</a>
          <a href="#coins">Coins</a>
          <a href="#reasons">Skip reasons</a>
          <a href="#decisions">Decisions</a>
          <a href="#logs">Logs</a>
          <a href="#settings">Settings</a>
          <a href="#operations">Operations</a>
          <a href="#backtest">Backtest</a>
          <a href="#alerts">Alerts</a>
      </nav>

      {error && (
        <div className="notice bad">
          Could not reach the dashboard API ({error}). Retrying every {POLL_MS / 1000}s.
        </div>
      )}
      {!snap && !error && data && <SetupHelp />}
      {!data && !error && <div className="notice">Loading…</div>}
      {data && <Performance refreshKey={refreshKey} />}
      {snap && (
        <>
          <ControlPanel />
          <Zerodha live={live} />
          <RunnerSection snap={snap} ageSec={ageSec} />
          <Agents refreshKey={refreshKey} />
          <MarketsStrip snap={snap} />
          <LedgerSection snap={snap} onChange={changed} live={live} />
          <CoinsSection snap={snap} />
          <div className="grid-2">
            <ReasonsSection snap={snap} />
            <RulesSection snap={snap} />
          </div>
          <DecisionsSection decisions={snap.decisions} />
          <LogsSection snap={snap} />
        </>
      )}
      {data && (
        <>
          <Settings />
          <Operations onChange={changed} />
          <Backtest />
          <Alerts />
        </>
      )}
      {snap && (
        <>
          <footer className="muted small">
            Snapshot built {timeIST(snap.generated_at, true)} · received {ageSec !== null ? ago(ageSec) : "—"} · page
            refreshes every {POLL_MS / 1000}s · server time {timeIST(new Date(nowSec * 1000).toISOString())}
          </footer>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ runner

function RunnerSection({ snap, ageSec }: { snap: Snapshot; ageSec: number | null }) {
  const r = snap.runner;
  const stale = ageSec === null || ageSec > STALE_MIN * 60;
  const started = r.started_at ? new Date(r.started_at) : null;
  const runFor = started ? Date.now() - started.getTime() : 0;
  const lastSeg = r.segments[r.segments.length - 1];
  return (
    <section id="runner" className="panel" aria-labelledby="runner-h">
      <div className="panel-head">
        <div>
          <h2 id="runner-h">Runner{snap.runner.mode ? ` · ${({ cloud: "cloud (Vercel)", vps: "VPS", pc: "PC" } as Record<string, string>)[snap.runner.mode] ?? snap.runner.mode}` : ""}</h2>
          <p>{r.status ?? "unknown"}</p>
        </div>
        {stale ? (
          <span className="chip c-bad">Not reporting</span>
        ) : (
          <span className="chip c-good">Active</span>
        )}
      </div>
      {stale && (
        <div className="notice bad" style={{ marginBottom: 12 }}>
          No update for {ageSec !== null ? ago(ageSec) : "a long time"}.{" "}
          {snap.runner.mode === "cloud"
            ? "The scheduler (cron-job.org or the GitHub Action) has stopped calling /api/py/cron/tick, or the tick is failing: check /api/py/health."
            : snap.runner.mode === "vps"
              ? "The runner service may have stopped: see Operations below, or run sudo systemctl status trader-runner on the VPS."
              : "The PC runner window may be closed, or the PC asleep."}
        </div>
      )}
      <div className="runner">
        <div className={`stat stripe ${stale ? "s-bad" : "s-good"}`}>
          <span className="label">Active since</span>
          <span className="value">{timeIST(r.started_at, true)}</span>
          <span className="sub">
            {stale ? "last heard " + (ageSec !== null ? ago(ageSec) : "—") : "running for " + duration(runFor)}
          </span>
        </div>
        <div className="stat">
          <span className="label">Uptime, last 24 h</span>
          <span className="value">{r.uptime_24h_hours.toFixed(1)} h</span>
          <span className="sub">{Math.round((r.uptime_24h_hours / 24) * 100)}% of the day</span>
        </div>
        <div className="stat">
          <span className="label">Last cycle</span>
          <span className="value">{timeIST(r.updated)}</span>
          <span className="sub">next at {timeIST(r.next_run)}</span>
        </div>
        <div className="stat">
          <span className="label">Markets in the runner</span>
          <span className="value" style={{ fontSize: 16 }}>{(r.markets ?? []).join(" · ") || "—"}</span>
          <span className="sub">pid {r.pid ?? "—"} · {r.errors.length} errors</span>
        </div>
        <div className="stat">
          <span className="label">Decisions logged</span>
          <span className="value">{snap.counts.decisions_total}</span>
          <span className="sub">
            {snap.counts.traded} traded · {snap.counts.skipped} skipped · {snap.counts.blocked} blocked
          </span>
        </div>
      </div>
      <UptimeTimeline segments={r.segments} />
      {lastSeg && (
        <p className="muted small" style={{ margin: "6px 0 0" }}>
          Green = runner alive (from the log). Gaps are times it was stopped or the PC slept; the current run started{" "}
          {timeIST(r.started_at, true)}.
        </p>
      )}
      {r.errors.length > 0 && (
        <ul className="small" style={{ color: "var(--bad)", margin: "8px 0 0" }}>
          {r.errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function UptimeTimeline({ segments }: { segments: { start: string; end: string }[] }) {
  const end = Date.now();
  const span = 48 * 3600 * 1000;
  const start = end - span;
  const ticks = [0, 12, 24, 36, 48].map((h) => new Date(start + h * 3600 * 1000));
  return (
    <div style={{ marginTop: 14 }}>
      <div className="small muted">Last 48 hours</div>
      <div className="timeline" role="img" aria-label="Runner uptime over the last 48 hours">
        {segments.map((s, i) => {
          const a = Math.max(new Date(s.start).getTime(), start);
          const b = Math.min(new Date(s.end).getTime(), end);
          if (b <= a) return null;
          return (
            <span
              key={i}
              className="seg"
              title={`${timeIST(s.start, true)} → ${timeIST(s.end, true)}`}
              style={{ left: `${((a - start) / span) * 100}%`, width: `${Math.max(0.3, ((b - a) / span) * 100)}%` }}
            />
          );
        })}
      </div>
      <div className="timeline-axis">
        {ticks.map((t, i) => (
          <span key={i}>{timeIST(t.toISOString(), i === 0 || i === 2)}</span>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ markets

function modeChip(mode?: string) {
  if (!mode) return <span className="chip c-off">—</span>;
  if (mode.startsWith("auto")) return <span className="chip c-good">Auto paper</span>;
  if (mode.startsWith("log")) return <span className="chip c-warn">Log only</span>;
  return <span className="chip c-off">{mode}</span>;
}

function MarketsStrip({ snap }: { snap: Snapshot }) {
  const m = snap.markets;
  const cards: { name: string; mode?: string; note: string }[] = [
    {
      name: "Crypto",
      mode: m.CRYPTO?.mode as string,
      note: `${snap.crypto.universe.length} coins · shorts ${m.CRYPTO?.shorts ? "on" : "off"}`,
    },
    { name: "US stocks", mode: m.US?.mode as string, note: `${(m.US?.status as string) ?? "—"} · last scan ${(m.US?.as_of as string) ?? "—"}` },
    {
      name: "NSE stocks",
      mode: m.NSE?.mode as string,
      note: `${(m.NSE?.universe as number) ?? "—"} stocks · last ORB ${timeIST(m.NSE?.orb_as_of as string, true)}`,
    },
    { name: "Nifty / Bank Nifty F&O", mode: m.FNO?.mode as string, note: (m.FNO?.status as string) ?? "—" },
  ];
  return (
    <section className="markets" aria-label="Markets">
      {cards.map((c) => (
        <div key={c.name} className={`stat stripe ${c.mode?.startsWith("auto") ? "s-good" : c.mode?.startsWith("log") ? "s-warn" : ""}`}>
          <div className="stat-head">
            <span className="label" style={{ color: "var(--ink)", fontWeight: 600, fontSize: 14 }}>
              {c.name}
            </span>
            {modeChip(c.mode)}
          </div>
          <span className="sub">{c.note}</span>
        </div>
      ))}
    </section>
  );
}

// ------------------------------------------------------------------ coins

const STATE_CHIP: Record<string, string> = {
  breakout: "c-good",
  breakdown: "c-bad",
  oversold: "c-warn",
  quiet: "c-off",
  "no data": "c-off",
};

function CoinsSection({ snap }: { snap: Snapshot }) {
  const c = snap.crypto;
  const counts = c.coins.reduce<Record<string, number>>((a, x) => ((a[x.state] = (a[x.state] ?? 0) + 1), a), {});
  return (
    <section id="coins" className="panel" aria-labelledby="coins-h">
      <div className="panel-head">
        <div>
          <h2 id="coins-h">Coins watched: {c.universe.length}</h2>
          <p>
            Last 15-minute candle {timeIST(c.scan_as_of, true)} · {c.usable ?? "—"} of {c.scanned ?? "—"} charts usable ·
            daily setups from closes through {c.daily_closes_through ?? "—"} (UTC)
          </p>
        </div>
        <div className="filters">
          {Object.entries(counts).map(([k, v]) => (
            <span key={k} className={`chip ${STATE_CHIP[k] ?? "c-off"}`}>
              {v} {k}
            </span>
          ))}
        </div>
      </div>
      <div className="coins">
        {c.coins.map((x) => (
          <CoinCard key={x.symbol} c={x} />
        ))}
      </div>
      <p className="muted small" style={{ margin: "10px 0 0" }}>
        The bar under each price is the last 4 hours&apos; range (low to high) and where the price sits in it. A long
        needs a fresh close above the high with volume ≥ the rule&apos;s minimum, fees ≤ the rule&apos;s cap and BTC above
        its own 4h midpoint.
      </p>
      <CoinBehaviour coins={c.coins} asOf={c.profiles_as_of ?? null} days={c.profiles_days ?? 30} />
    </section>
  );
}

// ------------------------------------------------------------------ coin behaviour (coin_profile.py)

const STYLE_SHORT: Record<string, string> = {
  "breakout / trend follower": "Trend follower",
  "range trader (respects support / resistance)": "Respects S/R",
  "fakeout-prone (breakouts fail)": "Fakeout-prone",
  trending: "Trending",
  "mean-reverting": "Mean-reverting",
  "no clear style": "No clear style",
};
const shortStyle = (s: string) => STYLE_SHORT[s] ?? s;
const styleTone = (s: string) =>
  s.startsWith("breakout") || s === "trending" ? "t-good" : s.startsWith("fakeout") ? "t-bad" : s.startsWith("range") || s === "mean-reverting" ? "t-warn" : "";
const share = (x: { n: number; follow_pct?: number | null; hold_pct?: number | null; continue_pct?: number | null } | undefined,
  k: "follow_pct" | "hold_pct" | "continue_pct") => (x && x.n ? `${x[k]}% of ${x.n}` : "—");

function CoinBehaviour({ coins, asOf, days }: { coins: Coin[]; asOf: string | null; days: number }) {
  const rows = coins.map((c) => c.profile).filter((p): p is CoinProfile => Boolean(p));
  return (
    <details className="behaviour">
      <summary>
        <b>How each coin behaves</b>{" "}
        <span className="muted small">
          {asOf ? `last ${days} days of 15m candles · updated ${timeIST(asOf, true)}` : "first update runs once the runner has this version (takes a minute)"}
        </span>
      </summary>
      <p className="muted small">
        Measured from each coin&apos;s own candles: do breakouts above the 4h high carry on (gain 1 ATR before losing 1),
        does price turn back at its 24h high or low, do big-volume candles continue (a rough proxy for large
        players; real order flow is not in free data), and how closely it follows BTC. 50% is a coin flip; a style is only
        named when the numbers are clearly beyond that. It describes the past and is not a trading filter.
      </p>
      {rows.length > 0 && (
        <div className="tablewrap">
          <table className="rtable">
            <thead>
              <tr>
                <th>Coin</th><th>Style</th><th>Breakouts carried on</th><th>Turned at 24h high/low</th>
                <th>Big-volume moves continued</th><th>BTC corr.</th><th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.symbol}>
                  <td data-label="Coin" className="mono"><span className="sym"><SymbolIcon market="CRYPTO" symbol={p.symbol} />{p.symbol}</span></td>
                  <td data-label="Style" className="why">
                    <span className={`style-line ${styleTone(p.style)}`}>{shortStyle(p.style)}</span>
                    {p.why && <div className="muted small">{p.why}</div>}
                  </td>
                  <td data-label="Breakouts carried on" className="num">{share(p.breakouts, "follow_pct")}</td>
                  <td data-label="Turned at 24h high/low" className="num">{share(p.levels, "hold_pct")}</td>
                  <td data-label="Big-volume moves continued" className="num">{share(p.volume, "continue_pct")}</td>
                  <td data-label="BTC corr." className="num">{p.btc_corr ?? "—"}</td>
                  <td data-label="Notes">{p.notes.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

function CoinCard({ c }: { c: Coin }) {
  const pos =
    c.price !== null && c.range_high !== null && c.range_low !== null && c.range_high > c.range_low
      ? Math.min(100, Math.max(0, ((c.price - c.range_low) / (c.range_high - c.range_low)) * 100))
      : null;
  return (
    <div className={`coin st-${c.state.replace(" ", "")}`}>
      <div className="row">
        <b className="sym"><SymbolIcon market="CRYPTO" symbol={c.symbol} size={20} />{c.symbol}</b>
        <span className={`chip plain ${STATE_CHIP[c.state] ?? "c-off"}`}>{c.state}</span>
      </div>
      <div className="row">
        <span className="px">${price(c.price)}</span>
        <span className="meta">RSI {c.rsi_15m ?? "—"}</span>
      </div>
      <div className="range" title="Position inside the last 4 hours' range">
        {pos !== null && <i style={{ left: `calc(${pos}% - 1px)` }} />}
      </div>
      <div className="meta">
        {pct(c.pct_vs_high)} vs 4h high · vol {c.vol_ratio !== null ? `${c.vol_ratio}×` : "—"}
      </div>
      {c.profile && (
        <div className={`meta style-line ${styleTone(c.profile.style)}`} title={c.profile.why}>
          {shortStyle(c.profile.style)}
        </div>
      )}
      {(c.daily.length > 0 || c.seen_today.length > 0) && (
        <div className="meta" style={{ color: "var(--ink)" }}>
          {c.daily.map((d) => d.replace(/_/g, " ")).join(", ")}
          {c.seen_today.length > 0 && <span className="muted"> {c.daily.length ? "·" : ""} today: {c.seen_today.join(", ").replace(/_/g, " ")}</span>}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ reasons

function ReasonsSection({ snap }: { snap: Snapshot }) {
  const [win, setWin] = useState<"since_restart" | "today" | "all">("today");
  const data = snap.skip_reasons[win] ?? {};
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map((r) => r[1]));
  const label = { since_restart: "Since restart", today: "Today", all: "All logged" } as const;
  return (
    <section id="reasons" className="panel" aria-labelledby="reasons-h">
      <div className="panel-head">
        <div>
          <h2 id="reasons-h">Why trades were skipped</h2>
          <p>Every candidate stops at the first agent that says no. &ldquo;Traded&rdquo; is a paper trade.</p>
        </div>
        <div className="seg-ctl" role="group" aria-label="Time window">
          {(Object.keys(label) as (keyof typeof label)[]).map((k) => (
            <button key={k} aria-pressed={win === k} onClick={() => setWin(k)}>
              {label[k]}
            </button>
          ))}
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="muted">No candidates in this window: no coin made a new breakout.</p>
      ) : (
        <div className="bars">
          {rows.map(([k, v]) => (
            <div className="bar" key={k}>
              <span>{k}</span>
              <div className="track">
                <div
                  className="fill"
                  style={{
                    width: `${(v / max) * 100}%`,
                    background: k === "Traded" ? "var(--good)" : k === "Log only" ? "var(--warn)" : undefined,
                  }}
                />
              </div>
              <span className="num">{v}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ rules

function RulesSection({ snap }: { snap: Snapshot }) {
  const r = (snap.rules.crypto ?? {}) as Record<string, unknown>;
  const rows: [string, string][] = [
    ["Setups traded", String((r.enabled_setups as string[] | undefined)?.join(", ") ?? "—")],
    ["Candles", String(r.timeframe ?? "15m")],
    ["Volume at least", r.min_vol_x !== undefined ? `${r.min_vol_x}× the 4h average` : "—"],
    ["Stop", r.stop === "atr" ? `${r.stop_atr_k ?? 1.5} × ATR(14) under the entry` : r.min_stop_pct ? `${r.stop}, at least ${r.min_stop_pct}% away` : String(r.stop ?? "—")],
    ["Exit", r.exit === "trail" ? `trailing: break-even at +${r.trail_arm_r ?? 1}R, then ${r.trail_atr_k ?? 2} × ATR under the high` : r.target_r !== undefined ? `target ${r.target_r}R` : "—"],
    ["Fees at most", r.max_fee_r !== undefined ? `${r.max_fee_r}R of the risk` : "—"],
    ["BTC regime", r.btc_regime ? "on (long only when BTC is above its 4h midpoint)" : "off"],
    ["Thin hours skipped", Array.isArray(r.skip_hours_utc) && r.skip_hours_utc.length ? `${(r.skip_hours_utc as number[])[0]}:00–${(r.skip_hours_utc as number[]).slice(-1)[0] + 1}:00 UTC` : "none"],
    ["Max chase", r.max_chase_r ? `${r.max_chase_r}R past the trigger` : "off"],
    ["Time stop", r.max_hold_hours !== undefined ? `${r.max_hold_hours} hours` : "—"],
    ...((r.enabled_setups as string[] | undefined)?.some((x) => x.startsWith("smc_sweep"))
      ? [["SMC sweep", `${r.smc_variant ?? "any"} sweeps, stop ${r.smc_stop ?? "sweep"}, exit ${r.smc_exit ?? "2R"}, volume ≥ ${r.smc_min_vol_x ?? 0}×, BTC filter ${r.smc_regime ? "on" : "off"}`] as [string, string]]
      : []),
    ["Rules version", String(r.rules_version ?? "—")],
  ];
  return (
    <section className="panel" aria-labelledby="rules-h">
      <div className="panel-head">
        <div>
          <h2 id="rules-h">Live crypto rules</h2>
          <p>From trader\live\auto_config.json, set from the walk-forward backtest.</p>
        </div>
      </div>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

// ------------------------------------------------------------------ decisions

function resultChip(res: string | null) {
  if (res === "PAPER BUY" || res === "PAPER SHORT") return <span className="chip c-good">{res}</span>;
  if (res === "LOG ONLY") return <span className="chip c-warn">log only</span>;
  if (res === "blocked") return <span className="chip c-bad">blocked</span>;
  return <span className="chip c-off">{res ?? "—"}</span>;
}

function DecisionsSection({ decisions }: { decisions: Decision[] }) {
  const [market, setMarket] = useState("all");
  const [result, setResult] = useState("all");
  const [q, setQ] = useState("");
  const markets = useMemo(() => Array.from(new Set(decisions.map((d) => d.market))).sort(), [decisions]);
  const rows = useMemo(
    () =>
      decisions
        .filter((d) => market === "all" || d.market === market)
        .filter((d) =>
          result === "all"
            ? true
            : result === "traded"
              ? d.result === "PAPER BUY" || d.result === "PAPER SHORT"
              : d.result === result,
        )
        .filter((d) => !q || `${d.symbol} ${d.why} ${d.category}`.toLowerCase().includes(q.toLowerCase()))
        .slice()
        .reverse(),
    [decisions, market, result, q],
  );
  return (
    <section id="decisions" className="panel" aria-labelledby="dec-h">
      <div className="panel-head">
        <div>
          <h2 id="dec-h">Agent decisions</h2>
          <p>Newest first. Each row is one candidate and the reason it was traded or skipped.</p>
        </div>
        <div className="filters">
          <label className="small muted" htmlFor="f-market">Market</label>
          <select id="f-market" value={market} onChange={(e) => setMarket(e.target.value)}>
            <option value="all">All</option>
            {markets.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <label className="small muted" htmlFor="f-result">Result</label>
          <select id="f-result" value={result} onChange={(e) => setResult(e.target.value)}>
            <option value="all">All</option>
            <option value="traded">Traded</option>
            <option value="skipped">Skipped</option>
            <option value="blocked">Blocked</option>
            <option value="LOG ONLY">Log only</option>
          </select>
          <input id="f-q" type="search" placeholder="Search coin or reason" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search decisions" />
        </div>
      </div>
      <div className="scroll">
        <table className="rtable">
          <thead>
            <tr>
              <th>Time</th>
              <th>Symbol</th>
              <th>Result</th>
              <th>Reason</th>
              <th>Price</th>
              <th>Stop</th>
              <th>Vol</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  No decisions match.
                </td>
              </tr>
            )}
            {rows.map((d, i) => (
              <tr key={i}>
                <td data-label="Time" className="num">{timeIST(d.time, true)}</td>
                <td data-label="Symbol" className="num"><span className="sym"><SymbolIcon id={d.symbol} />{d.symbol}</span></td>
                <td data-label="Result">{resultChip(d.result)}</td>
                <td data-label="Reason" className="why">
                  <b>{d.category}</b>
                  {(d.setup_name || d.setup) && (
                    <div className="small decision-setup">
                      {d.setup_name ?? d.setup?.replace(/_/g, " ")}
                      {d.scanner && d.scanner !== "rules" && <span className="chip plain c-accent setup-ver">{d.scanner}</span>}
                      {d.liquidity && <span className="muted"> · {d.liquidity}</span>}
                    </div>
                  )}
                  <div className="muted small">{d.why}</div>
                </td>
                <td data-label="Price" className="num">{price(d.price)}</td>
                <td data-label="Stop" className="num">
                  {price(d.stop)}
                  {d.stop_pct !== null && <div className="muted small">{d.stop_pct}%</div>}
                </td>
                <td data-label="Vol" className="num">{d.vol !== null ? `${d.vol}×` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ ledger

/** The setup behind a paper trade: its own fields, or (older trades) the agent's note. */
function setupOf(p: Position): { name: string; liq?: string; why?: string; scanner?: string } {
  if (p.setup_name || p.setup) return { name: p.setup_name ?? p.setup ?? "", liq: p.liquidity, why: p.entry_reason, scanner: p.scanner };
  const n = (p.note ?? "").replace(/^(auto(_nse|_us|_fno)?|scanner v\d)\s*:\s*/i, "").replace(/_/g, " ").trim();
  const v = /^scanner (v\d)/i.exec(p.note ?? "");
  return { name: n || "manual", scanner: v ? v[1].toLowerCase() : undefined };
}

function SetupCell({ p }: { p: Position }) {
  const s = setupOf(p);
  return (
    <td data-label="Setup" className="setup-cell" title={s.why}>
      <span className="setup-name">{s.name}</span>
      {s.scanner && s.scanner !== "rules" && <span className="chip plain c-accent setup-ver">{s.scanner}</span>}
      {s.liq && <span className="small muted setup-liq">{s.liq}</span>}
      {s.why && <span className="small muted setup-why">{s.why}</span>}
    </td>
  );
}

/** India positions with Zerodha's latest tick: price and gross open P&L change every second. */
function withLive(open: Position[], live: LiveTicks | null): (Position & { live?: boolean })[] {
  if (!live?.live) return open;
  return open.map((p) => {
    const t = INDIA(p.market) ? live.ticks[p.key] : undefined;
    if (!t) return p;
    const dir = p.side === "short" ? -1 : 1;
    return { ...p, last: t.ltp, open_pnl: (t.ltp - p.entry) * p.qty * dir, quote_time: new Date().toISOString(), live: true };
  });
}

function LedgerSection({ snap, onChange, live }: { snap: Snapshot; onChange: () => void; live: LiveTicks | null }) {
  const { accounts, closed } = snap.ledger;
  const open = withLive(snap.ledger.open, live);
  const { cmds, send, available } = useCommands(onChange);
  const [err, setErr] = useState<string | null>(null);
  const waiting = (key: string | null) =>
    cmds.pending.some((c) => (c.action === "close" && c.key === key) || c.action === "close_all");
  async function close(key?: string) {
    const what = key ? `Close ${key} now at the market price?` : `Close ALL ${open.length} open positions now?`;
    if (!window.confirm(what)) return;
    setErr(null);
    try { await send(key ? "close" : "close_all", key); } catch (e) { setErr(errText(e)); }
  }
  const acctOf = (m: string) => (m === "NSE" || m === "BSE" || m === "NFO" ? "INDIA" : m);
  return (
    <section id="ledger" className="panel" aria-labelledby="led-h">
      <div className="panel-head">
        <div>
          <h2 id="led-h">Paper ledger</h2>
          <p>
            {open.length} open · {closed.length} closed. Judge the strategy after 30+ trades, not one day.
          </p>
        </div>
      </div>
      <div className="accounts" style={{ marginBottom: 14 }}>
        {Object.entries(accounts).map(([name, a]) => {
          const d = a.cash - a.start_capital;
          const cur = currencyOf(name);
          return (
            <div key={name} className="stat">
              <span className="label">{name}</span>
              <span className="value" style={{ fontSize: 19 }}>{money(a.cash, cur)}</span>
              <span className={`sub ${d > 0 ? "pos" : d < 0 ? "neg" : ""}`}>
                {d === 0 ? "untouched" : `${d > 0 ? "+" : ""}${money(d, cur)} on ${money(a.start_capital, cur)}`}
              </span>
            </div>
          );
        })}
      </div>
      <TradeManagerStrip open={open} closed={closed} />
      {open.length > 0 && (
        <>
          <div className="list-head">
            <h3 className="subtitle">Open positions ({open.length})</h3>
            {available && (
              <button className="btn danger" onClick={() => close()} disabled={waiting(null)}>
                {cmds.pending.some((c) => c.action === "close_all") ? "Closing all…" : "Close all"}
              </button>
            )}
          </div>
          {err && <div className="notice bad" style={{ marginBottom: 8 }}>{err}</div>}
          <div className="tablewrap" style={{ marginBottom: 14 }}>
            <table className="rtable">
              <thead>
                <tr><th>Instrument</th><th>Setup · liquidity</th><th>Side</th><th>Qty</th><th>Entry</th><th>Now</th><th>Stop</th><th>Target</th><th>Opened</th>{available && <th><span className="sr-only">Action</span></th>}</tr>
              </thead>
              <tbody>
                {open.map((p) => (
                  <tr key={p.key}>
                    <td data-label="Instrument" className="num"><span className="sym"><SymbolIcon id={p.key} />{p.key}</span></td>
                    <SetupCell p={p} />
                    <td data-label="Side">{p.side ?? "long"}</td>
                    <td data-label="Qty" className="num">{p.qty}</td>
                    <td data-label="Entry" className="num">{price(p.entry)}</td>
                    <td data-label="Now" className="num">
                      {p.last !== undefined ? price(p.last) : "—"}
                      {p.live && <span className="live-dot" title="Live from Zerodha, updates every second" aria-label="live" />}
                      {(() => {
                        const age = p.quote_time ? (Date.now() - new Date(p.quote_time).getTime()) / 60000 : 0;
                        return age > 10 ? <span className="small stale" title="The price feed has not updated this quote">{" "}quote {Math.round(age)} min old</span> : null;
                      })()}
                      {p.open_pnl !== undefined && (
                        <span className={`small ${p.open_pnl > 0 ? "pos" : p.open_pnl < 0 ? "neg" : ""}`}>
                          {" "}{money(p.open_pnl, currencyOf(acctOf(p.market)))}
                        </span>
                      )}
                    </td>
                    <td data-label="Stop" className="num">
                      {price(p.stop)}
                      {p.trailing ? <span className="small muted"> (trailing)</span> : p.locked ? <span className="small pos"> (profit locked)</span> : p.breakeven ? <span className="small muted"> (break-even)</span> : null}
                      {p.mfe_r !== undefined && <span className="small muted" title="Trade Manager: best / worst so far"> best +{p.mfe_r.toFixed(1)}R</span>}
                    </td>
                    <td data-label="Target" className="num">
                      {p.trail_k ? <span className="muted">trailing exit, no fixed target</span> : price(p.target)}
                    </td>
                    <td data-label="Opened" className="num">{timeIST(p.entry_time, true)}</td>
                    {available && (
                      <td data-label="Action">
                        <button className="btn small-btn" onClick={() => close(p.key)} disabled={waiting(p.key)}>
                          {waiting(p.key) ? "Closing…" : "Close"}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <div className="list-head">
        <h3 className="subtitle">Closed trades ({closed.length})</h3>
        <span className="small muted">newest first</span>
      </div>
      <div className="scroll">
        <table className="rtable">
          <thead>
            <tr><th>Closed</th><th>Instrument</th><th>Setup · liquidity</th><th>Entry → exit</th><th>P&amp;L</th><th>R</th><th>Exit</th></tr>
          </thead>
          <tbody>
            {closed.length === 0 && (
              <tr><td colSpan={7} className="muted">No closed paper trades yet.</td></tr>
            )}
            {closed.slice().reverse().map((c, i) => (
              <tr key={i}>
                <td data-label="Closed" className="num">{timeIST(c.exit_time, true)}</td>
                <td data-label="Instrument" className="num"><span className="sym"><SymbolIcon id={c.key} />{c.key}</span></td>
                <SetupCell p={c} />
                <td data-label="Entry → exit" className="num">{price(c.entry)} → {price(c.exit)}</td>
                <td data-label="P&L" className={`num ${(c.pnl ?? 0) > 0 ? "pos" : "neg"}`}>{money(c.pnl, currencyOf(acctOf(c.market)))}</td>
                <td data-label="R" className={`num ${(c.r ?? 0) > 0 ? "pos" : "neg"}`}>
                  {c.r !== undefined ? `${c.r > 0 ? "+" : ""}${c.r}` : "—"}
                  {c.mfe_r !== undefined && <span className="small muted" title="How far the trade went in its favour (best) and against it (worst)"> best +{c.mfe_r.toFixed(1)} / worst {(c.mae_r ?? 0).toFixed(1)}</span>}
                </td>
                <td data-label="Exit">{c.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ trade manager

/** The Trade Manager agent above the open positions: what it is watching and what it last did. */
function TradeManagerStrip({ open, closed }: { open: Position[]; closed: Position[] }) {
  const stateOf = (p: Position) =>
    p.trail_k ? (p.trailing ? "trailing" : "trailing exit") : p.locked ? "profit locked" : p.breakeven ? "breakeven" : "watching";
  const acts = [...open, ...closed]
    .flatMap((p) => (p.tm_log ?? []).map((x) => ({ ...x, key: p.key })))
    .sort((a, b) => (a.t < b.t ? 1 : -1))
    .slice(0, 4);
  const time = (t: string) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return (
    <div className="tm-strip" role="status" aria-label="Trade Manager">
      <div className="tm-head">
        <span className={`tm-dot ${open.length ? "on" : ""}`} aria-hidden="true" />
        <strong>Trade Manager</strong>
        <span className="muted small">
          {open.length
            ? `watching ${open.length} open trade${open.length === 1 ? "" : "s"} every check`
            : "no open trade to watch"}
        </span>
      </div>
      {open.length > 0 && (
        <div className="tm-watch">
          {open.map((p) => (
            <span key={p.key} className={`chip tm-${stateOf(p).replace(/ /g, "-")}`}>
              {p.symbol} · {stateOf(p)}
              {p.mfe_r ? ` · best +${p.mfe_r.toFixed(1)}R` : ""}
            </span>
          ))}
        </div>
      )}
      <ul className="tm-acts">
        {acts.length === 0 && <li className="muted small">No action yet: it moves the stop at +1R, locks profit near the target, exits on a reversal or a dead trade.</li>}
        {acts.map((a, i) => (
          <li key={i} className="small">
            <span className="muted">{time(a.t)}</span> <span className="num">{a.key}</span> {a.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------ logs

function LogsSection({ snap }: { snap: Snapshot }) {
  const [kind, setKind] = useState("all");
  const [q, setQ] = useState("");
  const rows = snap.logs
    .filter((l) => kind === "all" || l.kind === kind)
    .filter((l) => !q || l.text.toLowerCase().includes(q.toLowerCase()))
    .slice()
    .reverse();
  const kinds = ["all", "trade", "tm", "decision", "scan", "runner", "dashboard", "error"];
  return (
    <section id="logs" className="panel" aria-labelledby="logs-h">
      <div className="panel-head">
        <div>
          <h2 id="logs-h">Runner log</h2>
          <p>Last {snap.logs.length} lines of trader\live\log.txt, newest first.</p>
        </div>
        <div className="filters">
          <div className="seg-ctl" role="group" aria-label="Log type">
            {kinds.map((k) => (
              <button key={k} aria-pressed={kind === k} onClick={() => setKind(k)}>
                {k === "tm" ? "trade manager" : k}
              </button>
            ))}
          </div>
          <input type="search" placeholder="Search the log" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the log" />
        </div>
      </div>
      <div className="logs">
        {rows.length === 0 && <div className="ln muted">No lines match.</div>}
        {rows.map((l, i) => (
          <div className="ln" key={i}>
            <span className="muted">{l.t.slice(5)}</span>
            <span className={`k k-${l.kind}`}>{l.kind === "tm" ? "manager" : l.kind}</span>
            <span>{l.text}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ setup

function SetupHelp() {
  return (
    <section className="panel setup">
      <h2 style={{ fontSize: 16 }}>Waiting for the runner&apos;s first snapshot</h2>
      <ol>
        <li>
          Start <code>start_all.bat</code> in <code>D:\trader</code> and keep its window open.
        </li>
        <li>
          After its first cycle it writes <code>trader\live\dashboard_snapshot.json</code>; this page reads it and
          refreshes by itself.
        </li>
      </ol>
    </section>
  );
}
