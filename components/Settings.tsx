"use client";

import { useEffect, useState } from "react";
import { getJSON, postJSON, OPS, errText } from "@/lib/api";
import { currencyOf } from "@/lib/format";

type Field = { type: string; min?: number; max?: number; choices?: string[]; accounts?: string[] };
type MarketRules = { rules: Record<string, unknown>; defaults: Record<string, unknown>; fields: Record<string, Field>; account: string };
type SettingsDoc = {
  markets: Record<string, MarketRules>;
  rules: Record<string, unknown>;
  rule_defaults: Record<string, unknown>;
  rule_fields: Record<string, Field>;
  rules_version: number | null;
  risk: Record<string, Record<string, number | boolean | string>>;
  risk_fields: Record<string, Field>;
  coins: string[];
  prefs: { usd_inr: number; daily_goal_inr: number };
};

const RULE_LABELS: Record<string, [string, string]> = {
  enabled_setups: ["Setups traded", "4h breakout (backtested, live). 4h breakdown: failed its backtest. SMC sweeps: run the Crypto SMC backtest first. Playbook setups (your SMC playbook): run \"Playbook crypto 15m\" first; each can be ticked alone."],
  short_exit: ["Short exit", "trail (crypto-v4-short best): break-even at +1R, then the stop follows the low. 2R: fixed target."],
  short_trend: ["Short trend filter", "ema+slope: short only a coin below its EMA50 < EMA200 with EMA200 falling (15m). ema: without the slope. off: any."],
  short_max_range_pct: ["Short max 4h range (%)", "Short only breakdowns of a tight 4h range (a squeeze). 0 = any width."],
  short_min_vol_x: ["Short min volume (x)", "Breakdown candle volume vs the 4h average, for shorts only. 0 = off."],
  short_skip_thin_hours: ["Shorts skip thin hours", "Off: shorts trade all hours (what the short backtest liked). On: same 00-06 UTC skip as longs."],
  timeframe: ["Candles (timeframe)", "15m: backtested (crypto-v4). 5m: run the Crypto 5m backtest first; the 4h range, ATR stop and trail use 5m candles."],
  smc_variant: ["SMC sweep shape", "wick: one candle sweeps and closes back in (best in crypto-smc, 2 Nov). 2bar: a failed breakdown. any: both."],
  smc_stop: ["SMC stop", "sweep: just beyond the sweep's wick (0.1 ATR buffer). atr1.5: 1.5 x ATR from the entry."],
  smc_exit: ["SMC exit", "2R target, mid (target the 4h range's middle), or trail (longs only; shorts use 2R)."],
  smc_min_vol_x: ["SMC min sweep volume (x)", "Sweep candle volume vs the 4h average. 0 = off."],
  smc_regime: ["SMC BTC filter", "Long only while BTC is above its 4h midpoint, short only below."],
  smcp_confirm: ["Playbook: confirm on candle", "2: candle 1 or candle 2 may close beyond the trigger (playbook). 1: candle 1 only."],
  smcp_struct: ["Playbook: structure (BOS/CHoCH)", "before: a BOS/CHoCH in the trade's direction before the sweep. any: before or up to the entry. none: not required."],
  smcp_doji_pct: ["Playbook: max doji body", "Doji body as a share of its range (0.15 = 15%; 0.10 = stricter)."],
  smcp_buffer_atr: ["Playbook: stop buffer (x ATR)", "Stop beyond the pattern / sweep extreme plus this many ATRs."],
  smcp_target: ["Playbook: target", "internal: nearest swing (else today's high/low). external: CDH/PDH (CDL/PDL). 2R. trail."],
  smcp_min_rr: ["Playbook: min reward (R)", "Skip if the liquidity target is closer than this, after fees."],
  smcp_regime: ["Playbook: BTC filter", "Long only while BTC is above its 4h midpoint, short only below."],
  smcp_liq: ["Playbook: liquidity", "base: PDH/PDL, CDH/CDL, swings. all: + last week's high/low. strong: only PDH/PDL/PWH/PWL or equal highs/lows."],
  smcp_min_disp: ["Playbook: min displacement (x ATR)", "Entry candle body at least this many ATRs. 0 = off."],
  smcp_skip_thin_hours: ["Playbook: skip thin hours", "On: skip 00-06 UTC like the breakout rule. Off: all hours."],
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
  // NSE / US / F&O (the agents' own rules)
  entry_start: ["Entries from (IST)", "No new trade before this time."],
  entry_end: ["Entries until (IST)", "No new trade after this time."],
  fresh_minutes: ["Fresh break (minutes)", "Only a break that triggered this recently is traded."],
  "NSE.stop": ["Stop", "range-mid: the middle of the opening range. range-low: below the range."],
  "NSE.target_r": ["Target (R)", "Take profit at this many times the risk."],
  "FNO.target_r": ["Index target (R)", "Index target this many times the risk; the option's target follows by its delta."],
  "NSE.min_stop_pct": ["Min stop distance (%)", "Skip stops tighter than this % of the price."],
  "US.min_stop_pct": ["Min stop distance (%)", "Skip stops tighter than this % of the price."],
  "NSE.max_chase_r": ["Max chase (R)", "Skip a break that already ran this far past the range."],
  "US.max_chase_r": ["Max chase (R)", "Skip a break that already ran this far past the range (longs and shorts)."],
  "FNO.max_chase_r": ["Max chase (R)", "Skip an index break that already ran this far."],
  "NSE.min_vol_x": ["Min breakout volume (x)", "Breakout candle volume vs its recent average."],
  max_gap_pct: ["Max opening gap (%)", "Skip a stock that opened this far from yesterday's close."],
  regime_filter: ["Nifty filter", "Long only while Nifty is bullish, short only while bearish."],
  "NSE.allow_short": ["Shorts (breakdowns)", "Also trade opening-range breakdowns as intraday shorts. Not backtested."],
  "US.allow_short": ["Shorts (breakdowns)", "Also trade opening-range breakdowns, on paper."],
  short_regime: ["Shorts: SPY filter", "Short only while SPY is below its opening-range middle and its open."],
  min_sim_avg_r: ["Time machine: min average (R)", "The replays of this setup must average at least this."],
  min_mc_avg_r: ["Time machine: min average (R)", "The replays of this setup must average at least this."],
  min_history_trades: ["History: min past trades", "The setup must have fired at least this often before."],
  min_history_avg_r: ["History: min average (R)", "Those past trades must average at least this."],
  max_new_per_cycle: ["Max new trades per scan", "At most this many new trades from one scan."],
  scan_every_min: ["Scan every (minutes)", "How often the whole US universe is scanned."],
  or_minutes: ["Opening range (minutes)", "Length of the opening range (15 = 9:30-9:45 ET)."],
  indices: ["Indices", "Which index's opening-range break is traded."],
  instruments: ["Instruments", "options: the ATM call / put. futures: the index future (long only)."],
  min_days_to_expiry: ["Min days to expiry", "Never buy an option this close to expiry: roll to the next."],
  theta_haircut_r: ["Theta haircut (R)", "Option buyers lose time value: subtract this from the index edge."],
};
const RISK_LABELS: Record<string, string> = {
  max_loss_per_trade: "Max loss per trade",
  max_loss_per_trade_fno: "Max loss per F&O trade",
  daily_loss_limit: "Daily loss limit",
  max_trades_per_day: "Max trades per day",
  capital: "Paper capital (changing it adds / removes the difference as cash; P&L kept)",
  risk_limits: "Risk limits ON (daily loss, trades/day, cooldown, weekly, max per side). Off while paper testing; turn on before real money",
  trade_setups: "Paper trade the Scanner's setups (v4, v3 or v2, as chosen in Scanner version)",
  fno_stock_options: "F&O stocks: buy the ATM option instead of the shares, only for underlyings in the F&O list (Nifty 50 and Bank Nifty only, so stocks trade as shares, never as options)",
  intraday_leverage: "Leverage on stock / crypto trades (1 = none; 5 = 20% margin, the SEBI maximum for Indian stocks; risk per trade unchanged)",
  trade_manager: "Trade Manager on (off = stop and target only)",
  tm_be_r: "Stop to the entry at (R in profit; 0 = never)",
  tm_trail: "Trailing stop on",
  tm_trail_step: "Trailing: move the stop every (R)",
  tm_trail_gap: "Trailing: keep it this far behind the best R (R)",
  tm_lock_at: "Lock profit once this share of the way to the target is covered (0.8 = 80%; 0 = off)",
  tm_lock_keep: "Share of the way to the target the lock keeps (0.5 = half)",
  tm_reversal: "Take profit on a reversal candle near the best price",
  tm_rev_min_r: "Reversal exit only after this many R in profit",
  tm_candle_min: "Candle size for the reversal check (minutes)",
  tm_stale_min: "Close a trade that went nowhere after (minutes; 0 = off)",
  scanner_version: "Scanner version: only the selected one's rules run (rules = only the older rules: crypto 4h breakout / SMC / playbook hits, NSE / US / F&O opening-range breakouts; v5 = the 0.146 level; v4 = your 11 Nov rules (Final Trading Workflow + your answers): primary, then sequential OB/FVG; v3 = 5 Nov sweep reversal + FVG/OB retest; v2 = A-B-C-D, playbook, FVG / OB)",
  v5_constant: "Scanner v5: the constant C, from the move's start (reel 0.146; Fibonacci 0.236 / 0.382 / 0.5 / 0.618 and 1 - r: 0.854 / 0.764 / 0.214 / 0.114; ICT OTE 0.38 / 0.295 / 0.21; Gann 0.125 / 0.25 / 0.375). Above 0.5 only target 2R trades",
  v5_move: "Scanner v5: the move (swing = last swing low -> high; day = today's low -> high)",
  v5_target: "Scanner v5: target (leg = the other end of the move; 2R)",
  cooldown_losses: "Cooldown after N losses in a row (0 = off)",
  cooldown_minutes: "Cooldown length (minutes)",
  weekly_loss_x: "Weekly loss limit (x daily limit, 0 = off)",
  max_same_side: "Max open positions on one side",
  max_position_pct: "Max position (% of capital)",
  fee_pct: "Fee per side % (CoinDCX futures taker + GST: 0.059)",
};
const SETUP_NAMES: Record<string, string> = {
  range_breakout_4h: "Long (4h breakout)",
  range_breakdown_4h: "Short (4h breakdown)",
  smc_sweep_long: "SMC long (swept 4h low, reclaimed)",
  smc_sweep_short: "SMC short (swept 4h high, reclaimed)",
  smcp_doji_long: "Playbook: doji long (after a swept low)",
  smcp_doji_short: "Playbook: doji short (after a swept high)",
  smcp_star_long: "Playbook: bottom star long",
  smcp_hammer_short: "Playbook: top hammer short",
  smcp_fvg_long: "Rulebook: FVG retest long",
  smcp_fvg_short: "Rulebook: FVG retest short",
  smcp_ob_long: "Rulebook: order block retest long",
  smcp_ob_short: "Rulebook: order block retest short",
};

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
      <TradeManagerForm doc={doc} onSaved={(t) => { say(t); load(); }} onError={(t) => say(t, true)} />
      <div className="grid-2" style={{ marginTop: 16 }}>
        <CoinsForm coins={doc.coins} onSaved={(t) => { say(t); load(); }} onError={(t) => say(t, true)} />
        <PrefsForm prefs={doc.prefs} onSaved={(t) => { say(t); load(); }} onError={(t) => say(t, true)} />
      </div>
    </section>
  );
}

type FormProps = { onSaved: (t: string) => void; onError: (t: string) => void };

type MarketKey = "CRYPTO" | "NSE" | "US" | "FNO";
const MARKET_TABS: [MarketKey, string][] = [["CRYPTO", "Crypto"], ["NSE", "NSE stocks"], ["US", "US stocks"], ["FNO", "F&O"]];
const ACCOUNT_OF: Record<MarketKey, string> = { CRYPTO: "CRYPTO", NSE: "INDIA", US: "US", FNO: "FNO" };
const V4_NAMES: Record<string, string> = {
  v4_primary_long: "v4 primary long (bullish BOS, a close below an old low, a classic / gravestone / long-legged doji or inverted hammer, the next 1-2 candles close above its high)",
  v4_primary_short: "v4 primary short (bearish BOS, a close above an old high, a classic / dragonfly / long-legged doji or hammer, the next 1-2 candles close below its low)",
  v4_secondary_long: "v4 OB / FVG secondary long (only after the primary closed)",
  v4_secondary_short: "v4 OB / FVG secondary short (only after the primary closed)",
};
const V5_NAMES: Record<string, string> = {
  v5_level_long: "v5 support long (after an up-move: low + C x range touched, closed back above)",
  v5_level_short: "v5 resistance short (after a down-move: high - C x range touched, closed back below)",
};
const RULES_NAME: Record<MarketKey, string> = {
  CRYPTO: "4h breakout / SMC / playbook / rulebook",
  NSE: "opening-range breakouts",
  US: "opening-range breakouts",
  FNO: "Nifty / Bank Nifty opening-range breakouts",
};

/** Strategy rules, one tab per market: which setups are traded (Scanner v4 setups, or the older rules) and each
 *  market's own rule values. Crypto: trader/live/auto_config.json. NSE / US / F&O: that agent's config file. */
function RulesForm({ doc, onSaved, onError }: { doc: SettingsDoc } & FormProps) {
  const [mkt, setMkt] = useState<MarketKey>("CRYPTO");
  const src = mkt === "CRYPTO"
    ? { rules: doc.rules, defaults: doc.rule_defaults, fields: doc.rule_fields }
    : { rules: doc.markets[mkt]?.rules ?? {}, defaults: doc.markets[mkt]?.defaults ?? {}, fields: doc.markets[mkt]?.fields ?? {} };
  const acct = ACCOUNT_OF[mkt];
  const version = String(doc.risk[acct]?.scanner_version ?? "v3");
  const v4 = version !== "rules";   // every scanner version runs only its own setups
  const ownKey = version === "v5" ? "v5_setups" : "v4_setups";
  const ownNames = version === "v5" ? V5_NAMES : V4_NAMES;
  const savedV4 = (doc.risk[acct]?.[ownKey] as unknown as string[] | undefined) ?? Object.keys(ownNames);
  const [v, setV] = useState<Record<string, unknown>>(src.rules);
  const [v4set, setV4set] = useState<string[]>(savedV4);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setV(src.rules); setV4set(savedV4); }, [doc, mkt]);

  const keys = Object.keys(src.fields);
  const changed = keys.filter((k) => JSON.stringify(v[k]) !== JSON.stringify(src.rules[k]));
  const v4changed = JSON.stringify([...v4set].sort()) !== JSON.stringify([...savedV4].sort());
  const offDefault = keys.filter((k) => JSON.stringify(src.rules[k]) !== JSON.stringify(src.defaults[k]));
  const shortOn = mkt === "CRYPTO" && Array.isArray(v.enabled_setups) && (v.enabled_setups as string[]).includes("range_breakdown_4h")
    && !(doc.rules.enabled_setups as string[] | undefined)?.includes("range_breakdown_4h");
  const nChanges = changed.length + (v4changed ? 1 : 0);
  const tabName = MARKET_TABS.find(([k]) => k === mkt)![1];

  async function save() {
    if (shortOn && !window.confirm("Crypto shorts are a paper forward test: the v7 short filters were positive out-of-sample on only 35 trades. Turn them on?")) return;
    setBusy(true);
    try {
      const done: string[] = [];
      if (changed.length) {
        const changes = Object.fromEntries(changed.map((k) => [k, v[k]]));
        const r = mkt === "CRYPTO"
          ? await postJSON<{ changed: string[] }>(`${OPS}/settings/rules`, { changes })
          : await postJSON<{ changed: string[] }>(`${OPS}/settings/market-rules`, { market: mkt, changes });
        done.push(...r.changed);
      }
      if (v4changed) {
        const r = await postJSON<{ changed: string[] }>(`${OPS}/settings/risk`, { account: acct, changes: { [ownKey]: v4set } });
        done.push(...r.changed);
      }
      onSaved(done.length ? `${tabName} saved: ${done.join("; ")}` : "Nothing changed.");
    } catch (e) { onError(`Not saved: ${errText(e)}`); } finally { setBusy(false); }
  }
  async function reset() {
    if (!window.confirm(`Reset the ${tabName} rules to the defaults?`)) return;
    setBusy(true);
    try {
      if (mkt === "CRYPTO") await postJSON(`${OPS}/settings/rules/reset`);
      else await postJSON(`${OPS}/settings/market-rules/reset`, { market: mkt });
      onSaved(`${tabName} rules reset to the defaults.`);
    } catch (e) { onError(errText(e)); } finally { setBusy(false); }
  }

  return (
    <fieldset className="formblock">
      <legend>Strategy rules{mkt === "CRYPTO" && doc.rules_version ? ` (crypto v${doc.rules_version})` : ""}</legend>
      <div className="filters" style={{ marginBottom: 10 }}>
        <div className="seg-ctl" role="group" aria-label="Market">
          {MARKET_TABS.map(([k, name]) => (
            <button key={k} aria-pressed={k === mkt} onClick={() => setMkt(k)}>{name}</button>
          ))}
        </div>
        <span className="small muted">Account {acct} · Scanner <b>{version}</b> (change it in Risk limits)</span>
      </div>
      {v4 ? (
        <div className="notice" style={{ marginBottom: 12 }}>
          <b>Scanner {version} is on for {acct}:</b> only the {version} setups{version === "v4" || version === "v5" ? " ticked below" : ""} are watched and traded. The {RULES_NAME[mkt]} rules
          are off for this account{mkt === "FNO" ? (version === "v4" ? " (v4 runs on the Nifty 50 and Bank Nifty charts and buys their ATM options)" : ` (${version} does not trade the indices)`) : ""}; their values below are kept for when you switch back.
          {version === "v5" && <> The 0.146 level is <b>not backtested yet</b>: run the Scanner v5 backtests first.</>}
        </div>
      ) : (
        <p className="small muted" style={{ margin: "0 0 10px" }}>
          The defaults are what the backtest tested. Changing them means trading an untested rule: run a backtest first.
        </p>
      )}
      {offDefault.length > 0 && <p className="small muted" style={{ margin: "0 0 10px" }}><b>Changed from the defaults:</b> {offDefault.join(", ")}.</p>}
      {version === "rules" && (
        <div className="notice" style={{ marginBottom: 12 }}>
          <b>Rules only for {acct}:</b> the {RULES_NAME[mkt]} rules below run; no Scanner setups are traded.
        </div>
      )}
      {(version === "v4" || version === "v5") && (
        <div className="field" style={{ marginBottom: 12 }}>
          <span className="field-label">Setups traded: Scanner {version === "v5" ? "v5" : "v4"}{v4 ? "" : " (used when Scanner version is v4)"}</span>
          <div className="checks" role="group" aria-label={`Scanner ${version === "v5" ? "v5" : "v4"} setups traded`}>
            {Object.entries(ownNames).map(([c, name]) => (
              <label key={c}>
                <input type="checkbox" checked={v4set.includes(c)}
                       onChange={(e) => setV4set(e.target.checked ? [...v4set, c] : v4set.filter((x) => x !== c))} />
                {name}
              </label>
            ))}
          </div>
          <span className="field-help">
            {version === "v5"
              ? `The 0.146 level (C = ${doc.risk[acct]?.v5_constant ?? 0.146}, move ${doc.risk[acct]?.v5_move ?? "swing"}, target ${doc.risk[acct]?.v5_target ?? "leg"}; change them in Risk limits). Unticked: found and logged, not traded.`
              : "Your 7 Nov final workflow. Secondaries only come after that chart's primary closed. Unticked: found and logged, not traded."}
            {mkt === "FNO" ? " F&O has its own account (FNO): Nifty 50 and Bank Nifty options only." : ""}
          </span>
        </div>
      )}
      <div className={`form-grid${v4 ? " dimmed" : ""}`}>
        {keys.map((k) => {
          const f = src.fields[k];
          const [label, help] = RULE_LABELS[`${mkt}.${k}`] ?? RULE_LABELS[k] ?? [k, ""];
          const def = src.defaults[k];
          const id = `rule-${mkt}-${k}`;
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
          } else if (f.type === "time") {
            input = <input id={id} type="time" value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: e.target.value })} />;
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
              <input id={id} type="number" inputMode="decimal" step={f.type === "int" ? 1 : "any"} min={f.min} max={f.max} value={String(v[k] ?? "")}
                     onChange={(e) => setV({ ...v, [k]: e.target.value === "" ? "" : Number(e.target.value) })} />
            );
          }
          const lbl = k === "enabled_setups" ? (v4 ? "Setups traded: older rules (off under Scanner v4)" : "Setups traded: older rules") : label;
          return (
            <div key={k} className="field">
              <label htmlFor={id} className="field-label">{lbl}</label>
              {input}
              <span className="field-help">{help} Default: {Array.isArray(def) ? def.map((x) => SETUP_NAMES[x] ?? x).join(", ") : String(def)}.</span>
            </div>
          );
        })}
      </div>
      {shortOn && <div className="notice bad" style={{ marginTop: 10 }}>Crypto shorts are selected. The old short rule lost money; the v7 short filters (downtrend, tight range, trailing exit) were positive out-of-sample on 35 trades only: treat it as a paper test.</div>}
      <div className="actions">
        <button className="btn primary" onClick={save} disabled={busy || nChanges === 0}>
          {nChanges ? `Save ${nChanges} change${nChanges > 1 ? "s" : ""}` : "No changes"}
        </button>
        <button className="btn" onClick={() => { setV(src.rules); setV4set(savedV4); }} disabled={busy || nChanges === 0}>Undo</button>
        <button className="btn" onClick={reset} disabled={busy || offDefault.length === 0}>Reset to defaults</button>
      </div>
    </fieldset>
  );
}

function RiskForm({ doc, onSaved, onError }: { doc: SettingsDoc } & FormProps) {
  const names = Object.keys(doc.risk);
  const [acct, setAcct] = useState(names.includes("CRYPTO") ? "CRYPTO" : names[0]);
  const [v, setV] = useState<Record<string, number | string | boolean>>(doc.risk[acct] ?? {});
  const [busy, setBusy] = useState(false);
  useEffect(() => setV(doc.risk[acct] ?? {}), [doc.risk, acct]);

  const fields = Object.entries(doc.risk_fields).filter(([k, f]) => (!f.accounts || f.accounts.includes(acct)) && f.type !== "setups" && !isTmKey(k) && k in (doc.risk[acct] ?? {}));
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
              {RISK_LABELS[k] ?? k}{k.startsWith("max_loss") || k === "daily_loss_limit" ? ` (${cur})` : ""}
            </label>
            {f.type === "bool" ? (
              <input id={`risk-${k}`} type="checkbox" checked={v[k] === true || v[k] === "true"}
                     onChange={(e) => setV({ ...v, [k]: e.target.checked })} />
            ) : f.type === "choice" ? (
              <select id={`risk-${k}`} value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: e.target.value })}>
                {f.choices!.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            ) : (
              <input id={`risk-${k}`} type="number" inputMode="decimal" step={f.type === "int" ? 1 : "any"} min={f.min} max={f.max}
                     value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
            )}
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

const TM_KEYS = ["trade_manager", "tm_be_r", "tm_trail", "tm_trail_step", "tm_trail_gap", "tm_lock_at", "tm_lock_keep",
  "tm_reversal", "tm_rev_min_r", "tm_stale_min", "tm_candle_min"];
const isTmKey = (k: string) => TM_KEYS.includes(k) || k.startsWith("v4_trail") || k === "v4_be_r";
const TM_GROUPS: [string, string[]][] = [
  ["On / off", ["trade_manager"]],
  ["Breakeven and trailing stop", ["tm_be_r", "tm_trail", "tm_trail_step", "tm_trail_gap"]],
  ["Profit lock (0 = off)", ["tm_lock_at", "tm_lock_keep"]],
  ["Exits (reversal candle, no follow-through: 0 min = off)", ["tm_reversal", "tm_rev_min_r", "tm_candle_min", "tm_stale_min"]],
];
// the owner's v4 rule (11 Nov): +1R -> entry, +2R -> +1R, then 1R per R; nothing else
const TM_DEFAULTS: Record<string, number | boolean> = {
  trade_manager: true, tm_be_r: 1, tm_trail: true, tm_trail_step: 1, tm_trail_gap: 1, tm_lock_at: 0, tm_lock_keep: 0.5,
  tm_reversal: false, tm_rev_min_r: 1, tm_stale_min: 0,
};
const on = (x: unknown) => x === true || x === "true";

/** The Trade Manager in words, from the form's values (the same rules as scanner_v4 / paper.py). */
function tmPreview(v: Record<string, number | string | boolean>): string {
  if (!on(v.trade_manager)) return "Trade Manager off: every trade exits only at its stop or its target (or the session's end).";
  const be = Number(v.tm_be_r), step = Number(v.tm_trail_step), gap = Number(v.tm_trail_gap), trail = on(v.tm_trail);
  const lock = (g: number) => {
    let l: number | null = be > 0 && g + 1e-9 >= be ? 0 : null;
    if (trail && step > 0) {
      const k = Math.floor(g / step + 1e-9);
      if (k >= 1 && k * step - gap > 1e-9) l = Math.max(l ?? 0, k * step - gap);
    }
    return l;
  };
  const marks: string[] = [];
  let last: number | null = null;
  for (let g = 0.25; g <= 5 + 1e-9 && marks.length < 5; g += 0.25) {
    const l = lock(g);
    if (l !== null && l !== last) { marks.push(`+${+g.toFixed(2)}R \u2192 ${l === 0 ? "entry" : `+${+l.toFixed(2)}R`}`); last = l; }
  }
  const out = [marks.length ? `Stop: ${marks.join(", ")}${trail ? ", ..." : ""}` : "The stop never moves"];
  if (Number(v.tm_lock_at) > 0) out.push(`profit lock at ${Math.round(Number(v.tm_lock_at) * 100)}% of the way to the target keeps ${Math.round(Number(v.tm_lock_keep) * 100)}%`);
  if (on(v.tm_reversal)) out.push(`reversal-candle exit after +${v.tm_rev_min_r}R (${v.tm_candle_min}-min candles)`);
  if (Number(v.tm_stale_min) > 0) out.push(`no-follow-through exit after ${v.tm_stale_min} min`);
  return out.join(" · ") + ".";
}

function TradeManagerForm({ doc, onSaved, onError }: { doc: SettingsDoc } & FormProps) {
  const names = Object.keys(doc.risk);
  const [acct, setAcct] = useState(names.includes("US") ? "US" : names[0]);
  const [v, setV] = useState<Record<string, number | string | boolean>>(doc.risk[acct] ?? {});
  const [busy, setBusy] = useState(false);
  useEffect(() => setV(doc.risk[acct] ?? {}), [doc.risk, acct]);
  const saved = doc.risk[acct] ?? {};
  const keys = TM_KEYS.filter((k) => k in saved && doc.risk_fields[k]);
  const changed = keys.filter((k) => String(v[k]) !== String(saved[k]));
  const offDefault = Object.keys(TM_DEFAULTS).filter((k) => k in saved && String(v[k]) !== String(TM_DEFAULTS[k]));

  async function save() {
    setBusy(true);
    try {
      const changes = Object.fromEntries(changed.map((k) => [k, v[k]]));
      const r = await postJSON<{ changed: string[] }>(`${OPS}/settings/risk`, { account: acct, changes });
      onSaved(r.changed.length ? `${acct} Trade Manager saved: ${r.changed.join("; ")}. Every open ${acct} trade uses it from the next check.` : "Nothing changed.");
    } catch (e) { onError(`Not saved: ${errText(e)}`); } finally { setBusy(false); }
  }

  const field = (k: string) => {
    const f = doc.risk_fields[k];
    return (
      <div key={k} className="field">
        <label htmlFor={`tm-${k}`} className="field-label">{RISK_LABELS[k] ?? k}</label>
        {f.type === "bool" ? (
          <input id={`tm-${k}`} type="checkbox" checked={on(v[k])} onChange={(e) => setV({ ...v, [k]: e.target.checked })} />
        ) : (
          <input id={`tm-${k}`} type="number" inputMode="decimal" step={f.type === "int" ? 1 : "any"} min={f.min} max={f.max}
                 value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
        )}
      </div>
    );
  };

  return (
    <fieldset className="formblock" style={{ marginTop: 16 }}>
      <legend>Trade Manager</legend>
      <div className="filters" style={{ marginBottom: 10 }}>
        <div className="seg-ctl" role="group" aria-label="Account">
          {names.map((n) => (
            <button key={n} aria-pressed={n === acct} onClick={() => setAcct(n)}>{n}</button>
          ))}
        </div>
        <span className="small muted">One set per market: it manages every {acct} trade, whatever the scanner (v2 / v3 / v4 / v5 / rules).</span>
      </div>
      {TM_GROUPS.map(([title, ks]) => {
        const shown = ks.filter((k) => keys.includes(k));
        return shown.length ? (
          <div key={title}>
            <h3 className="small" style={{ margin: "8px 0 6px" }}>{title}</h3>
            <div className={`form-grid compact${title !== "On / off" && !on(v.trade_manager) ? " dimmed" : ""}`}>{shown.map(field)}</div>
          </div>
        ) : null;
      })}
      <p className="small muted" aria-live="polite" style={{ margin: "10px 0 0" }}>{tmPreview(v)}</p>
      <p className="small muted" style={{ margin: "6px 0 0" }}>The backtests use these saved values, so check a change there first.</p>
      <div className="actions">
        <button className="btn primary" onClick={save} disabled={busy || changed.length === 0}>
          {changed.length ? `Save ${acct} Trade Manager` : "No changes"}
        </button>
        <button className="btn" onClick={() => setV(saved)} disabled={busy || changed.length === 0}>Undo</button>
        <button className="btn" onClick={() => setV({ ...v, ...TM_DEFAULTS })} disabled={busy || offDefault.length === 0}>
          Defaults (+1R entry, +2R +1R, nothing else)
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
