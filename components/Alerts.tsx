"use client";

import { useEffect, useState } from "react";
import { getJSON, postJSON, OPS, errText } from "@/lib/api";

type AlertsDoc = {
  enabled: boolean; token_set: boolean; token_hint: string; chat_id: string;
  on: { trades: boolean; errors: boolean; runner: boolean; daily: boolean };
};

const KINDS: [keyof AlertsDoc["on"], string][] = [
  ["trades", "Every paper trade opened or closed"],
  ["errors", "Runner errors (each at most once an hour)"],
  ["runner", "Runner started / restarted"],
  ["daily", "Daily summary at 23:30 IST"],
];

/** Telegram alerts so you hear about trades and problems on your phone. */
export default function Alerts() {
  const [doc, setDoc] = useState<AlertsDoc | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [token, setToken] = useState("");
  const [chat, setChat] = useState("");
  const [on, setOn] = useState<AlertsDoc["on"]>({ trades: true, errors: true, runner: true, daily: true });
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    getJSON<{ alerts: AlertsDoc }>(`${OPS}/settings`)
      .then((s) => { setDoc(s.alerts); setChat(s.alerts.chat_id); setOn(s.alerts.on); setToken(""); })
      .catch(() => setUnavailable(true));
  useEffect(() => { load(); }, []);
  if (unavailable || !doc) return null;

  async function run(fn: () => Promise<string>) {
    setBusy(true);
    setMsg(null);
    try { setMsg({ text: await fn() }); } catch (e) { setMsg({ text: errText(e), bad: true }); } finally { setBusy(false); }
  }
  const save = (enabled: boolean) => run(async () => {
    await postJSON(`${OPS}/alerts`, { telegram_token: token || undefined, chat_id: chat, enabled, on });
    await load();
    return enabled ? "Alerts saved and on." : "Alerts saved (off).";
  });
  const findChat = () => run(async () => {
    const r = await postJSON<{ chat_id: string; name: string }>(`${OPS}/alerts/find-chat`, { telegram_token: token });
    setChat(r.chat_id);
    return `Found your chat${r.name ? ` (${r.name})` : ""}. Now press Save.`;
  });
  const test = () => run(async () => {
    const r = await postJSON<{ ok: boolean; detail: string }>(`${OPS}/alerts/test`);
    if (!r.ok) throw new Error(`Telegram said: ${r.detail}`);
    return "Test message sent: check Telegram.";
  });

  return (
    <section id="alerts" className="panel" aria-labelledby="al-h">
      <div className="panel-head">
        <div>
          <h2 id="al-h">Phone alerts (Telegram)</h2>
          <p>Get a message for every trade and every problem, without opening the dashboard.</p>
        </div>
        <span className={`chip ${doc.enabled ? "c-good" : "c-off"}`}>{doc.enabled ? "On" : "Off"}</span>
      </div>
      {msg && <div className={`notice ${msg.bad ? "bad" : "ok"}`} role="status" style={{ marginBottom: 12 }}>{msg.text}</div>}
      <div className="grid-2">
        <div className="formblock">
          <ol className="small steps">
            <li>In Telegram, open <b>@BotFather</b>, send <code>/newbot</code>, pick a name. Copy the token it gives you.</li>
            <li>Paste the token below. Open your new bot in Telegram and send it any message (e.g. &quot;hi&quot;).</li>
            <li>Press <b>Find my chat id</b>, then <b>Save and turn on</b>, then <b>Send test</b>.</li>
          </ol>
          <div className="field">
            <label htmlFor="al-token" className="field-label">Bot token</label>
            <input id="al-token" type="password" autoComplete="off" placeholder={doc.token_set ? `saved (${doc.token_hint})` : "123456789:ABC..."}
                   value={token} onChange={(e) => setToken(e.target.value)} />
          </div>
          <div className="field" style={{ marginTop: 8 }}>
            <label htmlFor="al-chat" className="field-label">Chat id</label>
            <div className="inline">
              <input id="al-chat" inputMode="numeric" value={chat} onChange={(e) => setChat(e.target.value)} />
              <button className="btn" onClick={findChat} disabled={busy || (!token && !doc.token_set)}>Find my chat id</button>
            </div>
          </div>
        </div>
        <div className="formblock">
          <span className="field-label">Send me</span>
          <div className="checks col">
            {KINDS.map(([k, label]) => (
              <label key={k}>
                <input type="checkbox" checked={on[k]} onChange={(e) => setOn({ ...on, [k]: e.target.checked })} /> {label}
              </label>
            ))}
          </div>
          <div className="actions">
            <button className="btn primary" onClick={() => save(true)} disabled={busy || !chat || (!token && !doc.token_set)}>Save and turn on</button>
            {doc.enabled && <button className="btn" onClick={() => save(false)} disabled={busy}>Turn off</button>}
            <button className="btn" onClick={test} disabled={busy || !doc.token_set || !doc.chat_id}>Send test</button>
          </div>
        </div>
      </div>
    </section>
  );
}
