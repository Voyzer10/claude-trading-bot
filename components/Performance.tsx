"use client";

import { useEffect, useState } from "react";
import { getJSON, OPS, errText } from "@/lib/api";
import { currencyOf, money } from "@/lib/format";

type Acc = {
  trades: number; wins: number; pnl: number; today: number; d7: number; d30: number;
  best: number | null; worst: number | null; win_rate: number | null; avg_r: number | null;
};
type Perf = {
  prefs: { usd_inr: number; daily_goal_inr: number };
  accounts: Record<string, Acc>;
  daily: { day: string; pnl_inr: number; cum_inr: number }[];
  inr: { today: number; d7: number; d30: number; all: number };
  month: { days_traded: number; green_days: number; red_days: number; pnl_inr: number; goal_inr: number };
  open_positions: number;
  total_trades: number;
};

const inr = (x: number) => money(x, "₹");
const tone = (x: number) => (x > 0 ? "pos" : x < 0 ? "neg" : "");

/** P&L against the goal (₹500/day by default), in rupees across all paper accounts. */
export default function Performance({ refreshKey }: { refreshKey: number }) {
  const [p, setP] = useState<Perf | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [period, setPeriod] = useState("today");
  const [openAcc, setOpenAcc] = useState<Record<string, boolean>>({});

  useEffect(() => {
    getJSON<Perf>(`${OPS}/performance`).then((x) => { setP(x); setErr(null); }).catch((e) => setErr(errText(e)));
  }, [refreshKey]);

  if (err) return null; // the ops API is not available (cloud mode)
  if (!p) return null;
  const goal = p.prefs.daily_goal_inr;
  const monthPct = p.month.goal_inr > 0 ? Math.max(0, Math.min(100, (p.month.pnl_inr / p.month.goal_inr) * 100)) : 0;

  const periods: [string, string][] = [["today", "Today"], ["d7", "7 days"], ["month", "Month"], ["all", "All time"]];
  const hero: Record<string, { value: number; sub: string; bar: number | null }> = {
    today: { value: p.inr.today, sub: `goal ${inr(goal)}`, bar: goal > 0 ? Math.max(0, Math.min(100, (p.inr.today / goal) * 100)) : null },
    d7: { value: p.inr.d7, sub: `30 days ${inr(p.inr.d30)}`, bar: null },
    month: { value: p.month.pnl_inr, sub: `goal so far ${inr(p.month.goal_inr)} · ${p.month.green_days} green / ${p.month.red_days} red days`, bar: monthPct },
    all: { value: p.inr.all, sub: "since the paper accounts started", bar: null },
  };
  const h = hero[period];

  return (
    <>
      <section id="performance" className="panel hero" aria-labelledby="perf-h">
        <div className="seg" role="tablist" aria-label="Period">
          {periods.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={period === k} onClick={() => setPeriod(k)}>{label}</button>
          ))}
        </div>
        <h2 id="perf-h" className="hero-label">Profit and loss · all paper accounts in ₹</h2>
        <div className={`hero-value num ${tone(h.value)}`}>{inr(h.value)}</div>
        <div className="small muted">{h.sub}</div>
        {h.bar !== null && (
          <div className="track hero-track" aria-hidden="true"><div className="fill" style={{ width: `${h.bar}%` }} /></div>
        )}
        {p.daily.length > 0 && <DailyBars days={p.daily} goal={goal} />}
        <p className="small muted" style={{ margin: "10px 0 0" }}>
          US$ at ₹{p.prefs.usd_inr}. Goal ₹{goal}/day. {p.total_trades} closed trades, {p.open_positions} open. Judge after 30+ trades.
        </p>
      </section>

      {Object.keys(p.accounts).length > 0 && (
        <section className="panel list-card" aria-labelledby="acc-h">
          <h2 id="acc-h" className="list-title">Accounts</h2>
          {Object.entries(p.accounts).map(([name, a]) => {
            const cur = currencyOf(name);
            const isOpen = !!openAcc[name];
            return (
              <div key={name} className="list-row-wrap">
                <button className="list-row" aria-expanded={isOpen} onClick={() => setOpenAcc({ ...openAcc, [name]: !isOpen })}>
                  <span className="lr-main">
                    <b>{name}</b>
                    <span className="small muted">
                      {a.trades} trades · {a.win_rate !== null ? `${a.win_rate}% win` : "no win rate yet"} ·{" "}
                      <span className={tone(a.avg_r ?? 0)}>{a.avg_r !== null ? `${a.avg_r > 0 ? "+" : ""}${a.avg_r}R` : "—"}</span>
                    </span>
                  </span>
                  <span className="lr-side">
                    <b className={`num ${tone(a.pnl)}`}>{money(a.pnl, cur)}</b>
                    <span className="small muted">all time</span>
                  </span>
                  <span className="chev" aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
                </button>
                {isOpen && (
                  <dl className="kv lr-detail">
                    <dt>Today</dt><dd className={`num ${tone(a.today)}`}>{money(a.today, cur)}</dd>
                    <dt>7 days</dt><dd className={`num ${tone(a.d7)}`}>{money(a.d7, cur)}</dd>
                    <dt>30 days</dt><dd className={`num ${tone(a.d30)}`}>{money(a.d30, cur)}</dd>
                    <dt>All</dt><dd className={`num ${tone(a.pnl)}`}>{money(a.pnl, cur)}</dd>
                    <dt>Best / worst</dt><dd className="num">{money(a.best, cur)} / {money(a.worst, cur)}</dd>
                  </dl>
                )}
              </div>
            );
          })}
        </section>
      )}
    </>
  );
}

function DailyBars({ days, goal }: { days: Perf["daily"]; goal: number }) {
  const last = days.slice(-30);
  const max = Math.max(goal, ...last.map((d) => Math.abs(d.pnl_inr)), 1);
  const W = 100 / Math.max(last.length, 10); // at least 10 slots so one or two days do not fill the width
  return (
    <figure style={{ margin: "14px 0 0" }}>
      <figcaption className="small muted" style={{ marginBottom: 6 }}>
        Daily P&amp;L · last {last.length} trading days (dashed line = goal)
      </figcaption>
      <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="daybars" role="img"
           aria-label={`Daily P&L for ${last.length} days`}>
        <line x1="0" x2="100" y1="20" y2="20" className="axis" />
        <line x1="0" x2="100" y1={20 - (goal / max) * 19} y2={20 - (goal / max) * 19} className="goal" />
        {last.map((d, i) => {
          const h = (Math.abs(d.pnl_inr) / max) * 19;
          return (
            <rect key={d.day} x={i * W + W * 0.15} width={W * 0.7} y={d.pnl_inr >= 0 ? 20 - h : 20} height={Math.max(h, 0.3)}
                  className={d.pnl_inr >= 0 ? "up" : "down"}>
              <title>{`${d.day}: ₹${d.pnl_inr.toFixed(2)} (running total ₹${d.cum_inr.toFixed(2)})`}</title>
            </rect>
          );
        })}
      </svg>
      <div className="timeline-axis"><span>{last[0].day}</span><span>{last[last.length - 1].day}</span></div>
    </figure>
  );
}
