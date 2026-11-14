"use client";

// The time machine: how it works (a picture of the steps) and every run it made (owner, 14 Nov 2026).
import { useEffect, useMemo, useState } from "react";
import { getJSON, errText } from "@/lib/api";
import { ago, timeIST } from "@/lib/format";
import ChartView, { type ChartSource } from "@/components/ChartView";

type Run = {
  time: string; symbol: string; setup?: string; side?: string; result?: string; why?: string;
  entry?: number; stop?: number; target?: number;
  engine: "v4" | "us-pack" | "india" | "crypto" | "other"; gate: string | null;
  p_target: number | null; p_stop: number | null; p_neither: number | null; avg_r: number | null;
  paths: number | null; bars: number | null;
  hist_trades: number | null; hist_win: number | null; hist_avg_r: number | null; hist_days: number | null;
  verdict: string | null;
};
type Resp = { runs: Run[]; counts: Record<string, number>; last_run: string | null; scanned: number };

const ENGINE: Record<string, string> = {
  v4: "Scanner v4 · info only", "us-pack": "US ORB · gate", india: "India breakouts · gate", crypto: "Crypto rules · gate", other: "other",
};
const secsSince = (t: string) => Math.max(0, (Date.now() - new Date(t).getTime()) / 1000);
const pc = (x: number | null) => (x === null ? "–" : `${Math.round(x * 100)}%`);
const r2 = (x: number | null) => (x === null ? "–" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}R`);

function Steps() {
  const steps: [string, string][] = [
    ["1 · Setup", "The scanner finds a setup: entry, stop, target, side."],
    ["2 · Candles", "It takes that chart's own 5-minute candles (last ~60 days)."],
    ["3 · History", "Runs the same rules over those days: how many trades, how many won, average R."],
    ["4 · 1,000 replays", "Builds 1,000 possible rests of the day from real past candles, starting at the entry."],
    ["5 · Odds", "Counts target first / stop first / neither by the close, and the average R."],
    ["6 · Recorded", "Saved with the decision (step 5). v4: info only, never blocks. Old engines: a negative edge skipped the trade."],
  ];
  return (
    <ol className="tmx-steps">
      {steps.map(([h, t]) => (
        <li key={h}><b>{h}</b><span className="small muted">{t}</span></li>
      ))}
    </ol>
  );
}

function Odds({ r }: { r: Run }) {
  if (r.p_target === null && r.p_stop === null) return <span className="muted small">no replay</span>;
  const t = r.p_target ?? 0, s = r.p_stop ?? 0, n = r.p_neither ?? Math.max(0, 1 - t - s);
  return (
    <div className="tmx-bar" role="img" aria-label={`target first ${pc(t)}, stop first ${pc(s)}, neither ${pc(n)}`}>
      <span className="tmx-t" style={{ width: `${t * 100}%` }} title={`target first ${pc(t)}`} />
      <span className="tmx-s" style={{ width: `${s * 100}%` }} title={`stop first ${pc(s)}`} />
      <span className="tmx-n" style={{ width: `${n * 100}%` }} title={`neither ${pc(n)}`} />
    </div>
  );
}

export default function TimeMachine({ refreshKey }: { refreshKey: number }) {
  const [d, setD] = useState<Resp | null>(null);
  const [err, setErr] = useState("");
  const [eng, setEng] = useState("all");
  const [showAll, setShowAll] = useState(false);
  const [chartOf, setChartOf] = useState<ChartSource | null>(null);
  useEffect(() => {
    getJSON<Resp>("/api/py/timemachine?limit=300").then((x) => { setD(x); setErr(""); }).catch((e) => setErr(errText(e)));
  }, [refreshKey]);
  const list = useMemo(() => (d?.runs ?? []).filter((r) => eng === "all" || r.engine === eng), [d, eng]);
  const shown = showAll ? list : list.slice(0, 40);

  return (
    <section id="timemachine" className="panel" aria-labelledby="tmx-h">
      <div className="panel-head">
        <h2 id="tmx-h">Time machine</h2>
        {d?.last_run && <span className="muted small">last run {ago(secsSince(d.last_run))}</span>}
      </div>
      <p className="small muted">
        Before a trade it asks: “from here, how often does price reach the target before the stop?” and “has this
        rule worked on this chart?”. For Scanner v4 it runs on every setup and is <b>information only</b>: it never
        blocks or opens a trade. (It was not running for v4 until 14 Nov; the older runs below are from the earlier
        engines, where it acted as a gate.)
      </p>
      <Steps />
      <div className="tmx-legend small">
        <span><i className="tmx-t" /> target first</span><span><i className="tmx-s" /> stop first</span><span><i className="tmx-n" /> neither by the close</span>
      </div>

      {err && <p className="neg small">{err}</p>}
      {d && (
        <>
          <div className="tmx-filter">
            {[["all", `All (${d.runs.length})`], ...Object.entries(d.counts).map(([k, n]) => [k, `${ENGINE[k] ?? k} (${n})`])].map(([k, l]) => (
              <button key={k} className={`btn small${eng === k ? " on" : ""}`} onClick={() => setEng(k)}>{l}</button>
            ))}
          </div>
          {list.length === 0 ? (
            <p className="muted">No time machine run yet{eng === "v4" ? " for v4: it starts with the next v4 setup after this deploy" : ""}.</p>
          ) : (
            <ul className="tmx-runs">
              {shown.map((r, i) => (
                <li key={`${r.time}-${r.symbol}-${i}`} className="tmx-run">
                  <div className="tmx-head">
                    <b className="mono">{r.symbol}</b>
                    <span className="small muted">{r.setup ?? ""}{r.side ? ` · ${r.side}` : ""} · {timeIST(r.time, true)}</span>
                    <span className={`chip ${String(r.result ?? "").startsWith("PAPER") ? "c-good" : "c-warn"}`}>{r.result ?? "?"}</span>
                    <span className="chip plain c-off">{ENGINE[r.engine] ?? r.engine}</span>
                  </div>
                  <Odds r={r} />
                  <div className="small num tmx-nums">
                    target {pc(r.p_target)} · stop {pc(r.p_stop)} · neither {pc(r.p_neither)} · avg <b className={r.avg_r !== null && r.avg_r < 0 ? "neg" : "pos"}>{r2(r.avg_r)}</b>
                    {r.paths ? ` · ${r.paths} paths × ${r.bars} candles` : ""}
                  </div>
                  {r.hist_trades !== null && (
                    <div className="small muted num">
                      history: {r.hist_trades} trades{r.hist_days ? ` in ${r.hist_days} days` : ""}{r.hist_win !== null ? `, ${pc(r.hist_win)} won` : ""}, {r2(r.hist_avg_r)} a trade
                    </div>
                  )}
                  {r.entry !== undefined && r.entry !== null && (
                    <div className="small muted num">entry {r.entry} · stop {r.stop} · target {r.target ?? "–"}</div>
                  )}
                  {r.verdict && <p className="small tmx-verdict">{r.verdict}</p>}
                  {!String(r.result ?? "").startsWith("PAPER") && r.why && <p className="small muted">why: {r.why}</p>}
                  {r.entry !== undefined && r.entry !== null && r.stop !== undefined && r.stop !== null && (
                    <div className="lr-actions">
                      <button className="btn small" onClick={() => setChartOf({ kind: "timemachine", time: r.time, symbol: r.symbol })}>
                        View on chart
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          {list.length > 40 && (
            <button className="btn" style={{ marginTop: 8 }} onClick={() => setShowAll((x) => !x)}>{showAll ? "Show fewer" : `Show all ${list.length}`}</button>
          )}
        </>
      )}
      {chartOf && <ChartView src={chartOf} onClose={() => setChartOf(null)} />}
    </section>
  );
}
