"use client";

import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON, OPS, errText } from "@/lib/api";
import { timeIST } from "@/lib/format";

type Job = { id: string; mode: string; status: string; started: string; ended?: string; seconds?: number; exit_code?: number };

const MODE_NAMES: Record<string, string> = {
  "crypto-v4": "Crypto v4 pro setup: trend, squeeze, session, ATR stop, partial/trailing exit",
  "crypto-smc": "Crypto SMC: liquidity sweep and reclaim vs the live breakout rule",
  "nse-v2": "NSE v2: wider stops (range low / ATR), trailing exit, charges cap, 15/30-min range",
  "crypto-live": "Crypto live rule: entry timing (close vs +1 min vs +5 min)",
  crypto: "Crypto long (4h breakout, the live rule)",
  "crypto-5m": "Crypto on 5-minute charts (4h and 1h ranges)",
  "crypto-short": "Crypto short (4h breakdown)",
  "crypto-mr": "Crypto oversold bounce",
  nse: "NSE stocks (opening-range breakout)",
  fno: "Nifty / Bank Nifty F&O",
};

/** Runs research.py on the machine the bot runs on, in the background, and shows its report. */
export default function Backtest() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [modes, setModes] = useState<string[]>([]);
  const [mode, setMode] = useState("crypto-v4");
  const [sel, setSel] = useState<string | null>(null);
  const [out, setOut] = useState<{ job: Job; output: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await getJSON<{ jobs: Job[]; modes: string[] }>(`${OPS}/backtest`);
      setJobs(r.jobs);
      setModes(r.modes);
      setSel((s) => s ?? r.jobs[0]?.id ?? null);
    } catch {
      setUnavailable(true);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const running = jobs?.some((j) => j.status === "running");
  useEffect(() => {
    if (!sel) return;
    const get = () => getJSON<{ job: Job; output: string }>(`${OPS}/backtest/${sel}`).then(setOut).catch(() => {});
    get();
    if (!running) return;
    const id = setInterval(() => { get(); load(); }, 4000);
    return () => clearInterval(id);
  }, [sel, running, load]);

  if (unavailable || !jobs) return null;

  async function start(m: string = mode) {
    setErr(null);
    try {
      const r = await postJSON<{ id: string }>(`${OPS}/backtest`, { mode: m });
      setSel(r.id);
      await load();
    } catch (e) { setErr(errText(e)); }
  }

  return (
    <section id="backtest" className="panel" aria-labelledby="bt-h">
      <div className="panel-head">
        <div>
          <h2 id="bt-h">Backtest</h2>
          <p>
            Runs research.py on this machine with fresh market data (a few minutes). Read the out-of-sample line: that is
            the honest number. Change a live rule only after it holds up here.
          </p>
        </div>
      </div>
      <div className="filters">
        <label htmlFor="bt-mode" className="small">Strategy</label>
        <select id="bt-mode" value={mode} onChange={(e) => setMode(e.target.value)}>
          {modes.map((m) => <option key={m} value={m}>{MODE_NAMES[m] ?? m}</option>)}
        </select>
        <button className="btn primary" onClick={() => start()} disabled={running}>{running ? "A backtest is running…" : "Run backtest"}</button>
      </div>
      <div className="actions">
        <span className="small muted" style={{ alignSelf: "center" }}>Quick:</span>
        <button className="btn" onClick={() => start("crypto-v4")} disabled={running}>Crypto v4</button>
        <button className="btn" onClick={() => start("crypto-smc")} disabled={running}>Crypto SMC (new)</button>
        <button className="btn" onClick={() => start("nse-v2")} disabled={running}>NSE v2</button>
        <button className="btn" onClick={() => start("crypto-live")} disabled={running}>Live entry timing</button>
        <button className="btn" onClick={() => start("crypto-5m")} disabled={running}>5-minute charts</button>
        <button className="btn" onClick={() => start("crypto")} disabled={running}>Crypto 15m (all filters)</button>
      </div>
      {err && <div className="notice bad" style={{ marginTop: 10 }}>{err}</div>}
      {jobs.length === 0 && <p className="small muted" style={{ marginTop: 10 }}>No backtests yet. Each one takes a few minutes; the report appears here.</p>}
      {jobs.length > 0 && (
        <div className="bt-grid">
          <ul className="joblist" aria-label="Past backtests">
            {jobs.map((j) => (
              <li key={j.id}>
                <button aria-pressed={sel === j.id} onClick={() => setSel(j.id)}>
                  <span className={`chip ${j.status === "done" ? "c-good" : j.status === "running" ? "c-warn" : "c-bad"}`}>{j.status.split(" ")[0]}</span>
                  <span>{j.mode}</span>
                  <span className="muted small num">{timeIST(j.started, true)}{j.seconds !== undefined ? ` · ${Math.round(j.seconds / 60)} min` : ""}</span>
                </button>
              </li>
            ))}
          </ul>
          <pre className="report" aria-live="polite">
            {out ? out.output || (out.job.status === "running" ? "Starting… downloading market data." : "(no output)") : "Pick a backtest."}
          </pre>
        </div>
      )}
    </section>
  );
}
