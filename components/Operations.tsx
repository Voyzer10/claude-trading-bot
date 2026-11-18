"use client";

import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON, OPS, errText } from "@/lib/api";
import { timeIST } from "@/lib/format";

type Cmd = { id: string; action: string; key?: string | null; asked_at?: string; done_at?: string; ok?: boolean; detail?: string };
type Sys = {
  host?: string; platform: string; python: string; root: string; service_mode: boolean;
  disk: { total_gb: number; used_gb: number; free_gb: number; pct: number };
  cpu_pct?: number; cpus?: number; mem?: { total_gb: number; used_gb: number; pct: number }; boot_time?: string;
  load?: number[]; note?: string;
  runner: { pid: number | null; alive: boolean | null; status: string | null; updated: string | null };
  files: Record<string, number>;
};
type Probe = { name: string; ok: boolean; ms: number; detail: string };

const ACTION_NAMES: Record<string, string> = {
  run_now: "Scan now", restart: "Restart runner", close: "Close position", close_all: "Close all positions",
};

/** Queue a runner command and wait (poll) until the runner reports it done. */
export function useCommands(onDone?: () => void) {
  const [cmds, setCmds] = useState<{ pending: Cmd[]; done: Cmd[] }>({ pending: [], done: [] });
  const [available, setAvailable] = useState(true);
  const refresh = useCallback(async () => {
    try {
      setCmds(await getJSON(`${OPS}/commands`));
    } catch {
      setAvailable(false);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (cmds.pending.length === 0) return;
    const id = setInterval(async () => {
      const before = cmds.pending.length;
      const now = await getJSON<typeof cmds>(`${OPS}/commands`).catch(() => null);
      if (now) {
        setCmds(now);
        if (now.pending.length < before) onDone?.();
      }
    }, 3000);
    return () => clearInterval(id);
  }, [cmds, onDone]);
  const send = useCallback(async (action: string, key?: string) => {
    await postJSON(`${OPS}/command`, { action, key });
    await refresh();
  }, [refresh]);
  return { cmds, send, available, refresh };
}

export default function Operations({ onChange }: { onChange: () => void }) {
  const { cmds, send, available } = useCommands(onChange);
  const [sys, setSys] = useState<Sys | null>(null);
  const [probes, setProbes] = useState<{ checked_at: string; results: Probe[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);

  const loadSys = useCallback(() => getJSON<Sys>(`${OPS}/system`).then(setSys).catch(() => {}), []);
  useEffect(() => {
    loadSys();
    const id = setInterval(loadSys, 30_000);
    return () => clearInterval(id);
  }, [loadSys]);

  if (!available) return null;

  async function act(action: string) {
    if (action === "restart" && !window.confirm("Restart the runner? It reloads code and settings; open positions stay open.")) return;
    setBusy(action);
    setMsg(null);
    try {
      await send(action);
      setMsg({ text: `${ACTION_NAMES[action]}: sent. The runner picks it up within ~5 seconds.` });
    } catch (e) { setMsg({ text: errText(e), bad: true }); } finally { setBusy(null); }
  }
  async function check() {
    setBusy("data");
    try { setProbes(await postJSON(`${OPS}/datacheck`)); } catch (e) { setMsg({ text: errText(e), bad: true }); } finally { setBusy(null); }
  }

  const runnerDown = sys && sys.runner.alive === false;

  return (
    <section id="operations" className="panel" aria-labelledby="ops-h">
      <div className="panel-head">
        <div>
          <h2 id="ops-h">Operations</h2>
          <p>Runner actions, machine health, market-data check and downloads.</p>
        </div>
      </div>
      {msg && <div className={`notice ${msg.bad ? "bad" : "ok"}`} role="status" style={{ marginBottom: 12 }}>{msg.text}</div>}
      {runnerDown && (
        <div className="notice bad" style={{ marginBottom: 12 }}>
          The runner process (pid {sys!.runner.pid}) is not running. {sys!.service_mode
            ? "systemd should restart it; check: sudo journalctl -u trader-runner -n 50"
            : "Start start_all.bat again."} Buttons below only work while it runs.
        </div>
      )}

      <div className="grid-2">
        <div className="formblock">
          <h3 className="h3">Runner</h3>
          <div className="actions" style={{ marginTop: 0 }}>
            <button className="btn primary" onClick={() => act("run_now")} disabled={busy !== null}>Scan now</button>
            <button className="btn" onClick={() => act("restart")} disabled={busy !== null}>Restart runner</button>
          </div>
          <p className="field-help">
            Scan now: checks the latest candle and open positions immediately. Restart: reloads the code and settings
            (use after an update).
          </p>
          <h3 className="h3" style={{ marginTop: 12 }}>Recent requests</h3>
          <ul className="cmdlist">
            {cmds.pending.map((c) => (
              <li key={c.id}><span className="chip c-warn">waiting</span> {ACTION_NAMES[c.action] ?? c.action} {c.key ?? ""}</li>
            ))}
            {cmds.done.slice(0, 6).map((c) => (
              <li key={c.id + (c.done_at ?? "")}>
                <span className={`chip ${c.ok ? "c-good" : "c-bad"}`}>{c.ok ? "done" : "failed"}</span>{" "}
                <span className="num small">{timeIST(c.done_at, true)}</span> {ACTION_NAMES[c.action] ?? c.action}: {c.detail}
              </li>
            ))}
            {cmds.pending.length + cmds.done.length === 0 && <li className="muted">None yet.</li>}
          </ul>
        </div>

        <div className="formblock">
          <h3 className="h3">Machine{sys?.host ? `: ${sys.host}` : ""}</h3>
          {sys ? (
            <>
              <div className="meters">
                {sys.cpu_pct !== undefined && <Meter label={`CPU (${sys.cpus} cores)`} pct={sys.cpu_pct} text={`${sys.cpu_pct}%`} />}
                {sys.mem && <Meter label="Memory" pct={sys.mem.pct} text={`${sys.mem.used_gb} / ${sys.mem.total_gb} GB`} />}
                <Meter label="Disk" pct={sys.disk.pct} text={`${sys.disk.free_gb} GB free of ${sys.disk.total_gb}`} />
              </div>
              <dl className="kv" style={{ marginTop: 10 }}>
                <dt>Runner</dt>
                <dd>{sys.runner.alive === null ? "unknown" : sys.runner.alive ? `running (pid ${sys.runner.pid})` : "not running"}</dd>
                <dt>Mode</dt><dd>{sys.service_mode ? "VPS service (systemd)" : "PC (.bat windows)"}</dd>
                {sys.boot_time && (<><dt>Machine up since</dt><dd>{timeIST(sys.boot_time, true)}</dd></>)}
                <dt>Python</dt><dd>{sys.python} · {sys.platform}</dd>
                {sys.load && (<><dt>Load</dt><dd>{sys.load.join(" / ")}</dd></>)}
              </dl>
              {sys.note && <p className="field-help">{sys.note}</p>}
            </>
          ) : <p className="muted small">Loading…</p>}
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <div className="formblock">
          <h3 className="h3">Market data check</h3>
          <p className="field-help" style={{ marginTop: 0 }}>
            Can this machine reach Yahoo and Coinbase? Run it first on a new VPS: some datacenters are blocked.
          </p>
          <div className="actions" style={{ marginTop: 6 }}>
            <button className="btn" onClick={check} disabled={busy !== null}>{busy === "data" ? "Checking…" : "Check data sources"}</button>
          </div>
          {probes && (
            <ul className="cmdlist" aria-live="polite">
              {probes.results.map((p) => (
                <li key={p.name}>
                  <span className={`chip ${p.ok ? "c-good" : "c-bad"}`}>{p.ok ? "ok" : "failed"}</span> {p.name}{" "}
                  <span className="muted small">{p.ms} ms · {p.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="formblock">
          <h3 className="h3">Downloads</h3>
          <ul className="downloads">
            <li><a href={`${OPS}/download/trades.csv`}>Closed paper trades (CSV)</a></li>
            <li><a href={`${OPS}/download/ledger.json`}>Paper ledger (JSON)</a></li>
            <li><a href={`${OPS}/download/log.txt`}>Runner log</a></li>
            <li><a href={`${OPS}/download/decisions.jsonl`}>Agent decisions (JSONL)</a></li>
            <li><a href={`${OPS}/download/auto_config.json`}>Crypto rules</a> · <a href={`${OPS}/download/paper_config.json`}>Risk limits</a></li>
          </ul>
          {sys && Object.keys(sys.files).length > 0 && (
            <p className="field-help">
              {Object.entries(sys.files).map(([k, b]) => `${k} ${(b / 1024).toFixed(0)} KB`).join(" · ")}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function Meter({ label, pct, text }: { label: string; pct: number; text: string }) {
  const cls = pct >= 90 ? "bad" : pct >= 75 ? "warn" : "";
  return (
    <div className="meter">
      <div className="row"><span>{label}</span><span className="num">{text}</span></div>
      <div className="track" role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className={`fill ${cls}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  );
}
