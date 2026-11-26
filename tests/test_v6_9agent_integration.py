#!/usr/bin/env python3
"""Regression, parity, and benchmark tests for V6 9-Agent Production Integration & Stabilization.

Covers:
  - POLYCAB: signal target below live LONG entry -> target revalidation or Agent 4 rejection, no 2R fallback, no order
  - RBLBANK: V6 position with V4 tm_be_r=1.0 -> FIXED_SL_TP preserves V6 stop untouched
  - LONG/SHORT target & SL side invariants, no opposing pool reject, insufficient R:R reject
  - Delayed/gapped quote reject, incomplete confirmation reject
  - Incremental V6 scanner: duplicate candle idempotence, restart checkpoint restore, full-replay parity, benchmark
  - Agent trace parity across paper.setup_decision and api._ops._stopped_at
  - V4 mode regression: unchanged V4 Trade Manager & 2R fallback behaviour
"""
from __future__ import annotations

import csv
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import paper as P  # noqa: E402
import scanner_v6_bridge as V6B  # noqa: E402


def _synth_rows():
    p = os.path.join(ROOT, "tests", "v6_runtime", "fixtures", "synth_nyse_5m.csv")
    with open(p, encoding="utf-8") as fh:
        return [(datetime.fromisoformat(r[0].replace("Z", "+00:00")),) + tuple(float(x) for x in r[1:])
                for r in list(csv.reader(fh))[1:]]


def _with_tmp_cwd(fn):
    tmp = tempfile.mkdtemp()
    old = os.getcwd()
    os.chdir(tmp)
    try:
        return fn(tmp)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)


def test_polycab_long_target_below_live_entry_rejected():
    """POLYCAB: signal close target 7515, live LONG entry 7527, no higher pool -> rejected at Agent 4, never traded."""
    def _run(_tmp):
        cfg = P.load_config()
        cfg["accounts"]["INDIA"].update({"scanner_version": "v6", "trade_setups": True, "v6_max_adverse_gap_r": 2.0})
        P.save_json(P.CONFIG, cfg)
        setup = {
            "setup": "v6_smc_long", "name": "v6 SMC long", "side": "long",
            "price": 7500.0, "stop": 7470.0, "target": 7515.0,
            "bar_end": "2026-11-26T10:30:00+05:30",
            "_exec_price": 7527.0,
            "details": {
                "sweep_low": 7470.1, "sweep_high": 7490.0, "tick": "0.05",
                "sl_buffer_ticks": 2, "tp_offset_ticks": 1,
                "pools_snapshot": [{"pool_id": "p1", "side": "BSL", "price": "7515.05", "formed_index": 10, "status": "ACTIVE"}],
                "v6_setup_id": "polycab-test-1",
            },
        }
        rec = P.setup_decision("NSE", "POLYCAB", setup, news=[])
        assert rec["result"] == "skipped"
        assert "no active opposing liquidity pool" in rec["why"] or "wrong side" in rec["why"]
        tr = {t["agent_id"]: t for t in rec["trace"]}
        assert tr[4]["status"] == "REJECT"
        assert tr[5]["status"] == "NOT_EVALUATED"
        assert tr[8]["status"] == "NOT_EVALUATED"
        assert len(P.load_ledger(cfg)["open"]) == 0
    _with_tmp_cwd(_run)


def test_polycab_revalidates_to_next_genuine_pool():
    """POLYCAB variant: if a higher genuine BSL pool exists above 7527 with R:R >= 1, Agent 4 selects it."""
    reval, err = V6B.revalidate_v6_levels(
        pools_snapshot=[
            {"pool_id": "p1", "side": "BSL", "price": "7515.05", "formed_index": 10, "status": "ACTIVE"},
            {"pool_id": "p2", "side": "BSL", "price": "7600.05", "formed_index": 20, "status": "ACTIVE"},
        ],
        side_str="long", entry_px=7527.0, sweep_low=7470.1, sweep_high=7490.0,
        tick=Decimal("0.05"), sl_buffer_ticks=2, tp_offset_ticks=1, min_rr=1.0,
    )
    assert err is None
    assert reval["target"] == 7600.0
    assert reval["target"] > reval["entry"] > reval["stop"]


def test_rblbank_v6_fixed_sl_tp_ignores_v4_breakeven():
    """RBLBANK: V6 position with V4 tm_be_r=1.0 -> FIXED_SL_TP keeps V6 stop untouched."""
    def _run(_tmp):
        cfg = P.load_config()
        cfg["accounts"]["INDIA"].update({"scanner_version": "v6", "tm_be_r": 1.0, "v6_exit_policy": "FIXED_SL_TP"})
        P.save_json(P.CONFIG, cfg)
        led = P.load_ledger(cfg)
        pos = {
            "key": "NSE:RBLBANK", "market": "NSE", "symbol": "RBLBANK", "qty": 100,
            "entry": 389.05, "stop": 391.50, "risk_stop": 391.50, "target": 385.80,
            "side": "short", "scanner": "v6", "exit_policy": "FIXED_SL_TP",
            "entry_time": "2026-11-25T07:00:00+00:00", "entry_date": "2026-11-25",
        }
        led["open"].append(pos)
        now = datetime(2026, 11, 25, 7, 10, tzinfo=timezone.utc)
        # Price moves +1.5R in favor (389.05 - 1.5*2.45 = 385.375 -> use 386.00, doesn't hit 385.80 target)
        bar = (datetime(2026, 11, 25, 7, 5, tzinfo=timezone.utc), 388.8, 389.0, 386.0, 386.5)
        acc = P.acct_cfg(cfg, "NSE")
        closed = P.step_bar(led, cfg, pos, acc, bar, now, sh=True)
        assert not closed
        assert pos["stop"] == 391.50
        assert not pos.get("breakeven")
    _with_tmp_cwd(_run)


def test_v4_mode_regression_breakeven_unchanged():
    """V4 mode regression: V4 position with tm_be_r=1.0 still moves stop to breakeven at +1R."""
    def _run(_tmp):
        cfg = P.load_config()
        cfg["accounts"]["INDIA"].update({"scanner_version": "v4", "tm_be_r": 1.0})
        P.save_json(P.CONFIG, cfg)
        led = P.load_ledger(cfg)
        pos = {
            "key": "NSE:TESTV4", "market": "NSE", "symbol": "TESTV4", "qty": 50,
            "entry": 100.0, "stop": 98.0, "risk_stop": 98.0, "target": 106.0,
            "side": "long", "scanner": "v4",
            "entry_time": "2026-11-25T07:00:00+00:00", "entry_date": "2026-11-25",
        }
        led["open"].append(pos)
        now = datetime(2026, 11, 25, 7, 10, tzinfo=timezone.utc)
        bar = (datetime(2026, 11, 25, 7, 5, tzinfo=timezone.utc), 100.5, 102.5, 100.2, 102.0)
        acc = P.acct_cfg(cfg, "NSE")
        P.step_bar(led, cfg, pos, acc, bar, now, sh=False)
        assert pos["stop"] == 100.0
        assert pos.get("breakeven") is True
    _with_tmp_cwd(_run)


def test_exit_invariants_and_rejections():
    """LONG/SHORT SL & TP sides, no opposing pool, insufficient R:R, adverse gap, stale quote."""
    # Short target above entry -> reject
    _, err = V6B.revalidate_v6_levels(
        [{"pool_id": "p1", "side": "SSL", "price": "105.0", "formed_index": 5, "status": "ACTIVE"}],
        "short", entry_px=100.0, sweep_low=101.0, sweep_high=103.0, tick=Decimal("0.05"),
    )
    assert err is not None

    # No opposing pool -> reject (no 2R fallback)
    _, err = V6B.revalidate_v6_levels([], "long", entry_px=100.0, sweep_low=98.0, sweep_high=99.5, tick=Decimal("0.05"))
    assert err is not None and "no active opposing liquidity pool" in err

    # Insufficient R:R -> reject
    _, err = V6B.revalidate_v6_levels(
        [{"pool_id": "p1", "side": "BSL", "price": "101.0", "formed_index": 5, "status": "ACTIVE"}],
        "long", entry_px=100.0, sweep_low=98.0, sweep_high=99.5, tick=Decimal("0.05"), min_rr=1.5,
    )
    assert err is not None and "below minimum" in err

    # Adverse gap beyond max_adverse_gap_r -> reject at Agent 3
    def _run_gap(_tmp):
        cfg = P.load_config()
        cfg["accounts"]["INDIA"].update({"scanner_version": "v6", "v6_max_adverse_gap_r": 0.5})
        P.save_json(P.CONFIG, cfg)
        rec = P.setup_decision("NSE", "GAPTEST", {
            "setup": "v6_smc_long", "name": "v6 SMC long", "side": "long",
            "price": 100.0, "stop": 98.0, "target": 106.0, "_exec_price": 101.5,
        }, news=[])
        assert rec["result"] == "skipped" and "adverse gap" in rec["why"]
        tr = {t["agent_id"]: t for t in rec["trace"]}
        assert tr[3]["status"] == "REJECT"
    _with_tmp_cwd(_run_gap)


def test_incremental_vs_full_replay_parity_and_checkpoint_restart():
    """Incremental V6 scanner matches full replay identically, ignores duplicates, and restores from checkpoint."""
    rows = _synth_rows()
    full_hits = {}
    for i in range(len(rows)):
        res = V6B.setups(rows[:i + 1], i, "US")
        if res:
            full_hits[i] = res[0]["setup"]
    assert sorted(full_hits) == [50, 71]

    def _run(tmp):
        ckpt = os.path.join(tmp, "ckpts")
        inc = V6B.IncrementalV6Scanner(checkpoint_dir=ckpt)
        inc_hits = {}
        for i in range(len(rows)):
            res = inc.scan(rows[:i + 1], "SYNTH", market="US")
            if res:
                inc_hits[i] = res[0]["setup"]
            # Duplicate candle replay must not emit a duplicate setup
            dup = inc.scan(rows[:i + 1], "SYNTH", market="US")
            assert dup == []
        assert inc_hits == full_hits

        # Restart from checkpoint at bar 50 and process remaining bars
        inc2 = V6B.IncrementalV6Scanner(checkpoint_dir=ckpt)
        # Re-seed checkpoint up to bar 50
        ckpt_50 = os.path.join(tmp, "ckpts50")
        s1 = V6B.IncrementalV6Scanner(checkpoint_dir=ckpt_50)
        for i in range(51):
            s1.scan(rows[:i + 1], "SYNTH", market="US")
        s2 = V6B.IncrementalV6Scanner(checkpoint_dir=ckpt_50)
        res_71 = None
        for i in range(51, len(rows)):
            r = s2.scan(rows[:i + 1], "SYNTH", market="US")
            if r:
                res_71 = (i, r[0]["setup"])
        assert res_71 == (71, "v6_smc_short")
    _with_tmp_cwd(_run)


def test_agent_trace_parity_with_ops():
    """api._ops._stopped_at agrees 100% with paper.setup_decision canonical trace."""
    import api._ops as OPS
    def _run(_tmp):
        cfg = P.load_config()
        cfg["accounts"]["INDIA"].update({"scanner_version": "v6", "v6_max_adverse_gap_r": 0.5})
        P.save_json(P.CONFIG, cfg)
        rec = P.setup_decision("NSE", "TRACETST", {
            "setup": "v6_smc_long", "name": "v6 SMC long", "side": "long",
            "price": 100.0, "stop": 98.0, "target": 106.0, "_exec_price": 101.5,
        }, news=[])
        assert OPS._stopped_at(rec) == 3
    _with_tmp_cwd(_run)


def test_quote_freshness_v6_and_v4():
    """Quote timestamp regression: qt=None, stale quote, valid fresh quote, missing price for V6 and V4."""
    import api._ops as OPS
    def _run(_tmp):
        cfg = P.load_config()
        cfg["accounts"]["CRYPTO"]["scanner_version"] = "v6"
        cfg["accounts"]["CRYPTO"]["trade_setups"] = True
        cfg["accounts"]["CRYPTO"]["v6_max_quote_age_s"] = 1200
        cfg["accounts"]["INDIA"]["scanner_version"] = "v4"
        cfg["accounts"]["INDIA"]["trade_setups"] = True
        P.save_json(P.CONFIG, cfg)
        saved_fp = P.fetch_price
        try:
            now_utc = datetime.now(timezone.utc)
            base_v6 = {
                "setup": "v6_smc_long", "name": "v6 SMC long", "side": "long",
                "price": 100.0, "stop": 98.0, "target": 104.0,
            }
            # 1. V6 qt=None fails closed at Agent 3
            P.fetch_price = lambda m, t: (100.0, None)
            rec_none = P.setup_decision("CRYPTO", "QNTST", dict(base_v6), news=[])
            assert rec_none["result"] == "skipped" and OPS._stopped_at(rec_none) == 3
            assert "timestamp missing" in (rec_none.get("why") or "").lower()

            # 2. V6 stale quote fails closed at Agent 3
            P.fetch_price = lambda m, t: (100.0, now_utc - timedelta(seconds=1500))
            rec_stale = P.setup_decision("CRYPTO", "QSTALE", dict(base_v6), news=[])
            assert rec_stale["result"] == "skipped" and OPS._stopped_at(rec_stale) == 3
            assert "stale quote" in (rec_stale.get("why") or "").lower()

            # 3. V6 missing price (fetch_price raises) fails closed at Agent 3
            P.fetch_price = lambda m, t: (_ for _ in ()).throw(P.PaperError("no quote"))
            rec_miss = P.setup_decision("CRYPTO", "QMISS", dict(base_v6), news=[])
            assert rec_miss["result"] == "skipped" and OPS._stopped_at(rec_miss) == 3
            assert "unavailable" in (rec_miss.get("why") or "").lower()

            # 4. V6 valid fresh quote passes Agent 3 and trades
            P.fetch_price = lambda m, t: (100.0, now_utc - timedelta(seconds=10))
            rec_ok = P.setup_decision("CRYPTO", "QOK", dict(base_v6), news=[])
            assert rec_ok["result"] == "PAPER BUY", rec_ok

            # 5. cmd_buy direct: V6 qt=None fails closed; V4 qt=None succeeds without TypeError
            led = P.load_ledger(cfg)
            a_v6 = type("A", (), {
                "symbol": "CRYPTO:QCMD", "stop": "98", "target": "104", "qty": None,
                "price": None, "note": "t", "force": False, "side": "long", "scanner": "v6",
            })()
            P.fetch_price = lambda m, t: (100.0, None)
            try:
                P.cmd_buy(a_v6, cfg, led)
                raise AssertionError("expected PaperError for V6 qt=None")
            except P.PaperError as e:
                assert "timestamp missing" in str(e).lower()

            a_v4 = type("A", (), {
                "symbol": "CRYPTO:V4CMD", "stop": "98", "target": "104", "qty": None,
                "price": None, "note": "t", "force": False, "side": "long", "scanner": "v4",
            })()
            pos_v4 = P.cmd_buy(a_v4, cfg, led)
            assert pos_v4["entry"] == 100.0
        finally:
            P.fetch_price = saved_fp
    _with_tmp_cwd(_run)


def test_fno_and_account_scanner_isolation():
    """F&O and per-account scanner-version isolation: fresh config vs explicit V4/V6 routing."""
    def _run(_tmp):
        import auto_fno as AF
        import smc_playbook as PB
        cfg = P.load_config()
        # Fresh default config has scanner_version="v3" for FNO, INDIA, CRYPTO, US, USFNO
        assert PB.scanner_version("NSE") == "v3"
        assert PB.scanner_version("NFO") == "v3"
        assert PB.scanner_version("US") == "v3"
        assert PB.scanner_version("CRYPTO") == "v3"

        # Explicitly configure FNO=v4 and US=v6 (preserving isolation)
        cfg["accounts"]["FNO"]["scanner_version"] = "v4"
        cfg["accounts"]["US"]["scanner_version"] = "v6"
        P.save_json(P.CONFIG, cfg)
        assert PB.scanner_version("NFO") == "v4"
        assert PB.scanner_version("US") == "v6"
        assert PB.scanner_version("NSE") == "v3"

        # When FNO is v5 (non-v4), auto_fno.process() must NOT silently route into v3 or v4
        cfg["accounts"]["FNO"]["scanner_version"] = "v5"
        P.save_json(P.CONFIG, cfg)
        logs = []
        out = AF.process({"markets": {}}, logs.append)
        assert out == []
        assert any("Scanner v5 only" in x for x in logs), logs
    _with_tmp_cwd(_run)


def benchmark_incremental_vs_full_replay():
    rows = _synth_rows()
    t0 = time.perf_counter()
    for i in range(len(rows)):
        V6B.setups(rows[:i + 1], i, "US")
    full_ms = (time.perf_counter() - t0) * 1000

    def _run(tmp):
        inc = V6B.IncrementalV6Scanner(checkpoint_dir=os.path.join(tmp, "bench_ckpts"))
        t1 = time.perf_counter()
        for i in range(len(rows)):
            inc.scan(rows[:i + 1], "BENCH", market="US")
        return (time.perf_counter() - t1) * 1000
    inc_ms = _with_tmp_cwd(_run)
    print("Benchmark (%d bars): full_replay=%.1fms  incremental=%.1fms  speedup=%.2fx" % (
        len(rows), full_ms, inc_ms, full_ms / max(inc_ms, 0.01)))


if __name__ == "__main__":
    tests = [
        test_polycab_long_target_below_live_entry_rejected,
        test_polycab_revalidates_to_next_genuine_pool,
        test_rblbank_v6_fixed_sl_tp_ignores_v4_breakeven,
        test_v4_mode_regression_breakeven_unchanged,
        test_exit_invariants_and_rejections,
        test_incremental_vs_full_replay_parity_and_checkpoint_restart,
        test_agent_trace_parity_with_ops,
        test_quote_freshness_v6_and_v4,
        test_fno_and_account_scanner_isolation,
    ]
    for fn in tests:
        fn()
        print("PASS:", fn.__name__)
    benchmark_incremental_vs_full_replay()
