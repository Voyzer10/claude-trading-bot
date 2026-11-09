"use client";

import { useEffect, useState } from "react";
import { getJSON, OPS, errText } from "@/lib/api";
import { timeIST } from "@/lib/format";
import SymbolIcon from "@/components/SymbolIcon";

type Row = {
  time: string;
  market: string;
  symbol: string;
  setup: string;
  name: string;
  side: "long" | "short";
  bar_end?: string;
  price: number;
  stop: number | null;
  target_2r: number | null;
  result: string;
  why: string;
  details?: Record<string, unknown>;
};
type Resp = { generated_at: string; today: Record<string, number>; latest: Row[] };

const MARKETS = ["ALL", "CRYPTO", "NSE", "US"];
// every setup the scanner looks for (smc_playbook.SETUP_NAMES), listed even before one has been seen
const ALL_SETUPS = [
  "v5 0.146 support long", "v5 0.146 resistance short",
  "v4 primary long", "v4 primary short", "v4 OB/FVG secondary long", "v4 OB/FVG secondary short",
  "v3 sweep long", "v3 sweep short", "v3 FVG/OB retest long", "v3 FVG/OB retest short", "A-B-C-D long", "A-B-C-D short", "Playbook doji long", "Playbook doji short", "Playbook bottom star",
  "Playbook top hammer", "FVG retest long", "FVG retest short", "Order block long", "Order block short",
];

/** The Scanner's view of the owner's setups (A-B-C-D, playbook, FVG / order block), shown inside agent 1. */
export default function ScannerSetups({ refreshKey }: { refreshKey: number }) {
  const [d, setD] = useState<Resp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mkt, setMkt] = useState("ALL");
  const [setup, setSetup] = useState("ALL");

  useEffect(() => {
    getJSON<Resp>(`${OPS}/setups?limit=300`).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(errText(e)));
  }, [refreshKey]);

  if (err) return <p className="muted small">Could not load the setups ({err}).</p>;
  if (!d) return <p className="muted small">Loading…</p>;
  const seen: Record<string, number> = {};
  d.latest.forEach((r) => { seen[r.name] = (seen[r.name] || 0) + 1; });
  const names = Array.from(new Set([...ALL_SETUPS, ...d.latest.map((r) => r.name)]));
  const rows = d.latest.filter((r) => (mkt === "ALL" || r.market === mkt) && (setup === "ALL" || r.name === setup));
  const today = Object.entries(d.today).map(([m, v]) => `${m} ${v}`).join(" · ") || "none yet";

  return (
    <>
      <p className="small muted" style={{ margin: "4px 0 8px" }}>
        Your setups as the scanner finds them on the candle that just closed. Each goes through the agents (its pipe in
        the list above) and, while paper testing, the Broker paper trades it with its stop and target (v3: the opposing
        liquidity; v2: 2R). Each account runs one scanner version (Settings, risk limits: &quot;Scanner version&quot;).
        Judge them on the paper results and the backtests. Today: {today}.
      </p>
      <div className="row" style={{ flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
        {MARKETS.map((m) => (
          <button key={m} className={`btn ${mkt === m ? "primary" : ""}`} onClick={() => setMkt(m)}>{m}</button>
        ))}
        <select value={setup} onChange={(e) => setSetup(e.target.value)} aria-label="Setup">
          <option value="ALL">All setups</option>
          {names.map((n) => <option key={n} value={n}>{n} ({seen[n] || 0})</option>)}
        </select>
      </div>
      {rows.length === 0 ? (
        <p className="muted small">No setups yet{mkt !== "ALL" ? ` on ${mkt}` : ""}.</p>
      ) : (
        <div className="tablewrap">
          <table className="rtable">
            <thead>
              <tr>
                <th>Candle end</th><th>Market</th><th>Symbol</th><th>Setup</th><th>Side</th>
                <th className="num">Price</th><th className="num">Stop</th><th className="num">2R</th><th>Agents</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 150).map((r, i) => (
                <tr key={`${r.market}-${r.symbol}-${r.setup}-${r.time}-${i}`}>
                  <td className="num">{timeIST(r.bar_end || r.time)}</td>
                  <td>{r.market}</td>
                  <td className="mono"><span className="sym"><SymbolIcon market={r.market} symbol={r.symbol} />{r.symbol}</span></td>
                  <td>{r.name}</td>
                  <td className={r.side === "long" ? "pos" : "neg"}>{r.side}</td>
                  <td className="num">{r.price}</td>
                  <td className="num">{r.stop ?? "-"}</td>
                  <td className="num">{r.target_2r ?? "-"}</td>
                  <td className="muted small">{r.result === "LOG ONLY" ? "passed, recorded (not traded)" : r.result.startsWith("PAPER") ? `${r.result}: ${r.why}` : r.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
