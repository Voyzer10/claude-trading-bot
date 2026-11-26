"use client";

import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type ISeriesApi, type ISeriesPrimitive, type SeriesAttachedParameter, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import type { CanvasRenderingTarget2D } from "fancy-canvas";
import { getJSON } from "@/lib/api";

type ChartPos = {
  key: string; market: string; symbol: string; side?: string; qty?: number; entry: number | null; stop: number | null;
  risk_stop?: number; target?: number; entry_time?: string; exit_time?: string; exit?: number; reason?: string;
  setup_name?: string; liquidity?: string; entry_reason?: string; signal_at?: string; trailing?: boolean;
  breakeven?: boolean; locked?: boolean; trail_k?: number; last?: number; r?: number; pnl?: number;
  rr?: number | null; planned?: boolean;
};
type Marker = { t: number; kind: string; text: string };
type SetupLine = { kind: string; label: string; price: number; t1?: number; t2?: number };
type Verdict = { tone: "good" | "bad" | "flat"; title: string; lines: string[] };
/** What to chart: a paper position (open or closed) or a scanner candidate from the decisions log. */
export type ChartSource = { kind: "position"; key: string; entryTime?: string } | { kind: "decision"; time: string; symbol: string }
  | { kind: "timemachine"; time: string; symbol: string };
type Replay = {
  start: number; step: number; bars: number | null; paths: { end: "target" | "stop" | "neither"; r: number; c: number[] }[];
  r_hist: { edges: number[]; counts: number[] } | null;
  stats: { paths?: number; p_target?: number; p_stop?: number; p_neither?: number; avg_r?: number };
};
type ChartDoc = {
  chart: string; tf: string; open: boolean; box: boolean; note?: string | null;
  candles: [number, number, number, number, number][]; links: { name: string; url: string }[]; pos: ChartPos;
  markers?: Marker[]; setup_lines?: SetupLine[]; verdict?: Verdict; replay?: Replay;
};

const IST = 19800; // the chart's clock: IST, like the rest of the dashboard
const toT = (iso?: string | number | null) =>
  iso === undefined || iso === null ? null : ((typeof iso === "number" ? iso : Math.floor(new Date(iso).getTime() / 1000)) + IST) as UTCTimestamp;

function cssVar(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return /^#[0-9a-f]{6}$/i.test(v) ? v : fallback;
}
function rgba(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/** The long / short position box: the reward zone (entry -> target) and the risk zone (entry -> the original stop),
 *  from the entry candle to the exit (or the last candle while open). Drawn under the candles. */
class PositionBox implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<"Candlestick"> | null = null;
  constructor(private spec: { t1: Time; t2: Time; entry: number; target?: number; risk: number; good: string; bad: string }) {}
  attached(p: SeriesAttachedParameter<Time>) {
    this.chart = p.chart as IChartApi;
    this.series = p.series as ISeriesApi<"Candlestick">;
  }
  detached() { this.chart = null; this.series = null; }
  paneViews() {
    return [{
      zOrder: () => "bottom" as const,
      renderer: () => ({
        draw: (target: CanvasRenderingTarget2D) => {
          const { chart, series, spec } = this;
          if (!chart || !series) return;
          const ts = chart.timeScale();
          const x1 = ts.timeToCoordinate(spec.t1), x2 = ts.timeToCoordinate(spec.t2);
          const ye = series.priceToCoordinate(spec.entry), yr = series.priceToCoordinate(spec.risk);
          const yt = spec.target !== undefined ? series.priceToCoordinate(spec.target) : null;
          if (x1 === null || x2 === null || ye === null || yr === null) return;
          target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
            const left = Math.min(x1, x2) * hr, w = Math.max(Math.abs(x2 - x1) * hr, 24 * hr);
            const zone = (ya: number, yb: number, fill: string, edge: string) => {
              const top = Math.min(ya, yb) * vr, h = Math.abs(yb - ya) * vr;
              ctx.fillStyle = fill;
              ctx.fillRect(left, top, w, h);
              ctx.strokeStyle = edge;
              ctx.lineWidth = Math.max(1, hr);
              ctx.strokeRect(left, top, w, h);
            };
            if (yt !== null) zone(ye, yt, rgba(spec.good, 0.18), rgba(spec.good, 0.6));
            zone(ye, yr, rgba(spec.bad, 0.18), rgba(spec.bad, 0.6));
          });
        },
      }),
    }];
  }
}

/** How the 1,000 replays ended: the three outcomes and the spread of R. */
function ReplaySummary({ rp }: { rp: Replay }) {
  const s = rp.stats;
  if (!s.paths) return null;
  const pc = (x?: number) => `${Math.round((x ?? 0) * 100)}%`;
  const h = rp.r_hist;
  const labels = h ? h.counts.map((_, i) => i === 0 ? `≤${h.edges[0]}R` : i === h.edges.length ? `>${h.edges[h.edges.length - 1]}R`
    : `${h.edges[i - 1]}…${h.edges[i]}R`) : [];
  const max = h ? Math.max(1, ...h.counts) : 1;
  return (
    <div className="tmr">
      <div className="tmr-odds small num">
        <b>{s.paths} replays</b> × {rp.bars} candles:
        <span className="pos"> target first {pc(s.p_target)}</span> ·
        <span className="neg"> stop first {pc(s.p_stop)}</span> ·
        <span className="muted"> neither {pc(s.p_neither)}</span> · average <b>{(s.avg_r ?? 0) >= 0 ? "+" : ""}{(s.avg_r ?? 0).toFixed(2)}R</b>
      </div>
      {h && (
        <div className="tmr-hist" role="img" aria-label="How the replays ended, by R">
          {h.counts.map((n, i) => (
            <div key={i} className="tmr-col">
              <span className="tmr-bar" style={{ height: `${(n / max) * 100}%` }} data-tone={i === 0 ? "bad" : i >= 5 ? "good" : "flat"} />
              <span className="tmr-n small num">{n}</span>
              <span className="tmr-l small muted">{labels[i]}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ChartView({ src, onClose }: { src: ChartSource; onClose: () => void }) {
  const title = (src.kind === "position" ? src.key : src.symbol) + (src.kind === "timemachine" ? " · time machine" : "");
  const box = useRef<HTMLDivElement>(null);
  const dlg = useRef<HTMLDialogElement>(null);
  const [doc, setDoc] = useState<ChartDoc | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [fitFull, setFitFull] = useState(true);
  const chartRef = useRef<IChartApi | null>(null);
  const setupRangeRef = useRef<{ from: number; to: number } | null>(null);
  // where the person had scrolled / zoomed, kept across live refreshes
  const view = useRef<{ from: number; to: number; n: number } | null>(null);

  useEffect(() => {
    dlg.current?.showModal();
    view.current = null;
    const url = src.kind === "position"
      ? `/api/py/chart/position?${new URLSearchParams({ key: src.key, ...(src.entryTime ? { entry_time: src.entryTime } : {}) })}`
      : `/api/py/chart/${src.kind}?${new URLSearchParams({ time: src.time, symbol: src.symbol })}`;
    let stop = false, timer: ReturnType<typeof setTimeout> | undefined;
    const load = (first: boolean) => {
      getJSON<ChartDoc>(url)
        .then((d) => {
          if (stop) return;
          if (first) view.current = null;
          setDoc(d); setUpdated(new Date()); setErr(null);
          // live: an open trade every 20 s; a chart whose last candle is fresh (a skip, a time machine run) every 60 s
          const last = d.candles.length ? d.candles[d.candles.length - 1][0] : 0;
          const fresh = Date.now() / 1000 - last < 15 * 60;
          const every = d.open ? 20000 : fresh ? 60000 : 0;
          if (every) timer = setTimeout(() => load(false), every);
        })
        .catch((e) => {
          if (stop) return;
          if (first) setErr(String(e?.message ?? e));
          else timer = setTimeout(() => load(false), 30000);    // a failed refresh keeps the last chart, tries again
        });
    };
    load(true);
    const onVis = () => {               // a hidden tab does not poll; coming back refreshes at once
      if (document.hidden) { clearTimeout(timer); timer = undefined; }
      else if (!stop) { clearTimeout(timer); load(false); }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => { stop = true; clearTimeout(timer); document.removeEventListener("visibilitychange", onVis); };
  }, [src]);

  useEffect(() => {
    if (!doc || !box.current || !doc.candles.length) return;
    const good = cssVar("--good", "#6fcf97"), bad = cssVar("--bad", "#f0807a");
    const ink = cssVar("--ink", "#f1ebe1"), muted = cssVar("--muted", "#a89e90"), line = cssVar("--line", "#3a332c");
    const accent = cssVar("--accent", "#f0b541");
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: muted, fontFamily: "IBM Plex Mono, ui-monospace, monospace" },
      grid: { vertLines: { color: rgba(line, 0.5) }, horzLines: { color: rgba(line, 0.5) } },
      rightPriceScale: { borderColor: line },
      timeScale: { borderColor: line, timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    const s = chart.addSeries(CandlestickSeries, {
      upColor: good, downColor: bad, borderUpColor: good, borderDownColor: bad, wickUpColor: good, wickDownColor: bad,
    });
    const data = doc.candles.map(([t, o, h, l, c]) => ({ time: toT(t)!, open: o, high: h, low: l, close: c }));
    const p = doc.pos;
    // keep the whole box (entry, stop, target) on screen, not only the candles
    const levels = [p.entry, p.risk_stop ?? p.stop, p.stop, p.trail_k ? null : p.target].filter((x): x is number => typeof x === "number");
    s.applyOptions({
      autoscaleInfoProvider: (orig: () => { priceRange: { minValue: number; maxValue: number } | null } | null) => {
        const r = orig();
        if (!r || !r.priceRange || !doc.box || !levels.length) return r;
        return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, ...levels), maxValue: Math.max(r.priceRange.maxValue, ...levels) } };
      },
    });
    s.setData(data);
    const times = data.map((d) => d.time as number);
    const snap = (t: number | null) => {           // the candle that contains t
      if (t === null) return null;
      let best: number | null = null;
      for (const x of times) if (x <= t) best = x; else break;
      return (best ?? times[0]) as UTCTimestamp;
    };
    const tEntry = snap(toT(p.entry_time));
    const tExit = p.exit_time ? snap(toT(p.exit_time)) : (times[times.length - 1] as UTCTimestamp);
    const risk = p.risk_stop ?? p.stop;
    const planned = p.planned ? "planned " : "";
    if (doc.box && tEntry !== null && tExit !== null && p.entry !== null && risk !== null) {
      s.attachPrimitive(new PositionBox({ t1: tEntry, t2: tExit, entry: p.entry, target: p.trail_k ? undefined : (p.target ?? undefined), risk, good, bad }));
      s.createPriceLine({ price: p.entry, color: ink, lineWidth: 1, lineStyle: LineStyle.Solid, title: planned + "entry" });
      if (p.target != null && !p.trail_k) s.createPriceLine({ price: p.target, color: good, lineWidth: 1, lineStyle: LineStyle.Dashed, title: planned + "target" });
      s.createPriceLine({ price: risk, color: bad, lineWidth: 1, lineStyle: LineStyle.Dashed, title: planned + "stop" });
      if (p.stop !== null && Math.abs(p.stop - risk) > 1e-9) {
        s.createPriceLine({ price: p.stop, color: accent, lineWidth: 2, lineStyle: LineStyle.Solid,
                            title: p.trailing ? "trailing stop" : p.locked ? "locked stop" : "stop now" });
      }
      if (p.exit != null) s.createPriceLine({ price: p.exit, color: muted, lineWidth: 1, lineStyle: LineStyle.Dotted, title: "exit" });
    }
    for (const sl of doc.setup_lines ?? []) {
      const col = sl.kind === "choch" ? accent : sl.kind === "sweep" ? "#a855f7" : "#38bdf8";
      const st1 = sl.t1 != null ? snap(toT(sl.t1)) : null;
      const st2 = sl.t2 != null ? snap(toT(sl.t2)) : null;
      if (st1 !== null && st2 !== null && st1 < st2) {
        const seg = chart.addSeries(LineSeries, {
          color: col, lineWidth: 2, lineStyle: LineStyle.Dotted,
          lastValueVisible: true, priceLineVisible: false, crosshairMarkerVisible: false, title: sl.label,
        });
        seg.setData([{ time: st1, value: sl.price }, { time: st2, value: sl.price }]);
      } else {
        s.createPriceLine({ price: sl.price, color: col, lineWidth: 1, lineStyle: LineStyle.Dashed, title: sl.label });
      }
    }
    const short = p.side === "short";
    // server markers: CHoCH, BOS, sweep, signal, confirm, entry / skip, Trade Manager actions, exit
    type MStyle = { color: string; shape: "circle" | "square" | "arrowUp" | "arrowDown"; position: "aboveBar" | "belowBar" };
    const style: Record<string, MStyle> = {
      choch: { color: accent, shape: "square", position: short ? "belowBar" : "aboveBar" },
      bos: { color: "#38bdf8", shape: "square", position: short ? "belowBar" : "aboveBar" },
      sweep: { color: "#a855f7", shape: short ? "arrowUp" : "arrowDown", position: short ? "aboveBar" : "belowBar" },
      signal: { color: accent, shape: "circle", position: short ? "aboveBar" : "belowBar" },
      confirm: { color: good, shape: "circle", position: short ? "belowBar" : "aboveBar" },
      entry: { color: ink, shape: short ? "arrowDown" : "arrowUp", position: short ? "aboveBar" : "belowBar" },
      skip: { color: bad, shape: "square", position: short ? "belowBar" : "aboveBar" },   // the other side: no pile-up
      tm: { color: accent, shape: "circle", position: short ? "belowBar" : "aboveBar" },
      win: { color: good, shape: "square", position: short ? "belowBar" : "aboveBar" },
      loss: { color: bad, shape: "square", position: short ? "aboveBar" : "belowBar" },
      exit: { color: muted, shape: "square", position: short ? "belowBar" : "aboveBar" },
      info: { color: muted, shape: "circle", position: "aboveBar" },
    };
    const marks: SeriesMarker<Time>[] = (doc.markers ?? [])
      .map((m) => ({ m, t: snap(toT(m.t)) }))
      .filter((x) => x.t !== null)
      .map(({ m, t }) => ({ time: t as Time, text: m.text, ...(style[m.kind] ?? style.info) }));
    marks.sort((a, b) => (a.time as number) - (b.time as number));
    // only join labels that land on the exact same candle and side
    const lastLabel: Record<string, SeriesMarker<Time> | undefined> = {};
    for (const mk of marks) {
      const prev = lastLabel[mk.position];
      if (prev && mk.text && (mk.time as number) === (prev.time as number)) {
        prev.text = `${prev.text} · ${mk.text}`;
        mk.text = "";
      } else if (mk.text) {
        lastLabel[mk.position] = mk;
      }
    }
    createSeriesMarkers(s, marks);
    // the time machine's replayed paths, from the decision candle on: green = target first, red = stop, grey = neither
    const rp = doc.replay;
    if (rp && rp.paths.length) {
      const col = { target: good, stop: bad, neither: muted } as const;
      const order = [...rp.paths].sort((a, b) => (a.end === "neither" ? 0 : 1) - (b.end === "neither" ? 0 : 1));
      for (const path of order) {
        const ls = chart.addSeries(LineSeries, {
          color: rgba(col[path.end], path.end === "neither" ? 0.35 : 0.55), lineWidth: 1,
          lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
        });
        ls.setData(path.c.map((v, k) => ({ time: (rp.start + k * rp.step + IST) as UTCTimestamp, value: v })));
      }
    }
    chartRef.current = chart;
    const firstMark = marks.length ? (marks[0].time as number) : null;
    const startAt = firstMark !== null && tEntry !== null ? Math.min(firstMark, tEntry as number) : (tEntry as number | null);
    if (startAt !== null) {
      const before = (box.current?.clientWidth ?? 800) < 600 ? 10 : 30;
      const i = Math.max(0, times.indexOf(startAt) - before);
      setupRangeRef.current = { from: i, to: times.length + 5 };
    } else {
      setupRangeRef.current = null;
    }
    const was = view.current;
    if (was) {                // a live refresh: keep the person's view; at the right edge, follow the new candles
      const added = times.length - was.n;
      const follow = was.to >= was.n - 2;
      chart.timeScale().setVisibleLogicalRange(follow ? { from: was.from + added, to: was.to + added } : { from: was.from, to: was.to });
    } else if (fitFull || !setupRangeRef.current) {
      chart.timeScale().fitContent();
    } else {
      chart.timeScale().setVisibleLogicalRange(setupRangeRef.current);
    }
    return () => {
      const r = chart.timeScale().getVisibleLogicalRange();
      if (r) view.current = { from: r.from, to: r.to, n: times.length };
      chartRef.current = null;
      chart.remove();
    };
  }, [doc, fitFull]);

  const p = doc?.pos;
  const r = p && p.entry != null && p.risk_stop != null ? Math.abs(p.entry - p.risk_stop) : null;
  const rr = p && r && p.entry != null && p.target != null ? Math.abs(p.target - p.entry) / r : null;
  const v = doc?.verdict;
  return (
    <dialog ref={dlg} className="chart-dialog" onClose={onClose} aria-labelledby="chart-title">
      <div className="chart-head">
        <div>
          <h2 id="chart-title" style={{ margin: 0, fontSize: 16 }}>{title}{p ? ` · ${p.side ?? "long"}` : ""}</h2>
          {p && (
            <p className="small muted" style={{ margin: "2px 0 0" }}>
              {p.setup_name ?? "trade"}{p.planned ? " · planned" : ""}
              {p.entry != null ? ` · entry ${p.entry}` : ""}{p.risk_stop ?? p.stop ? ` · stop ${p.risk_stop ?? p.stop}` : ""}
              {p.target != null && !p.trail_k ? ` · target ${p.target}` : ""}
              {rr ? ` · ${rr.toFixed(1)}R` : ""} · {doc?.tf} candles, IST
            </p>
          )}
          {updated && (
            <p className="small muted chart-live" style={{ margin: "2px 0 0" }}>
              {doc?.open ? <><span className="chart-live-dot" aria-hidden="true" />live · </> : null}
              updated {updated.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}
              {doc?.open ? " · refreshes every 20 s" : ""}
            </p>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            className="btn small-btn"
            onClick={() => {
              const next = !fitFull;
              setFitFull(next);
              view.current = null;
              if (chartRef.current) {
                if (next || !setupRangeRef.current) chartRef.current.timeScale().fitContent();
                else chartRef.current.timeScale().setVisibleLogicalRange(setupRangeRef.current);
              }
            }}
          >
            {fitFull ? "Zoom to setup" : "Full chart"}
          </button>
          <button className="btn small-btn" onClick={() => dlg.current?.close()} aria-label="Close chart">Close</button>
        </div>
      </div>
      {err && <div className="notice bad">Chart not loaded: {err}</div>}
      {v && (
        <div className={`chart-verdict tone-${v.tone}`} role="status">
          <b>{v.title}</b>
          <ul>{v.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </div>
      )}
      {!doc && !err && <p className="muted small">Loading candles…</p>}
      {doc && !doc.candles.length && <div className="notice bad">No candles came back for {doc.chart}.</div>}
      <div ref={box} className="chart-box" />
      {doc?.replay && <ReplaySummary rp={doc.replay} />}
      {doc?.note && <p className="small muted" style={{ margin: "6px 0 0" }}>{doc.note}</p>}
      <p className="small muted chart-legend" style={{ margin: "6px 0 0" }}>
        Markers: ■ CHoCH / BOS · ▼▲ sweep · ● pattern / confirm / Trade Manager · arrow = entry · red ■ = skipped · exit in green (win) / red (loss)
      </p>
      {!!doc?.links.length && (
        <div className="actions" style={{ marginTop: 8 }}>
          <span className="small muted">Open the symbol on (no drawings there):</span>
          {doc.links.map((l) => (
            <a key={l.url} className="btn small-btn" href={l.url} target="_blank" rel="noopener noreferrer">{l.name}</a>
          ))}
        </div>
      )}
    </dialog>
  );
}
