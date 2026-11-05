"use client";

import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON, OPS, errText } from "@/lib/api";
import { timeIST } from "@/lib/format";

type Job = { id: string; mode: string; status: string; started: string; ended?: string; seconds?: number; exit_code?: number };

const MODE_NAMES: Record<string, string> = {
  "crypto-v4": "Crypto v4 pro setup: trend, squeeze, session, ATR stop, partial/trailing exit",
  "crypto-v4-short": "Crypto v4 grid for SHORTS (4h breakdowns): ATR stop, trailing, BTC filter, fee cap",
  "crypto-v4-5m": "Crypto v4 on 5-minute candles (compare with Crypto v4)",
  "us-orb": "US ORB (the live US rule) vs earlier entries: opening drive, squeeze, pullback; range width, in-play, RS filters",
  "crypto-v3": "Scanner v3 sweep reversal (crypto 15m): BOS -> close beyond the swept swing -> doji / hammer -> close past trigger",
  "crypto-v3-5m": "Scanner v3 sweep reversal (crypto 5m)",
  "us-v3": "Scanner v3 sweep reversal (US stocks 5m, ~100 liquid names)",
  "nse-v3": "Scanner v3 sweep reversal (NSE 5m, India charges)",
  "crypto-abcd": "A-B-C-D (your entry, crypto 15m): BOS -> red close below swing -> green doji -> close above doji high",
  "crypto-abcd-5m": "A-B-C-D (your entry, crypto 5m)",
  "us-abcd": "A-B-C-D (your entry, US stocks 5m, ~100 liquid names incl. MAR)",
  "nse-abcd": "A-B-C-D (your entry, NSE 5m, India charges)",
  "crypto-smcp": "SMC Playbook (crypto 15m): sweep -> doji / hammer / star -> candle 1-2 close, each setup scored",
  "crypto-smcp-5m": "SMC Playbook (crypto 5m): the same playbook rules on 5-minute candles",
  "nse-smcp": "SMC Playbook (NSE 5m): the playbook on NSE stocks, intraday, India charges",
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
  const [copied, setCopied] = useState<string | null>(null);

  async function copyReport() {
    const text = out?.output ?? "";
    if (!text) return;
    let ok = false;
    try {
      if (navigator.clipboard && window.isSecureContext) {   // HTTPS / localhost
        await navigator.clipboard.writeText(text);
        ok = true;
      }
    } catch { /* fall back below */ }
    if (!ok) {   // plain HTTP (the VPS dashboard): the old textarea + execCommand way still works there
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, text.length);
      try { ok = document.execCommand("copy"); } catch { ok = false; }
      document.body.removeChild(ta);
    }
    setCopied(ok ? "Copied" : "Copy blocked by the browser: use Download");
    setTimeout(() => setCopied(null), 2500);
  }

  function downloadReport() {
    if (!out?.output) return;
    const blob = new Blob([out.output], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `backtest-${out.job.id}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

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
        <button className="btn" onClick={() => start("crypto-v3")} disabled={running}>Scanner v3 crypto 15m</button>
        <button className="btn" onClick={() => start("crypto-v3-5m")} disabled={running}>Scanner v3 crypto 5m</button>
        <button className="btn" onClick={() => start("us-v3")} disabled={running}>Scanner v3 US</button>
        <button className="btn" onClick={() => start("nse-v3")} disabled={running}>Scanner v3 NSE</button>
        <button className="btn" onClick={() => start("crypto-v4")} disabled={running}>Crypto v4</button>
        <button className="btn" onClick={() => start("crypto-v4-short")} disabled={running}>Crypto shorts v4 (new)</button>
        <button className="btn" onClick={() => start("crypto-v4-5m")} disabled={running}>Crypto 5m</button>
        <button className="btn" onClick={() => start("us-orb")} disabled={running}>US ORB + early entries</button>
        <button className="btn" onClick={() => start("crypto-abcd")} disabled={running}>A-B-C-D crypto 15m</button>
        <button className="btn" onClick={() => start("crypto-abcd-5m")} disabled={running}>A-B-C-D crypto 5m</button>
        <button className="btn" onClick={() => start("us-abcd")} disabled={running}>A-B-C-D US</button>
        <button className="btn" onClick={() => start("nse-abcd")} disabled={running}>A-B-C-D NSE</button>
        <button className="btn" onClick={() => start("crypto-smcp")} disabled={running}>Playbook crypto 15m</button>
        <button className="btn" onClick={() => start("crypto-smcp-5m")} disabled={running}>Playbook crypto 5m</button>
        <button className="btn" onClick={() => start("nse-smcp")} disabled={running}>Playbook NSE</button>
        <button className="btn" onClick={() => start("crypto-smc")} disabled={running}>Crypto SMC</button>
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
          <div className="report-wrap">
            <div className="report-bar">
              <span className="small muted">{out ? `${out.job.mode} · ${out.job.status.split(" ")[0]}` : ""}</span>
              <span className="report-actions">
                {copied && <span className="small muted" role="status">{copied}</span>}
                <button className="btn small-btn" onClick={copyReport} disabled={!out?.output}>Copy log</button>
                <button className="btn small-btn" onClick={downloadReport} disabled={!out?.output}>Download .txt</button>
              </span>
            </div>
            <pre className="report" aria-live="polite">
              {out ? out.output || (out.job.status === "running" ? "Starting… downloading market data." : "(no output)") : "Pick a backtest."}
            </pre>
          </div>
        </div>
      )}
    </section>
  );
}
