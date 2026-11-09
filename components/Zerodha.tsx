"use client";

import { useEffect, useState } from "react";
import { getJSON, postJSON, errText } from "@/lib/api";
import type { LiveTicks } from "@/lib/live";

type Status = {
  configured: boolean;
  connected: boolean;
  user: string | null;
  since: string | null;
  expires: string | null;
  orders: string;
  ticker: { running: boolean; age_s: number | null; instruments: number };
};

const INDICES: [string, string][] = [["NSE:NIFTY50", "Nifty 50"], ["NSE:BANKNIFTY", "Bank Nifty"], ["NSE:INDIAVIX", "India VIX"]];
const SECTOR_START = 3; // after Nifty, Bank Nifty and VIX come the sector indices

const fmt = (x: number) => x.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const istTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" }) : "";

/** Zerodha (Kite Connect) as the Indian market data source: the daily login and a live index strip.
 *  Data only: the server refuses every order endpoint. */
export default function Zerodha({ live }: { live: LiveTicks | null }) {
  const [st, setSt] = useState<Status | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  const load = () =>
    getJSON<Status>("/api/py/kite/status")
      .then(setSt)
      .catch(() => setMissing(true)); // cloud mode: no Zerodha endpoints

  useEffect(() => {
    load();
    const q = new URLSearchParams(window.location.search).get("kite");
    if (q) {
      setMsg(q === "connected" ? "Zerodha connected: Indian prices now come from Kite." : `Zerodha: ${q}`);
      window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    }
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  if (missing) return null;

  async function logout() {
    if (!window.confirm("Disconnect Zerodha for today? Indian prices go back to Yahoo / the model.")) return;
    try {
      setSt(await postJSON<Status>("/api/py/kite/logout"));
      setMsg("Disconnected.");
    } catch (e) {
      setMsg(`Not done: ${errText(e)}`);
    }
  }

  const on = !!st?.connected;
  return (
    <section id="zerodha" className="panel" aria-labelledby="kite-h">
      <div className="panel-head">
        <div>
          <h2 id="kite-h">Zerodha live data</h2>
          <p>
            Indian market prices (NSE, F&amp;O) from Kite. Paper trades only: the bot can not place an order on Zerodha.
          </p>
        </div>
        {st && st.configured && (
          on ? (
            <button className="btn" onClick={logout}>Disconnect</button>
          ) : (
            <a className="btn primary" href="/api/py/kite/login">Connect Zerodha</a>
          )
        )}
      </div>
      {msg && <div className="notice" style={{ marginBottom: 10 }}>{msg}</div>}
      {!st && <div className="muted small">Loading…</div>}
      {st && !st.configured && (
        <div className="notice">
          Keys not set on the server. Add <code>KITE_API_KEY</code> and <code>KITE_API_SECRET</code> to{" "}
          <code>/etc/trader/trader.env</code>, then <code>sudo systemctl restart trader-api trader-runner trader-ticker</code>.
        </div>
      )}
      {st && st.configured && (
        <div className="kite-status small">
          <span className={`chip ${on ? "c-good" : "c-bad"}`}>{on ? "connected" : "not connected today"}</span>
          {on ? (
            <span className="muted">
              {st.user} · since {istTime(st.since)} · expires {istTime(st.expires)} ·{" "}
              {st.ticker.running ? `live stream: ${st.ticker.instruments} instruments` : "live stream not running (trader-ticker)"}
            </span>
          ) : (
            <span className="muted">Kite logins expire every morning. Until you connect, Indian prices come from Yahoo and F&amp;O from the model.</span>
          )}
          <span className="chip">orders: blocked</span>
        </div>
      )}
      {on && (() => {
        const list = live?.indices?.length ? live.indices : INDICES;
        const change = (k: string) => {
          const t = live?.ticks[k];
          return { t, ch: t && t.close ? ((t.ltp - t.close) / t.close) * 100 : null };
        };
        const cls = (ch: number | null) => (ch === null ? "" : ch > 0 ? "pos" : ch < 0 ? "neg" : "");
        return (
          <>
            <div className="kite-indices">
              {list.slice(0, SECTOR_START).map(([k, name]) => {
                const { t, ch } = change(k);
                return (
                  <div key={k} className="stat">
                    <span className="label">{name}</span>
                    <span className="value num" style={{ fontSize: 19 }}>{t ? fmt(t.ltp) : "—"}</span>
                    <span className={`sub ${cls(ch)}`}>
                      {ch === null ? (live?.live ? "waiting for a tick" : "market closed or stream off") : `${ch > 0 ? "+" : ""}${ch.toFixed(2)}% today`}
                    </span>
                  </div>
                );
              })}
            </div>
            {list.length > SECTOR_START && (
              <>
                <h3 className="subtitle" style={{ margin: "14px 0 6px" }}>Sector indices</h3>
                <div className="kite-sectors" role="list">
                  {list.slice(SECTOR_START).map(([k, name]) => {
                    const { t, ch } = change(k);
                    return (
                      <div key={k} className="kite-sector" role="listitem">
                        <span className="name">{name}</span>
                        <span className="num">{t ? fmt(t.ltp) : "—"}</span>
                        <span className={`num ${cls(ch)}`}>{ch === null ? "" : `${ch > 0 ? "+" : ""}${ch.toFixed(2)}%`}</span>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
            {!!live?.missing?.length && (
              <p className="small muted" style={{ marginTop: 8 }}>Zerodha did not recognise: {live.missing.join(", ")}</p>
            )}
          </>
        );
      })()}
    </section>
  );
}
