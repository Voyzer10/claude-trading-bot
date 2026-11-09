"use client";

import { useState } from "react";
import type { Snapshot } from "@/lib/types";
import type { LiveTicks } from "@/lib/live";
import { price, timeIST } from "@/lib/format";
import SymbolIcon from "@/components/SymbolIcon";

/** Watch lists for the markets other than crypto (owner, 10 Nov 2026): NSE (Nifty 50, live from Zerodha when
 *  connected, else the last opening-range scan), US (the scanner's liquid list, every 5-minute candle) and the
 *  index F&O (Nifty / Bank Nifty opening range). Plus each market's opening-range breaks today. */

type Quote = { price: number; prev_close?: number | null; chg_pct?: number | null; t?: number };
type Hit = { symbol: string; side?: string; price?: number; last?: number; time?: string; at?: string; holding?: boolean;
  pct_now?: number; pct_over?: number; vol_x?: number; gap_pct?: number; range_high?: number; range_low?: number;
  or_high?: number; or_low?: number };
type Watch = { symbols?: string[]; quotes?: Record<string, Quote>; as_of?: string | null; hits?: Hit[]; hits_as_of?: string | null };
type Brk = { direction?: string | null; level?: number; or_high?: number; or_low?: number; close?: number; time?: string };

type Row = { sym: string; key: string; price: number | null; chg: number | null; live: boolean; hit?: Hit; note?: string };

const pct = (x: number | null | undefined) => (x === null || x === undefined ? "" : `${x > 0 ? "+" : ""}${x.toFixed(2)}%`);
const tone = (x: number | null | undefined) => (x === null || x === undefined ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "");

export function NseWatch({ snap, live }: { snap: Snapshot; live: LiveTicks | null }) {
  const w = (snap.markets.NSE?.watch ?? {}) as Watch;
  const hits = w.hits ?? [];
  const byHit = Object.fromEntries(hits.map((h) => [h.symbol, h]));
  const symbols = w.symbols ?? [];
  const rows: Row[] = [...symbols, ...hits.map((h) => h.symbol).filter((s) => !symbols.includes(s))].map((s) => {
    const t = live?.live ? live.ticks["NSE:" + s] : undefined;
    const q = w.quotes?.[s];
    const p = t?.ltp ?? q?.price ?? (byHit[s]?.last ?? null);
    const chg = t && t.close ? ((t.ltp - t.close) / t.close) * 100 : q?.chg_pct ?? null;
    return { sym: s, key: "NSE:" + s, price: p, chg, live: !!t, hit: byHit[s] };
  });
  const src = live?.live ? "live from Zerodha, every second" : w.as_of ? `last scan ${timeIST(w.as_of, true)} (connect Zerodha for live prices)` : "no scan yet today";
  return (
    <WatchList id="watch-nse" title={`NSE watch list: Nifty 50${hits.length ? ` + ${hits.filter((h) => !symbols.includes(h.symbol)).length} breaks` : ""}`}
               sub={`Prices ${src}. Breaks = opening-range breaks today across the NSE universe.`}
               rows={rows} cur="₹" />
  );
}

export function UsWatch({ snap }: { snap: Snapshot }) {
  const w = (snap.markets.US?.watch ?? {}) as Watch;
  const hits = (w.hits ?? []).map((h) => ({ ...h, time: h.time ?? h.at }));
  const byHit = Object.fromEntries(hits.map((h) => [h.symbol, h]));
  const symbols = w.symbols ?? [];
  const rows: Row[] = [...symbols, ...hits.map((h) => h.symbol).filter((s) => !symbols.includes(s))].map((s) => {
    const q = w.quotes?.[s];
    return { sym: s, key: "US:" + s, price: q?.price ?? byHit[s]?.price ?? null, chg: q?.chg_pct ?? null, live: false, hit: byHit[s] };
  });
  return (
    <WatchList id="watch-us" title={`US watch list: ${symbols.length || "—"} liquid names${hits.length ? ` + breaks` : ""}`}
               sub={w.as_of ? `Last 5-minute close ${timeIST(w.as_of, true)} IST; updated every candle while the US market is open.` : "Filled from the first 5-minute candle of the US session."}
               rows={rows} cur="$" />
  );
}

export function FnoWatch({ snap, live }: { snap: Snapshot; live: LiveTicks | null }) {
  const f = snap.markets.FNO ?? {};
  const idx: [string, string, string][] = [["NIFTY", "Nifty 50", "NSE:NIFTY50"], ["BANKNIFTY", "Bank Nifty", "NSE:BANKNIFTY"]];
  return (
    <section id="watch-fno" className="panel" aria-labelledby="watch-fno-h">
      <div className="panel-head">
        <div>
          <h2 id="watch-fno-h">F&amp;O watch: index opening range</h2>
          <p>{(f.status as string) ?? "Waiting for the session."} Mode: {(f.mode as string) ?? "—"}.</p>
        </div>
      </div>
      <div className="idx-grid">
        {idx.map(([k, name, tk]) => {
          const b = (f[k] ?? null) as Brk | null;
          const t = live?.live ? live.ticks[tk] : undefined;
          const chg = t && t.close ? ((t.ltp - t.close) / t.close) * 100 : null;
          return (
            <div key={k} className="stat">
              <span className="label">{name}</span>
              <span className="value num" style={{ fontSize: 20 }}>{t ? t.ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—"}</span>
              <span className={`sub ${tone(chg)}`}>{chg !== null ? `${pct(chg)} today` : "live level needs Zerodha"}</span>
              <span className="sub">
                {b && b.or_high !== undefined
                  ? `Opening range ${price(b.or_low)} – ${price(b.or_high)}${b.direction ? ` · broke ${b.direction} at ${b.time ?? "?"}` : " · no break yet"}`
                  : "Opening range not formed yet (09:15–09:30)"}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function WatchList({ id, title, sub, rows, cur }: { id: string; title: string; sub: string; rows: Row[]; cur: string }) {
  const [q, setQ] = useState("");
  const [f, setF] = useState("all");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const nBreaks = rows.filter((r) => r.hit).length;
  const filters: [string, string, number][] = [
    ["all", "All", rows.length], ["breaks", "Breaks", nBreaks],
    ["up", "Up", rows.filter((r) => (r.chg ?? 0) > 0).length], ["down", "Down", rows.filter((r) => (r.chg ?? 0) < 0).length],
  ];
  const shown = rows
    .filter((r) => !q || r.sym.toLowerCase().includes(q.trim().toLowerCase()))
    .filter((r) => f === "all" || (f === "breaks" ? !!r.hit : f === "up" ? (r.chg ?? 0) > 0 : (r.chg ?? 0) < 0))
    .sort((a, b) => Number(!!b.hit) - Number(!!a.hit));
  return (
    <section id={id} className="panel list-card" aria-labelledby={`${id}-h`}>
      <div className="watch-head">
        <h2 id={`${id}-h`}>{title}</h2>
        <p className="small muted">{sub}</p>
        <input type="search" placeholder="Search symbol" value={q} onChange={(e) => setQ(e.target.value)} aria-label={`Search ${title}`} />
        <div className="seg-ctl chips" role="group" aria-label="Filter">
          {filters.map(([k, label, n]) => (
            <button key={k} aria-pressed={f === k} onClick={() => setF(k)}>{label} <span className="muted">{n}</span></button>
          ))}
        </div>
      </div>
      {rows.length === 0 && <p className="muted small" style={{ padding: "0 16px 16px", margin: 0 }}>No prices yet: they come with the first scan of the session.</p>}
      {rows.length > 0 && shown.length === 0 && <p className="muted small" style={{ padding: "0 16px 16px", margin: 0 }}>Nothing matches.</p>}
      <div className="watch-rows">
      {shown.map((r) => {
        const isOpen = !!open[r.sym];
        const h = r.hit;
        const short = h?.side === "short";
        return (
          <div key={r.sym} className="list-row-wrap">
            <button className="list-row" aria-expanded={h ? isOpen : undefined} onClick={() => h && setOpen({ ...open, [r.sym]: !isOpen })}>
              <span className="lr-main">
                <b className="sym"><SymbolIcon id={r.key} />{r.sym}</b>
                <span className="small muted">
                  {h ? <span className={short ? "neg" : "pos"}>{short ? "Broke down" : "Broke out"} at {h.time ?? "?"}{h.holding === false ? " · back inside" : ""}</span>
                    : r.live ? "live" : "watching"}
                </span>
              </span>
              <span className="lr-side">
                <b className="num">{r.price !== null ? `${cur}${price(r.price)}` : "—"}</b>
                <span className={`small num ${tone(r.chg)}`}>{r.chg !== null ? pct(r.chg) : ""}</span>
              </span>
              {r.live && <span className="live-dot" aria-label="live" />}
            </button>
            {h && isOpen && (
              <dl className="kv lr-detail">
                <dt>Opening range</dt><dd className="num">{price(h.range_low ?? h.or_low)} – {price(h.range_high ?? h.or_high)}</dd>
                <dt>Break close</dt><dd className="num">{price(h.price)}</dd>
                {h.pct_now !== undefined && (<><dt>Now vs the range</dt><dd className={`num ${tone(short ? -h.pct_now : h.pct_now)}`}>{pct(h.pct_now)}</dd></>)}
                {h.pct_over !== undefined && (<><dt>Past the range</dt><dd className="num">{pct(h.pct_over)}</dd></>)}
                {h.vol_x !== undefined && (<><dt>Volume</dt><dd className="num">{h.vol_x}x</dd></>)}
                {h.gap_pct !== undefined && (<><dt>Opening gap</dt><dd className="num">{pct(h.gap_pct)}</dd></>)}
              </dl>
            )}
          </div>
        );
      })}
      </div>
    </section>
  );
}
