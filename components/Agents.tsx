"use client";

import { useEffect, useState } from "react";
import { getJSON, OPS, errText } from "@/lib/api";
import { ago, timeIST } from "@/lib/format";
import SymbolIcon from "@/components/SymbolIcon";
import ScannerSetups from "@/components/ScannerSetups";

type Status = "active" | "working" | "standby" | "paused" | "off" | "n/a";
type Agent = {
  n: number;
  key: string;
  name: string;
  skill: string;
  job: string;
  status: Status;
  now: string;
  today?: { checked: number; passed: number; stopped: number };
  v2_today?: number;
  last?: { time: string; symbol: string; market: string; verdict: "passed" | "stopped" | "traded"; text: string };
};
type Flow = {
  time: string;
  symbol: string;
  market: string;
  setup?: string;
  own?: boolean;
  result: string;
  why: string;
  stopped_at: number | null;
  chain: ("pass" | "stop" | "rec" | "none")[];
};
type AgentsResp = {
  generated_at: string;
  running: boolean;
  runner_status: string;
  markets: string[];
  thin_hours_now: boolean;
  thin_until: string | null;
  agents: Agent[];
  flow: Flow[];
  today: { candidates: number; traded: number };
};

const CHIP: Record<Status, string> = {
  active: "c-good",
  working: "c-good",
  standby: "c-off",
  paused: "c-warn",
  off: "c-bad",
  "n/a": "c-off",
};
const LABEL: Record<Status, string> = {
  active: "Active",
  working: "Working",
  standby: "Standby",
  paused: "Paused",
  off: "Off",
  "n/a": "Not used",
};
const SHORT = ["Scan", "News", "Entry", "Exit", "TM", "Size", "Risk", "Broker", "Alerts"]; // fits 9 across a phone
const FULL = ["Scanner", "News", "Entry", "Exit", "Time machine", "Budget", "Risk", "Broker", "Alerts"];

const secsSince = (iso: string) => (Date.now() - new Date(iso).getTime()) / 1000;

/** The 11 day-trader skill agents: which is working, on what, and how far each candidate got. */
export default function Agents({ refreshKey }: { refreshKey: number }) {
  const [d, setD] = useState<AgentsResp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [showV2, setShowV2] = useState(false);

  useEffect(() => {
    getJSON<AgentsResp>(`${OPS}/agents`).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(errText(e)));
  }, [refreshKey]);

  if (err || !d) return null; // ops API not available (cloud mode) or still loading
  const used = d.agents.filter((a) => a.status !== "n/a");
  const unused = d.agents.filter((a) => a.status === "n/a");
  const busy = used.filter((a) => a.status === "active" || a.status === "working").length;

  return (
    <section id="agents" className="panel" aria-labelledby="agents-h">
      <div className="panel-head">
        <div>
          <h2 id="agents-h">Agents</h2>
          <p>
            The day-trader skill&apos;s agents run in order inside the runner. A candidate stops at the first agent that
            says no. {d.running ? `${busy} active now` : "Runner is not running"} · today {d.today.candidates}{" "}
            candidate{d.today.candidates === 1 ? "" : "s"}, {d.today.traded} traded.
          </p>
        </div>
        {d.thin_hours_now && <span className="chip c-warn">Thin hours till {d.thin_until} IST</span>}
      </div>

      <ol className="agents">
        {used.map((a) => (
          <li key={a.key} className={`agent st-${a.status}`}>
            <div className="agent-top">
              <span className="agent-n num" aria-hidden="true">{a.n}</span>
              <div className="agent-name">
                <b>{a.name}</b>
                <span className="muted small mono">{a.skill}</span>
              </div>
              <span className={`chip ${CHIP[a.status]}`}>{LABEL[a.status]}</span>
            </div>
            <p className="agent-now">{a.now}</p>
            {a.last && (
              <p className="agent-last small">
                <span className={`verdict v-${a.last.verdict}`}>{a.last.verdict}</span>{" "}
                <span className="muted">{ago(secsSince(a.last.time))}:</span> {a.last.text}
              </p>
            )}
            {a.today && (
              <div className="agent-stats small muted num">
                today {a.today.checked} checked · {a.today.passed} passed
                {a.today.stopped > 0 && <> · <span className="neg">{a.today.stopped} stopped</span></>}
              </div>
            )}
            {a.key === "scanner" && (
              <button className="btn small" style={{ marginTop: 6 }} onClick={() => setShowV2((x) => !x)}>
                {showV2 ? "Hide" : "Show"} your setups{a.v2_today !== undefined ? ` (${a.v2_today} today)` : ""}
              </button>
            )}
            <details className="agent-job small">
              <summary>What it does</summary>
              <p>{a.job}</p>
            </details>
          </li>
        ))}
      </ol>
      {showV2 && (
        <div className="v2-box">
          <h3 className="subhead">1 · {d.agents.find((x) => x.key === "scanner")?.name ?? "Scanner"}: your setups</h3>
          <ScannerSetups refreshKey={refreshKey} />
        </div>
      )}
      {unused.length > 0 && (
        <p className="muted small" style={{ marginTop: 10 }}>
          Not used here: {unused.map((a) => `${a.name} (${a.skill})`).join(", ")}. {unused[0].now}
        </p>
      )}

      <h3 className="subhead">Latest candidates through the agents</h3>
      {d.flow.length === 0 ? (
        <p className="muted">No candidate yet: no coin has made a fresh breakout since the log started.</p>
      ) : (
        <>
          <ul className="flow">
            {(showAll ? d.flow : d.flow.slice(0, 6)).map((f, i) => (
              <li key={`${f.time}-${f.symbol}-${i}`}>
                <div className="flow-head">
                  <b className="mono sym"><SymbolIcon market={f.market === "FNO" ? "NFO" : f.market} symbol={f.symbol} />{f.symbol}</b>
                  <span className="muted small">{f.market} · {timeIST(f.time)}</span>
                  {f.setup && <span className={`chip plain ${f.own ? "c-warn" : "c-off"}`}>{f.setup}</span>}
                  <span className={`chip plain ${f.stopped_at === null ? "c-good" : f.result === "blocked" ? "c-bad" : "c-off"}`}>
                    {f.stopped_at === null ? f.result : f.result === "LOG ONLY" ? "recorded, not traded" : `stopped at ${FULL[f.stopped_at - 1] ?? f.stopped_at}`}
                  </span>
                </div>
                <div className="pipe" role="img" aria-label={pipeLabel(f)}>
                  {f.chain.map((c, j) => (
                    <span key={j} className={`step s-${c}`} title={`${j + 1} ${FULL[j]}: ${c}`}>
                      {SHORT[j]}
                    </span>
                  ))}
                </div>
                {f.stopped_at !== null && <p className="small muted flow-why">{f.why}</p>}
              </li>
            ))}
          </ul>
          {d.flow.length > 6 && (
            <button className="btn" style={{ marginTop: 8 }} onClick={() => setShowAll((x) => !x)}>
              {showAll ? "Show fewer" : `Show all ${d.flow.length}`}
            </button>
          )}
        </>
      )}
    </section>
  );
}

function pipeLabel(f: Flow) {
  const passed = f.chain.filter((c) => c === "pass").length;
  if (f.stopped_at === null) return `${f.symbol} passed all ${passed} agents and was traded`;
  if (f.result === "LOG ONLY") return `${f.symbol} passed ${passed} agents; the broker recorded it, no trade`;
  return `${f.symbol} passed ${passed} agents, stopped at ${FULL[f.stopped_at - 1]}`;
}
