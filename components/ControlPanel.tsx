"use client";

import { useEffect, useState } from "react";
import { getJSON, postJSON, OPS, errText } from "@/lib/api";

type Control = { CRYPTO: boolean; US: boolean; NSE: boolean; FNO: boolean; paused: boolean };
type AutoBuy = Record<"NSE" | "FNO" | "US_SHORT", { on: boolean; entry_start?: string; entry_end?: string }>;
type ControlResponse = { control: Control; cloud_markets: string[]; can_change: boolean; mode?: "local" | "cloud" };

const MARKETS: { key: keyof Control; name: string; note: string }[] = [
  { key: "CRYPTO", name: "Crypto", note: "20 coins, 4h breakouts, auto paper trades" },
  { key: "US", name: "US stocks", note: "~5,900 stocks, opening-range breakouts (and breakdowns, short)" },
  { key: "NSE", name: "NSE stocks", note: "Backtest found no edge: log-only unless paper buys are on" },
  { key: "FNO", name: "Nifty / Bank Nifty F&O", note: "Backtest found no edge: log-only unless paper buys are on" },
];

/** Market on/off switches. Local mode (PC): written to trader/live/control.json, which live.py reads before every
 *  cycle; no password. Cloud mode: stored in Redis and needs DASHBOARD_PASSWORD. */
export default function ControlPanel() {
  const [data, setData] = useState<ControlResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [ab, setAb] = useState<AutoBuy | null>(null);

  useEffect(() => {
    getJSON<AutoBuy>(`${OPS}/autobuy`).then(setAb).catch(() => setAb(null)); // ops API: PC/VPS only
  }, []);

  async function setBuy(m: "NSE" | "FNO" | "US_SHORT", on: boolean) {
    if (!ab) return;
    setBusy(`buy-${m}`);
    setMsg(null);
    try {
      await postJSON(`${OPS}/autobuy`, { market: m, on });
      setAb({ ...ab, [m]: { ...ab[m], on } });
      if (m === "US_SHORT") {
        setMsg(on ? "US shorts on: opening-range breakdowns are sold short on paper (from 9:50 AM ET, SPY must be weak)." : "US shorts off: US trades long only.");
        return;
      }
      setMsg(on ? `${m} paper buys on: candidates that pass every agent are bought on paper (entries ${ab[m].entry_start}-${ab[m].entry_end} IST).` : `${m} paper buys off: candidates are logged only.`);
    } catch (e) {
      setMsg(`Not saved: ${errText(e)}`);
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    fetch("/api/py/control", { cache: "no-store" })
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setMsg(`Could not load the controls: ${e}`));
  }, []);

  async function change(key: keyof Control, value: boolean) {
    if (!data) return;
    setBusy(key);
    setMsg(null);
    try {
      const r = await fetch("/api/py/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [key]: value }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || r.statusText);
      setData({ ...data, control: body.control });
      setMsg(data.mode === "local" ? "Saved. The runner picks it up on its next cycle (within ~5 min)." : "Saved. The next cloud tick (within ~5 min) uses it.");
    } catch (e) {
      setMsg(`Not saved: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(null);
    }
  }

  if (!data) return null;
  const c = data.control;
  return (
    <section id="control" className="panel" aria-labelledby="ctl-h">
      <div className="panel-head">
        <div>
          <h2 id="ctl-h">Automation control</h2>
          <p>
            Which markets the runner scans and trades on paper. Open paper positions are always watched, even when paused.
            {data.mode === "local" && " A market only runs if the runner was started with it (start_all.bat on the PC, RUNNER_MARKETS on the VPS)."}
          </p>
        </div>
        <label className="switch-row">
          <input
            type="checkbox"
            role="switch"
            id="ctl-paused"
            checked={c.paused}
            disabled={!data.can_change || busy !== null}
            onChange={(e) => change("paused", e.target.checked)}
          />
          <span>{c.paused ? "Paused" : "Pause everything"}</span>
        </label>
      </div>
      {!data.can_change && (
        <div className="notice" style={{ marginBottom: 12 }}>
          Read-only: set <code>DASHBOARD_PASSWORD</code> on Vercel to switch markets from here.
        </div>
      )}
      <div className="markets">
        {MARKETS.map((m) => {
          const cloud = data.cloud_markets.includes(m.key);
          const on = Boolean(c[m.key]) && cloud && !c.paused;
          return (
            <label key={m.key} className={`stat stripe toggle ${on ? "s-good" : ""}`} htmlFor={`ctl-${m.key}`}>
              <div className="stat-head nowrap">
                <span style={{ fontWeight: 600 }}>{m.name}</span>
                <input
                  type="checkbox"
                  role="switch"
                  id={`ctl-${m.key}`}
                  checked={Boolean(c[m.key]) && cloud}
                  disabled={!cloud || !data.can_change || busy !== null}
                  onChange={(e) => change(m.key, e.target.checked)}
                />
              </div>
              <span className="sub">{cloud ? m.note : `PC runner only · ${m.note}`}</span>
              <span>
                {on ? (
                  <span className="chip c-good">Automation on</span>
                ) : cloud ? (
                  <span className="chip c-off">{c.paused ? "Paused" : "Off"}</span>
                ) : (
                  <span className="chip c-warn">{data.mode === "local" ? "Not available" : "Not in the cloud yet"}</span>
                )}
              </span>
            </label>
          );
        })}
      </div>
      {ab && (
        <div className="paperbuys">
          <div>
            <b>Forward tests (paper)</b>
            <p className="small muted">
              India: off logs a candidate that passes every agent, on buys it on paper (the backtests found no edge
              after charges). US shorts: opening-range breakdowns sold short on paper while SPY is weak; not backtested
              yet. Treat these trades as tests, not as proof.
            </p>
          </div>
          {(["NSE", "FNO"] as const).map((m) => (
            <label key={m} className="switch-row" htmlFor={`buy-${m}`}>
              <input
                type="checkbox"
                role="switch"
                id={`buy-${m}`}
                checked={ab[m].on}
                disabled={busy !== null || !c[m]}
                onChange={(e) => setBuy(m, e.target.checked)}
              />
              <span>
                {m === "NSE" ? "NSE stocks" : "F&O"} <span className="muted small">entries {ab[m].entry_start}-{ab[m].entry_end}</span>
              </span>
            </label>
          ))}
          {ab.US_SHORT && (
            <label className="switch-row" htmlFor="buy-US_SHORT">
              <input
                type="checkbox"
                role="switch"
                id="buy-US_SHORT"
                checked={ab.US_SHORT.on}
                disabled={busy !== null || !c.US}
                onChange={(e) => setBuy("US_SHORT", e.target.checked)}
              />
              <span>
                US shorts <span className="muted small">breakdowns, 9:50 AM-3:30 PM ET</span>
              </span>
            </label>
          )}
        </div>
      )}
      {msg && <p className="small muted" style={{ margin: "10px 0 0" }}>{msg}</p>}
    </section>
  );
}
