"use client";

import { useEffect, useState } from "react";
import { getJSON, OPS, errText } from "@/lib/api";
import { timeIST } from "@/lib/format";
import SymbolIcon from "@/components/SymbolIcon";

type Obs = {
  time: string;
  market: string;
  symbol: string;
  setup: string;
  side: "long" | "short";
  bar_end: string;
  price: number;
  stop: number | null;
  target_2r: number | null;
  details?: Record<string, unknown>;
};
type Resp = { generated_at: string; today: Record<string, number>; latest: Obs[] };

const NAMES: Record<string, string> = {
  abcd_long: "A-B-C-D long",
  abcd_short: "A-B-C-D short",
  doji_long: "Playbook doji long",
  doji_short: "Playbook doji short",
  star_long: "Playbook bottom star",
  hammer_short: "Playbook top hammer",
  fvg_long: "FVG retest long",
  fvg_short: "FVG retest short",
  ob_long: "Order block long",
  ob_short: "Order block short",
};
const MARKETS = ["ALL", "CRYPTO", "NSE", "US"];

/** Scanner v2: the owner's setups seen live on every market, handed to the agents. Record only: nothing is traded. */
export default function ScannerV2({ refreshKey, embedded = false }: { refreshKey: number; embedded?: boolean }) {
  const [d, setD] = useState<Resp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mkt, setMkt] = useState("ALL");
  const [setup, setSetup] = useState("ALL");

  useEffect(() => {
    getJSON<Resp>(`${OPS}/scanner-v2?limit=300`).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(errText(e)));
  }, [refreshKey]);

  if (err || !d) return null;
  const rows = d.latest.filter((o) => (mkt === "ALL" || o.market === mkt) && (setup === "ALL" || o.setup === setup));
  const totals: Record<string, number> = {};
  Object.entries(d.today).forEach(([k, v]) => {
    const [m] = k.split("|");
    totals[m] = (totals[m] || 0) + v;
  });

  const body = (
    <>
      <p className="small muted" style={{ margin: "4px 0 8px" }}>
        Your setups (A-B-C-D, SMC playbook, FVG / order block), found on the candle that just closed and handed to the
        agents above: each one&apos;s pipe in the list shows how far it got. The Broker records them, it does{" "}
        <b>not</b> trade them (these rules failed their backtests). Today:{" "}
        {Object.keys(totals).length ? Object.entries(totals).map(([m, v]) => `${m} ${v}`).join(" · ") : "none yet"}.
      </p>
      <div className="row" style={{ flexWrap: "wrap", gap: 8, marginBottom: 8 }} id="scanner-v2">
        {MARKETS.map((m) => (
          <button key={m} className={`btn ${mkt === m ? "primary" : ""}`} onClick={() => setMkt(m)}>{m}</button>
        ))}
        <select value={setup} onChange={(e) => setSetup(e.target.value)} aria-label="Setup">
          <option value="ALL">All setups</option>
          {Object.entries(NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {rows.length === 0 ? (
        <p className="muted small">No setups seen yet{mkt !== "ALL" ? ` on ${mkt}` : ""}.</p>
      ) : (
        <div className="tablewrap">
          <table className="rtable">
            <thead>
              <tr>
                <th>Candle end</th><th>Market</th><th>Symbol</th><th>Setup</th><th>Side</th>
                <th className="num">Price</th><th className="num">Stop</th><th className="num">2R</th><th>Details</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 150).map((o, i) => (
                <tr key={`${o.market}-${o.symbol}-${o.setup}-${o.bar_end}-${i}`}>
                  <td className="num">{timeIST(o.bar_end)}</td>
                  <td>{o.market}</td>
                  <td className="mono"><span className="sym"><SymbolIcon market={o.market} symbol={o.symbol} />{o.symbol}</span></td>
                  <td>{NAMES[o.setup] || o.setup}</td>
                  <td className={o.side === "long" ? "pos" : "neg"}>{o.side}</td>
                  <td className="num">{o.price}</td>
                  <td className="num">{o.stop ?? "-"}</td>
                  <td className="num">{o.target_2r ?? "-"}</td>
                  <td className="muted">
                    {o.details
                      ? Object.entries(o.details)
                          .filter(([, v]) => v !== null && v !== undefined && v !== "")
                          .map(([k, v]) => `${k}: ${typeof v === "string" && v.includes("T") ? timeIST(v) : String(v)}`)
                          .join(" · ")
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
  if (embedded) return body;
  return <section className="panel">{body}</section>;
}
