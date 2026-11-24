"""Backtest metrics, computed only from the run's own simulation ledger and equity curve (never estimated).

A metric that is mathematically undefined is reported as null with a reason, never as 0 or infinity:
win rate with no closed trades, profit factor with no losing trades, average win / loss with none of that kind,
ending equity while an open position cannot be marked (UNSCORABLE).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

Q2, Q4 = Decimal("0.01"), Decimal("0.0001")


def _d(v: Any) -> Decimal:
    return Decimal(str(v))


def _s(v: Optional[Decimal], q: Optional[Decimal] = None) -> Optional[str]:
    if v is None:
        return None
    return str(v.quantize(q) if q is not None else v)


def drawdown(points: List[Optional[Decimal]], start: Decimal) -> Dict[str, Optional[str]]:
    """Max peak-to-trough decline of the scorable equity points (start equity is the first peak)."""
    peak, max_abs, max_pct = start, Decimal(0), Decimal(0)
    for e in points:
        if e is None:
            continue
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_abs:
            max_abs = dd
        if peak > 0 and dd / peak * 100 > max_pct:
            max_pct = dd / peak * 100
    return {"max_drawdown": _s(max_abs), "max_drawdown_pct": _s(max_pct, Q4)}


def sample(curve: List[Dict[str, Any]], n: int = 500) -> List[Dict[str, Any]]:
    if len(curve) <= n:
        return list(curve)
    step = (len(curve) - 1) / (n - 1)
    idx = sorted({round(i * step) for i in range(n)} | {len(curve) - 1})
    return [curve[i] for i in idx]


def compute(ledger_state: Dict[str, Any], summary: Dict[str, Any], curve: List[Dict[str, Any]],
            trades: List[Dict[str, Any]], half_spread_ticks: int, tick_size: float) -> Dict[str, Any]:
    start = _d(ledger_state["starting_budget"])
    closed = [t for t in trades if t["status"] != "ENTERED"]
    realized = [_d(t["realized_pnl"]) for t in closed]
    wins = [r for r in realized if r > 0]
    losses = [r for r in realized if r < 0]
    n = len(closed)
    gross = sum((_d(t["gross_pnl"]) for t in closed), Decimal(0))
    net = sum(realized, Decimal(0))
    end_equity = _d(summary["equity"]) if summary.get("equity") is not None else None
    tick = _d(repr(tick_size))
    spread = Decimal(0)
    for t in trades:
        q, m = _d(t["quantity"]), _d(t["contract_multiplier"])
        legs = 1 + (1 if t["status"] == "STOPPED_OUT" else 0)
        spread += half_spread_ticks * tick * q * m * legs
    rr = [_d(t["net_rr"]) for t in trades if t.get("net_rr") is not None]
    r_mult = [_d(t["realized_pnl"]) / _d(t["loss_estimate"]) for t in closed
              if t.get("loss_estimate") not in (None, "0") and _d(t["loss_estimate"]) > 0]
    rej: Dict[str, int] = {}
    for r in ledger_state["rejections"]:
        rej[r["code"]] = rej.get(r["code"], 0) + 1
    out: Dict[str, Any] = {
        "currency": ledger_state["currency"],
        "starting_equity": str(start),
        "ending_equity": _s(end_equity),
        "ending_equity_status": summary["mtm_status"],
        "ending_cash": summary["cash"],
        "gross_pnl": str(gross),
        "net_pnl": str(net),
        "unrealized_pnl_open": summary.get("unrealized_pnl") if summary["open_positions"] else "0",
        "return_pct": None if end_equity is None else _s((end_equity - start) / start * 100, Q4),
        "total_trades": n,
        "open_trades_at_end": summary["open_positions"],
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "breakeven_trades": n - len(wins) - len(losses),
        "win_rate_pct": None if n == 0 else _s(Decimal(len(wins)) * 100 / n, Q2),
        "average_win": None if not wins else _s(sum(wins, Decimal(0)) / len(wins), Q4),
        "average_loss": None if not losses else _s(sum(losses, Decimal(0)) / len(losses), Q4),
        "profit_factor": None if not losses else _s(sum(wins, Decimal(0)) / -sum(losses, Decimal(0)), Q4),
        "profit_factor_note": None if losses else ("no losing trades: undefined" if wins else "no closed trades"),
        "average_planned_net_rr": None if not rr else _s(sum(rr, Decimal(0)) / len(rr), Q4),
        "average_realized_r": None if not r_mult else _s(sum(r_mult, Decimal(0)) / len(r_mult), Q4),
        "fees_total": ledger_state["fees_total"],
        "slippage_total": ledger_state["slippage_total"],
        "spread_cost_included_in_slippage": str(spread),
        "rejected_entries": rej,
        "equity_points": len(curve),
        "unscorable_equity_points": sum(1 for p in curve if p["equity"] is None),
    }
    out.update(drawdown([None if p["equity"] is None else _d(p["equity"]) for p in curve], start))
    return out
