"use client";

import { useEffect, useState } from "react";

type Control = { CRYPTO: boolean; US: boolean; NSE: boolean; FNO: boolean; paused: boolean };

const MARKETS: { key: keyof Control; name: string; note: string }[] = [
  { key: "CRYPTO", name: "Crypto", note: "20 coins, 4h breakouts, auto paper trades" },
  { key: "US", name: "US stocks", note: "~5,900 stocks, opening-range breakouts" },
  { key: "NSE", name: "NSE stocks", note: "Backtest found no edge: log-only" },
  { key: "FNO", name: "Nifty / Bank Nifty F&O", note: "Backtest found no edge: log-only" },
];

/** Market on/off switches, written to trader/live/control.json, which live.py reads before every cycle. */
export default function ControlPanel() {
  const [control, setControl] = useState<Control | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/py/control", { cache: "no-store" })
      .then((r) => r.json())
      .then((b) => setControl(b.control))
      .catch((e) => setMsg(`Could not load the controls: ${e}`));
  }, []);

  async function change(key: keyof Control, value: boolean) {
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
      setControl(body.control);
      setMsg("Saved. The runner picks it up on its next cycle (within ~5 min).");
    } catch (e) {
      setMsg(`Not saved: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(null);
    }
  }

  if (!control) return msg ? <p className="notice bad">{msg}</p> : null;
  const c = control;
  return (
    <section id="control" className="panel" aria-labelledby="ctl-h">
      <div className="panel-head">
        <div>
          <h2 id="ctl-h">Automation control</h2>
          <p>
            Which markets the runner scans and trades on paper. Open paper positions are always watched, even when paused.
            A market only runs if the runner was started with it (start_all.bat on the PC, RUNNER_MARKETS on the VPS).
          </p>
        </div>
        <label className="switch-row">
          <input
            type="checkbox"
            role="switch"
            id="ctl-paused"
            checked={c.paused}
            disabled={busy !== null}
            onChange={(e) => change("paused", e.target.checked)}
          />
          <span>{c.paused ? "Paused" : "Pause everything"}</span>
        </label>
      </div>
      <div className="markets">
        {MARKETS.map((m) => {
          const on = Boolean(c[m.key]) && !c.paused;
          return (
            <label key={m.key} className={`stat stripe toggle ${on ? "s-good" : ""}`} htmlFor={`ctl-${m.key}`}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <span style={{ fontWeight: 600 }}>{m.name}</span>
                <input
                  type="checkbox"
                  role="switch"
                  id={`ctl-${m.key}`}
                  checked={Boolean(c[m.key])}
                  disabled={busy !== null}
                  onChange={(e) => change(m.key, e.target.checked)}
                />
              </div>
              <span className="sub">{m.note}</span>
              <span>
                {on ? (
                  <span className="chip c-good">Automation on</span>
                ) : (
                  <span className="chip c-off">{c.paused ? "Paused" : "Off"}</span>
                )}
              </span>
            </label>
          );
        })}
      </div>
      {msg && <p className="small muted" style={{ margin: "10px 0 0" }}>{msg}</p>}
    </section>
  );
}
