#!/usr/bin/env python3
"""research_costs (21 Nov 2026): one research cost model per market, equal to the main backtests' formulas
(research_scanner_v4.py nse-sv4 / us-sv4 / crypto-sv4 before the move), entry AND exit, long and short, small and
large orders, never counted twice. Offline.

    python tests/test_research_costs.py
"""
import copy
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import paper as P  # noqa: E402
import research_costs as RC  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def old_nse(cfg, sym, entry, stop, exit_px, side):
    """research_scanner_v4.py nse-sv4 cost_fn, verbatim (before 21 Nov 2026)."""
    acc = cfg["accounts"]["INDIA"]
    risk = abs(entry - stop)
    qty = int(min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / entry))
    if qty < 1:
        return None
    o, c = ("buy", "sell") if side == "long" else ("sell", "buy")
    return (P.charges(cfg, "NSE", sym, o, qty * entry) + P.charges(cfg, "NSE", sym, c, qty * exit_px)) / (qty * risk)


def old_us(cfg, entry, stop, exit_px):
    fee = float(cfg["accounts"]["US"].get("fee_pct", 0)) / 100 + 0.0002
    return (entry + exit_px) * fee / abs(entry - stop)


def old_crypto_main(cfg, entry, stop, exit_px):
    fee = float(cfg["accounts"]["CRYPTO"]["fee_pct"]) / 100
    return (entry + exit_px) * fee / abs(entry - stop)


if __name__ == "__main__":
    cfg = copy.deepcopy(P.DEFAULT_CONFIG)
    rnd = random.Random(5)
    # --- NSE: identical to the old nse-sv4 formula, long and short, many sizes
    bad = 0
    for _ in range(2000):
        e = rnd.uniform(20, 5000)
        risk = e * rnd.uniform(0.001, 0.02)
        side = rnd.choice(("long", "short"))
        stop = e - risk if side == "long" else e + risk
        x = e + rnd.uniform(-2, 3) * risk * (1 if side == "long" else -1)
        a, b = old_nse(cfg, "X", e, stop, x, side), RC.cost_r("nse", "X", side, e, x, stop, cfg)
        if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-12):
            bad += 1
    check("NSE: research_costs == the old nse-sv4 formula on 2,000 random long / short trades", bad == 0, bad)
    # small order: Rs 2,000 a share, stop 10 away -> qty min(3000 / 10, 25000 / 2000) = 12 (Rs 24,000)
    got = RC.nse("X", "long", 2000.0, 2010.0, 1990.0, cfg)
    fe = P.charges(cfg, "NSE", "X", "buy", 12 * 2000.0)
    fx = P.charges(cfg, "NSE", "X", "sell", 12 * 2010.0)
    check("NSE small order: qty 12; entry (buy) and exit (sell) charges both counted; R = (entry + exit) / (qty x risk)",
          got["qty"] == 12 and abs(got["entry_fees"] - fe) < 1e-12 and abs(got["exit_fees"] - fx) < 1e-12
          and abs(got["total_r"] - (fe + fx) / (12 * 10.0)) < 1e-12, got)
    check("NSE: STT only on the sell order, stamp only on the buy order (long: exit has STT)",
          got["exit_fees"] > got["entry_fees"], (got["entry_fees"], got["exit_fees"]))
    sh = RC.nse("X", "short", 2000.0, 1990.0, 2010.0, cfg)
    check("NSE short: the entry is the sell (STT), the exit the buy (stamp)",
          abs(sh["entry_fees"] - P.charges(cfg, "NSE", "X", "sell", 12 * 2000.0)) < 1e-12
          and abs(sh["exit_fees"] - P.charges(cfg, "NSE", "X", "buy", 12 * 1990.0)) < 1e-12, sh)
    big = copy.deepcopy(cfg)
    big["accounts"]["INDIA"].update(capital=10_000_000, max_loss_per_trade=300_000)
    g2 = RC.nse("X", "long", 2000.0, 2010.0, 1990.0, big)
    check("NSE large order (Rs 25 lakh): brokerage capped at the flat Rs 20 per order, so a lower cost per rupee",
          g2["qty"] == 1250 and g2["total_r"] < got["total_r"], (g2["qty"], g2["total_r"], got["total_r"]))
    check("NSE: an order the INDIA sizing cannot size (one share > the position cap) -> no cost (None)",
          RC.nse("X", "long", 30000.0, 30100.0, 29900.0, cfg) is None)
    check("NSE: spread and slippage are reported missing, not filled in",
          got["spread_r"] is None and got["slippage_r"] is None and got["total_r"] == got["fees_r"])
    # --- US
    bad = 0
    for _ in range(2000):
        e = rnd.uniform(5, 900)
        risk = e * rnd.uniform(0.001, 0.02)
        side = rnd.choice(("long", "short"))
        stop = e - risk if side == "long" else e + risk
        x = e + rnd.uniform(-2, 3) * risk * (1 if side == "long" else -1)
        if abs(old_us(cfg, e, stop, x) - RC.cost_r("us", "X", side, e, x, stop, cfg)) > 1e-12:
            bad += 1
    check("US: research_costs == the old us-sv4 formula on 2,000 random long / short trades", bad == 0, bad)
    u = RC.us("X", "long", 100.0, 102.0, 99.0, cfg)
    check("US: per side on the entry AND the exit price: (100 + 102) x 0.02% / 1 = 0.0404R; fees 0 (fee_pct 0)",
          abs(u["total_r"] - 0.0404) < 1e-12 and u["fees_r"] == 0 and abs(u["spread_slippage_r"] - 0.0404) < 1e-12, u)
    us_fee = copy.deepcopy(cfg)
    us_fee["accounts"]["US"]["fee_pct"] = 0.01
    u2 = RC.us("X", "short", 100.0, 97.0, 101.0, us_fee)
    check("US short with a 0.01% fee: fees (197 x 0.0001) and the 0.02% allowance kept apart, total = their sum once",
          abs(u2["fees_r"] - 0.0197) < 1e-12 and abs(u2["spread_slippage_r"] - 0.0394) < 1e-12
          and abs(u2["total_r"] - 0.0591) < 1e-12, u2)
    # --- crypto: unchanged
    check("crypto harness unchanged: 0.118% of the entry / risk (unverified source)",
          abs(RC.cost_r("crypto", "BTC", "long", 50000.0, 51000.0, 49500.0) - 0.118 / 100 * 50000 / 500) < 1e-12)
    check("crypto-sv4 main formula unchanged: (entry + exit) x fee_pct a side / risk",
          abs(RC.crypto_main("BTC", "long", 50000.0, 51000.0, 49500.0, cfg)["total_r"]
              - old_crypto_main(cfg, 50000.0, 49500.0, 51000.0)) < 1e-12)
    print("\n%d failed" % len(FAILS) if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
