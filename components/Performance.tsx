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

  useEffect(() => {
    getJSON<Perf>(`${OPS}/performance`).then((x) => { setP(x); setErr(null); }).catch((e) => setErr(errText(e)));
  }, [refreshKey]);

  if (err) return null; // the dashboard API is not reachable; the page shows that error already
  if (!p) return null;
  const goal = p.prefs.daily_goal_inr;
  const monthPct = p.month.goal_inr > 0 ? Math.max(0, Math.min(100, (p.month.pnl_inr / p.month.goal_inr) * 100)) : 0;

  return (
    <section id="performance" className="panel" aria-labelledby="perf-h">
      <div className="panel-head">
        <div>
          <h2 id="perf-h">Performance vs goal</h2>
          <p>
            All paper accounts in rupees (US$ at ₹{p.prefs.usd_inr}). Goal ₹{goal}/day. {p.total_trades} closed trades,{" "}
            {p.open_positions} open. Judge after 30+ trades.
          </p>
        </div>
      </div>
      <div className="markets">
        <div className={`stat stripe ${p.inr.today >= goal ? "s-good" : p.inr.today < 0 ? "s-bad" : ""}`}>
          <span className="label">Today</span>
          <span className={`value ${tone(p.inr.today)}`}>{inr(p.inr.today)}</span>
          <span className="sub">goal {inr(goal)}</span>
        </div>
        <div className="stat">
          <span className="label">This month</span>
          <span className={`value ${tone(p.month.pnl_inr)}`}>{inr(p.month.pnl_inr)}</span>
          <span className="sub">
            goal so far {inr(p.month.goal_inr)} · {p.month.green_days} green / {p.month.red_days} red days
          </span>
          <div className="track" style={{ marginTop: 4 }} aria-hidden="true">
            <div className="fill" style={{ width: `${monthPct}%` }} />
          </div>
        </div>
        <div className="stat">
          <span className="label">Last 7 days</span>
          <span className={`value ${tone(p.inr.d7)}`}>{inr(p.inr.d7)}</span>
          <span className="sub">30 days {inr(p.inr.d30)}</span>
        </div>
        <div className="stat">
          <span className="label">All time</span>
          <span className={`value ${tone(p.inr.all)}`}>{inr(p.inr.all)}</span>
          <span className="sub">since the paper accounts started</span>
        </div>
      </div>

      {p.daily.length > 0 && <DailyBars days={p.daily} goal={goal} />}

      {Object.keys(p.accounts).length > 0 && (
        <div className="tablewrap" style={{ marginTop: 14 }}>
          <table>
            <thead>
              <tr><th>Account</th><th>Trades</th><th>Win rate</th><th>Avg R</th><th>Today</th><th>7 days</th><th>All</th><th>Best / worst</th></tr>
            </thead>
            <tbody>
              {Object.entries(p.accounts).map(([name, a]) => {
                const cur = currencyOf(name);
                return (
                  <tr key={name}>
                    <td>{name}</td>
                    <td className="num">{a.trades}</td>
                    <td className="num">{a.win_rate !== null ? `${a.win_rate}%` : "—"}</td>
                    <td className={`num ${tone(a.avg_r ?? 0)}`}>{a.avg_r !== null ? `${a.avg_r > 0 ? "+" : ""}${a.avg_r}R` : "—"}</td>
                    <td className={`num ${tone(a.today)}`}>{money(a.today, cur)}</td>
                    <td className={`num ${tone(a.d7)}`}>{money(a.d7, cur)}</td>
                    <td className={`num ${tone(a.pnl)}`}>{money(a.pnl, cur)}</td>
                    <td className="num">{money(a.best, cur)} / {money(a.worst, cur)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function DailyBars({ days, goal }: { days: Perf["daily"]; goal: number }) {
  const last = days.slice(-30);
  const max = Math.max(goal, ...last.map((d) => Math.abs(d.pnl_inr)), 1);
  const W = 100 / Math.max(last.length, 10); // at least 10 slots so one or two days do not fill the width
  return (
    <figure style={{ margin: "14px 0 0" }}>
      <figcaption className="small muted" style={{ marginBottom: 6 }}>
        Daily P&amp;L, last {last.length} trading days (dashed line = goal)
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
