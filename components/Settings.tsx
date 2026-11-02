"use client";

import { useEffect, useState } from "react";
import { getJSON, postJSON, OPS, errText } from "@/lib/api";
import { currencyOf } from "@/lib/format";

type Field = { type: string; min?: number; max?: number; choices?: string[]; accounts?: string[] };
type SettingsDoc = {
  rules: Record<string, unknown>;
  rule_defaults: Record<string, unknown>;
  rule_fields: Record<string, Field>;
  rules_version: number | null;
  risk: Record<string, Record<string, number>>;
  risk_fields: Record<string, Field>;
  coins: string[];
  prefs: { usd_inr: number; daily_goal_inr: number };
};

const RULE_LABELS: Record<string, [string, string]> = {
  enabled_setups: ["Setups traded", "Long = 4h breakout. Short = 4h breakdown (failed its backtest: keep off)."],
  stop: ["Stop", "atr: 1.5 x ATR under the entry (v4, backtested). range-mid / range-low: the older v3 stops."],
  stop_atr_k: ["ATR stop (x ATR)", "How many ATRs below the entry the stop sits (stop = atr)."],
  exit: ["Exit", "trail: break-even at +1R, then the stop follows the high (v4). target: fixed target at Target (R)."],
  trail_atr_k: ["Trail distance (x ATR)", "How far under the highest price the trailing stop follows."],
  target_r: ["Target (R)", "Take profit at this many times the risk (exit = target only)."],
  max_chase_r: ["Max chase (R)", "0 = off (v5: skipping strong breakout candles hurt in the backtest). >0 skips a breakout that already ran this far."],
  min_stop_pct: ["Min stop distance (%)", "0 = off (v4 uses the fee cap instead). v3 used 1%."],
  min_vol_x: ["Min breakout volume (x)", "Breakout candle volume vs the 4h average."],
  btc_regime: ["BTC filter", "Only buy when BTC is above the middle of its own 4h range."],
  max_fee_r: ["Max fees (R)", "Skip if the round-trip fee costs more than this."],
  max_hold_hours: ["Time stop (hours)", "Close an open crypto trade after this long."],
};
const RISK_LABELS: Record<string, string> = {
  max_loss_per_trade: "Max loss per trade",
  max_loss_per_trade_fno: "Max loss per F&O trade",
  daily_loss_limit: "Daily loss limit",
  max_trades_per_day: "Max trades per day",
  max_position_pct: "Max position (% of capital)",
};
const SETUP_NAMES: Record<string, string> = { range_breakout_4h: "Long (breakout)", range_breakdown_4h: "Short (breakdown)" };

export default function Settings() {
  const [doc, setDoc] = useState<SettingsDoc | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);

  const load = () =>
    getJSON<SettingsDoc>(`${OPS}/settings`).then(setDoc).catch(() => setUnavailable(true));
  useEffect(() => { load(); }, []);

  if (unavailable || !doc) return null;
  const say = (text: string, bad = false) => setMsg({ text, bad });

  return (
    <section id="settings" className="panel" aria-labelledby="set-h">
      <div className="panel-head">
        <div>
          <h2 id="set-h">Settings</h2>
          <p>Saved to the bot&apos;s files; the runner uses them from its next scan. Every change is written to the runner log.</p>
        </div>
      </div>
      {msg && <div className={`notice ${msg.bad ? "bad" : "ok"}`} role="status" style={{ marginBottom: 12 }}>{msg.text}</div>}
      <RulesForm doc={doc} onSaved={(t) => { say(t); load(); }} onError={(t) => say(t, true)} />
      <RiskForm doc={doc} onSaved={(t) => { say(t); load(); }} onError={(t) => say(t, true)} />
      <div className="grid-2" style={{ marginTop: 16 }}>
        <CoinsForm coins={doc.coins} onSaved={(t) => { say(t); load(); }} onError={(t) => say(t, true)} />
        <PrefsForm prefs={doc.prefs} onSaved={(t) => { say(t); load(); }} onError={(t) => say(t, true)} />
      </div>
    </section>
  );
}

type FormProps = { onSaved: (t: string) => void; onError: (t: string) => void };

function RulesForm({ doc, onSaved, onError }: { doc: SettingsDoc } & FormProps) {
  const [v, setV] = useState<Record<string, unknown>>(doc.rules);
  const [busy, setBusy] = useState(false);
  useEffect(() => setV(doc.rules), [doc.rules]);

  const changed = Object.keys(doc.rule_fields).filter((k) => JSON.stringify(v[k]) !== JSON.stringify(doc.rules[k]));
  const offDefault = Object.keys(doc.rule_fields).filter((k) => JSON.stringify(doc.rules[k]) !== JSON.stringify(doc.rule_defaults[k]));
  const shortOn = Array.isArray(v.enabled_setups) && (v.enabled_setups as string[]).includes("range_breakdown_4h");

  async function save() {
    if (shortOn && !window.confirm("Shorts lost money in the backtest. Turn them on anyway?")) return;
    setBusy(true);
    try {
      const changes = Object.fromEntries(changed.map((k) => [k, v[k]]));
      const r = await postJSON<{ changed: string[] }>(`${OPS}/settings/rules`, { changes });
      onSaved(r.changed.length ? `Crypto rules saved: ${r.changed.join("; ")}` : "Nothing changed.");
    } catch (e) { onError(`Not saved: ${errText(e)}`); } finally { setBusy(false); }
  }
  async function reset() {
    if (!window.confirm("Reset the crypto rules to the backtested defaults?")) return;
    setBusy(true);
    try { await postJSON(`${OPS}/settings/rules/reset`); onSaved("Crypto rules reset to the backtested defaults."); }
    catch (e) { onError(errText(e)); } finally { setBusy(false); }
  }

  return (
    <fieldset className="formblock">
      <legend>Crypto strategy rules (v{doc.rules_version ?? "?"})</legend>
      <p className="small muted" style={{ margin: "0 0 10px" }}>
        The defaults are what the backtest tested. Changing them means trading an untested rule: run a backtest first.
        {offDefault.length > 0 && <> <b>Changed from the defaults:</b> {offDefault.join(", ")}.</>}
      </p>
      <div className="form-grid">
        {Object.entries(doc.rule_fields).map(([k, f]) => {
          const [label, help] = RULE_LABELS[k] ?? [k, ""];
          const def = doc.rule_defaults[k];
          const id = `rule-${k}`;
          let input;
          if (f.type === "bool") {
            input = (
              <label className="switch-row" htmlFor={id}>
                <input id={id} type="checkbox" role="switch" checked={Boolean(v[k])} onChange={(e) => setV({ ...v, [k]: e.target.checked })} />
                <span>{v[k] ? "On" : "Off"}</span>
              </label>
            );
          } else if (f.type === "choice") {
            input = (
              <select id={id} value={String(v[k])} onChange={(e) => setV({ ...v, [k]: e.target.value })}>
                {f.choices!.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            );
          } else if (f.type === "setups") {
            const cur = (v[k] as string[]) ?? [];
            input = (
              <div className="checks" id={id} role="group" aria-label={label}>
                {f.choices!.map((c) => (
                  <label key={c}>
                    <input type="checkbox" checked={cur.includes(c)}
                           onChange={(e) => setV({ ...v, [k]: e.target.checked ? [...cur, c] : cur.filter((x) => x !== c) })} />
                    {SETUP_NAMES[c] ?? c}
                  </label>
                ))}
              </div>
            );
          } else {
            input = (
              <input id={id} type="number" inputMode="decimal" step="any" min={f.min} max={f.max} value={String(v[k] ?? "")}
                     onChange={(e) => setV({ ...v, [k]: e.target.value === "" ? "" : Number(e.target.value) })} />
            );
          }
          return (
            <div key={k} className="field">
              <label htmlFor={id} className="field-label">{label}</label>
              {input}
              <span className="field-help">{help} Default: {Array.isArray(def) ? def.map((x) => SETUP_NAMES[x] ?? x).join(", ") : String(def)}.</span>
            </div>
          );
        })}
      </div>
      {shortOn && <div className="notice bad" style={{ marginTop: 10 }}>Short selling is selected. It failed its backtest (also with the trend filter).</div>}
      <div className="actions">
        <button className="btn primary" onClick={save} disabled={busy || changed.length === 0}>
          {changed.length ? `Save ${changed.length} change${changed.length > 1 ? "s" : ""}` : "No changes"}
        </button>
        <button className="btn" onClick={() => setV(doc.rules)} disabled={busy || changed.length === 0}>Undo</button>
        <button className="btn" onClick={reset} disabled={busy || offDefault.length === 0}>Reset to backtested defaults</button>
      </div>
    </fieldset>
  );
}

function RiskForm({ doc, onSaved, onError }: { doc: SettingsDoc } & FormProps) {
  const names = Object.keys(doc.risk);
  const [acct, setAcct] = useState(names.includes("CRYPTO") ? "CRYPTO" : names[0]);
  const [v, setV] = useState<Record<string, number | string>>(doc.risk[acct] ?? {});
  const [busy, setBusy] = useState(false);
  useEffect(() => setV(doc.risk[acct] ?? {}), [doc.risk, acct]);

  const fields = Object.entries(doc.risk_fields).filter(([, f]) => !f.accounts || f.accounts.includes(acct));
  const changed = fields.map(([k]) => k).filter((k) => String(v[k]) !== String(doc.risk[acct]?.[k]));
  const cur = currencyOf(acct);

  async function save() {
    setBusy(true);
    try {
      const changes = Object.fromEntries(changed.map((k) => [k, v[k]]));
      const r = await postJSON<{ changed: string[] }>(`${OPS}/settings/risk`, { account: acct, changes });
      onSaved(r.changed.length ? `${acct} risk limits saved: ${r.changed.join("; ")}` : "Nothing changed.");
    } catch (e) { onError(`Not saved: ${errText(e)}`); } finally { setBusy(false); }
  }

  return (
    <fieldset className="formblock" style={{ marginTop: 16 }}>
      <legend>Risk limits</legend>
      <div className="filters" style={{ marginBottom: 10 }}>
        <div className="seg-ctl" role="group" aria-label="Account">
          {names.map((n) => (
            <button key={n} aria-pressed={n === acct} onClick={() => setAcct(n)}>{n}</button>
          ))}
        </div>
        <span className="small muted">Capital {cur}{doc.risk[acct]?.capital?.toLocaleString("en-IN")} (paper)</span>
      </div>
      <div className="form-grid compact">
        {fields.map(([k, f]) => (
          <div key={k} className="field">
            <label htmlFor={`risk-${k}`} className="field-label">
              {RISK_LABELS[k] ?? k}{k.includes("loss") ? ` (${cur})` : ""}
            </label>
            <input id={`risk-${k}`} type="number" inputMode="decimal" step={f.type === "int" ? 1 : "any"} min={f.min} max={f.max}
                   value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
          </div>
        ))}
      </div>
      <div className="actions">
        <button className="btn primary" onClick={save} disabled={busy || changed.length === 0}>
          {changed.length ? `Save ${acct} limits` : "No changes"}
        </button>
      </div>
    </fieldset>
  );
}

function CoinsForm({ coins, onSaved, onError }: { coins: string[] } & FormProps) {
  const [text, setText] = useState(coins.join(" "));
  const [busy, setBusy] = useState(false);
  useEffect(() => setText(coins.join(" ")), [coins]);
  const list = text.split(/[\s,]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
  async function save() {
    setBusy(true);
    try {
      const r = await postJSON<{ coins: string[] }>(`${OPS}/settings/coins`, { coins: list });
      onSaved(`Coins saved (${r.coins.length}). The next scan uses them.`);
    } catch (e) { onError(`Not saved: ${errText(e)}`); } finally { setBusy(false); }
  }
  return (
    <fieldset className="formblock">
      <legend>Crypto coins watched ({list.length})</legend>
      <label htmlFor="coins" className="field-help" style={{ display: "block", marginBottom: 6 }}>
        Symbols separated by spaces (BTC ETH SOL...). The backtest used the current 20; more coins means more trades but
        untested ones. Max 60.
      </label>
      <textarea id="coins" rows={4} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      <div className="actions">
        <button className="btn primary" onClick={save} disabled={busy || list.join(" ") === coins.join(" ")}>Save coins</button>
      </div>
    </fieldset>
  );
}

function PrefsForm({ prefs, onSaved, onError }: { prefs: SettingsDoc["prefs"] } & FormProps) {
  const [v, setV] = useState({ usd_inr: String(prefs.usd_inr), daily_goal_inr: String(prefs.daily_goal_inr) });
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try { await postJSON(`${OPS}/settings/prefs`, { usd_inr: Number(v.usd_inr), daily_goal_inr: Number(v.daily_goal_inr) }); onSaved("Goal settings saved."); }
    catch (e) { onError(`Not saved: ${errText(e)}`); } finally { setBusy(false); }
  }
  return (
    <fieldset className="formblock">
      <legend>Goal and currency</legend>
      <div className="form-grid compact">
        <div className="field">
          <label htmlFor="pref-goal" className="field-label">Daily goal (₹)</label>
          <input id="pref-goal" type="number" inputMode="decimal" value={v.daily_goal_inr} onChange={(e) => setV({ ...v, daily_goal_inr: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="pref-fx" className="field-label">US$ to ₹</label>
          <input id="pref-fx" type="number" inputMode="decimal" step="any" value={v.usd_inr} onChange={(e) => setV({ ...v, usd_inr: e.target.value })} />
          <span className="field-help">Only for showing $ accounts in rupees.</span>
        </div>
      </div>
      <div className="actions">
        <button className="btn primary" onClick={save} disabled={busy}>Save</button>
      </div>
    </fieldset>
  );
}
