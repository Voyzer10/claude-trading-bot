#!/usr/bin/env python3
"""One research cost model per market (21 Nov 2026), shared by the main backtests (research_scanner_v4.py nse-sv4 /
us-sv4 / crypto-sv4) and the research harnesses (sweep, bos, entry, research_tf). Research only: no trading
behaviour, no broker behaviour. Every formula below is the main backtest's, moved here unchanged:

  NSE     paper.charges (equity intraday: brokerage, STT, exchange, SEBI, stamp, GST) on the buy order AND the sell
          order, at the actual entry and exit prices, for the INDIA account's sizing:
            qty = int(min(max_loss_per_trade / risk per share, capital x max_position_pct / 100 / entry))
          (qty < 1: the trade cannot be sized -> no cost, the trade is left out of net results, as the main backtest
          does). Config: paper.DEFAULT_CONFIG (as nse-sv4). Spread and slippage: NO value exists in the code
          -> reported as missing (None), never filled in.
  US      per side, on the entry AND the exit price: the account fee_pct (paper config "US", 0 by default) plus a 0.02%
          allowance labelled "assumed spread/slippage" (research_v3.py, research_abcd.py, research_usorb.py; the
          same 0.0002 in us-sv4). That allowance is ONE combined number: spread and slippage are not separable.
  CRYPTO  unchanged (data source and fee configuration not verified): the research harnesses keep
          research_tf.COST_PCT["crypto"] (0.118% of the entry, round trip); the main crypto-sv4 keeps its
          (entry + exit) x fee_pct a side. The two are NOT normalised here, on purpose; both are reported.

All prices are real prices (positive); `risk` = |entry - stop| per unit; costs come back in money per unit and in R
(cost / (qty x risk) for NSE, cost per unit / risk otherwise: identical to the main backtest)."""
import paper as P

US_SPREAD_SLIP_SIDE = 0.0002      # 0.02% a side, "assumed spread/slippage" (combined; see the docstring)
CRYPTO_HARNESS_PCT = 0.118        # research_tf.COST_PCT["crypto"], round trip, % of the entry (unchanged)
_CFG = []


def _config():
    """paper.load_config() once per process (us-sv4 / crypto-sv4 read the paper config file)."""
    if not _CFG:
        _CFG.append(P.load_config())
    return _CFG[0]


def nse(sym, side, entry, exit_px, stop, cfg=None):
    """The nse-sv4 cost. {"qty", "entry_fees", "exit_fees", "fees_r", "spread_r", "slippage_r", "total_r"} or None
    when the INDIA sizing gives less than one share."""
    cfg = cfg or P.DEFAULT_CONFIG
    acc = cfg["accounts"]["INDIA"]
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    qty = int(min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / entry))
    if qty < 1:
        return None
    o, c = ("buy", "sell") if side == "long" else ("sell", "buy")
    fe = P.charges(cfg, "NSE", sym, o, qty * entry)
    fx = P.charges(cfg, "NSE", sym, c, qty * exit_px)
    fees_r = (fe + fx) / (qty * risk)
    return {"qty": qty, "entry_fees": fe, "exit_fees": fx, "fees_r": fees_r, "spread_r": None, "slippage_r": None,
            "total_r": fees_r, "missing": "spread, slippage (no value in the code)"}


def us(sym, side, entry, exit_px, stop, cfg=None):
    """The us-sv4 cost, split into the account fee and the spread/slippage allowance (per side, entry + exit)."""
    cfg = cfg or _config()
    fee_side = float(cfg["accounts"]["US"].get("fee_pct", 0)) / 100
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    fees_r = (entry + exit_px) * fee_side / risk
    ss_r = (entry + exit_px) * US_SPREAD_SLIP_SIDE / risk
    return {"qty": None, "entry_fees": entry * fee_side, "exit_fees": exit_px * fee_side, "fees_r": fees_r,
            "spread_slippage_r": ss_r, "spread_r": None, "slippage_r": None, "total_r": fees_r + ss_r,
            "missing": "spread and slippage separately (one combined 0.02%/side allowance)"}


def crypto_harness(sym, side, entry, exit_px, stop, cfg=None):
    """Unchanged research-harness crypto cost (COST_PCT, entry only). UNVERIFIED data source / fees."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    r = CRYPTO_HARNESS_PCT / 100 * entry / risk
    return {"qty": None, "entry_fees": None, "exit_fees": None, "fees_r": None, "spread_r": None, "slippage_r": None,
            "total_r": r, "missing": "everything separable: one unverified round-trip percentage"}


def crypto_main(sym, side, entry, exit_px, stop, cfg=None):
    """crypto-sv4's own cost (kept for that backtest): (entry + exit) x the CRYPTO account fee_pct a side."""
    cfg = cfg or _config()
    fee = float(cfg["accounts"]["CRYPTO"]["fee_pct"]) / 100
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return {"qty": None, "entry_fees": entry * fee, "exit_fees": exit_px * fee, "fees_r": (entry + exit_px) * fee / risk,
            "spread_r": None, "slippage_r": None, "total_r": (entry + exit_px) * fee / risk,
            "missing": "spread, slippage (none modelled)"}


HARNESS = {"nse": nse, "us": us, "crypto": crypto_harness}


def cost_r(market, sym, side, entry, exit_px, stop, cfg=None):
    """The research harnesses' cost in R for one closed trade (None = not sizeable, NSE only)."""
    got = HARNESS[market](sym, side, entry, exit_px, stop, cfg)
    return None if got is None else got["total_r"]
