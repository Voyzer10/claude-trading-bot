"""Regression tests for Chart Testing V6 validation consistency (Findings 1-4)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from api._chart_test import _analyze_v6, _norm_candles


def _make_bars(ohlc_list):
    return _norm_candles([[i * 300, o, h, l, c, 1000] for i, (o, h, l, c) in enumerate(ohlc_list)])


def _bullish_setup_base(confirm_bars, include_high_pool=True, include_c1=True):
    """Build deterministic OHLC series producing:
    Bearish trend (SH1, SH2 -> LH, SL1, SL2 -> LL)
    -> CHoCH (bullish close above SH2)
    -> Higher high / BSL pool (optional above entry)
    -> Reversal-confirming BOS
    -> SSL sweep
    -> Bullish Engulfing pattern
    -> caller-provided confirmation candles & C+1 open bar.
    """
    high_peak = 2520.0 if include_high_pool else 2486.0
    bars = [
        # 0..6: initial peak SH1 (~2505) and drop to SL1 (~2480)
        (2498, 2500, 2496, 2499),
        (2499, 2502, 2498, 2501),
        (2501, 2505, 2500, 2504),  # SH1
        (2504, 2504, 2494, 2495),
        (2495, 2496, 2488, 2489),
        (2489, 2490, 2483, 2484),
        (2484, 2485, 2480, 2481),  # SL1
        # 7..13: lower high LH (~2492) and drop to lower low LL (~2470)
        (2481, 2486, 2480, 2485),
        (2485, 2490, 2484, 2489),
        (2489, 2492, 2488, 2491),  # LH (protected SH for bullish CHoCH)
        (2491, 2491, 2482, 2483),
        (2483, 2484, 2476, 2477),
        (2477, 2478, 2470, 2471),  # LL
        (2471, 2476, 2471, 2475),
        # 14..18: rally and close > 2492 => Bullish CHoCH, forming swing high pool
        (2475, 2484, 2474, 2483),
        (2483, 2495, 2482, 2494),  # CHoCH break
        (2494, 2498, 2493, 2497),
        (2497, high_peak, 2496, high_peak - 1.0),  # swing high (optional BSL pool above later entry)
        (high_peak - 1.0, high_peak - 1.0, 2492, 2493),
        # 19..24: pullback to HL (2486, confirmed SSL pool) then break above swing high -> BOS
        (2493, 2494, 2488, 2489),
        (2489, 2490, 2485, 2486),  # HL (SSL pool at 2485)
        (2486, 2491, 2486, 2490),
        (2490, 2495, 2489, 2494),
        (2494, high_peak + 1.0 if not include_high_pool else 2500.0, 2493, high_peak + 0.5 if not include_high_pool else 2499.0),
        # Wait: ensure swing high before BOS is broken without sweeping high_peak if include_high_pool
    ]
    return bars


def _canonical_asserts(test_case, res):
    v = res["validation"]
    mods = {m["key"]: m for m in res["v6_flow"]["modules"]}
    chk = {c["step"]: c for c in res["checklist"]}
    cnc = {c["name"]: c for c in res["concepts"]}

    test_case.assertEqual(mods["A"]["passed"], v["structure_passed"])
    test_case.assertEqual(mods["B"]["passed"], v["liquidity_passed"])
    test_case.assertEqual(mods["C"]["passed"], v["pattern_passed"])
    test_case.assertEqual(mods["D"]["passed"], v["confirmation_passed"])
    test_case.assertEqual(mods["E"]["passed"], v["setup_valid"])

    test_case.assertEqual(chk["1. CHoCH"]["passed"], v["choch_passed"])
    test_case.assertEqual(chk["2. BOS"]["passed"], v["bos_passed"])
    test_case.assertEqual(chk["3. Liquidity Sweep"]["passed"], v["liquidity_passed"])
    test_case.assertEqual(chk["4. Candlestick Pattern"]["passed"], v["pattern_passed"])
    test_case.assertEqual(chk["5. 3-Candle Confirm & Execution"]["passed"], v["setup_valid"])

    test_case.assertEqual(cnc["CHoCH"]["passed"], v["choch_passed"])
    test_case.assertEqual(cnc["BOS"]["passed"], v["bos_passed"])
    test_case.assertEqual(cnc["Liquidity Sweep"]["passed"], v["liquidity_passed"])
    test_case.assertEqual(cnc["Candlestick Pattern"]["passed"], v["pattern_passed"])
    test_case.assertEqual(cnc["3-Candle Confirm"]["passed"], v["confirmation_passed"])
    test_case.assertEqual(cnc["Structural SL"]["passed"], v["setup_valid"])
    test_case.assertEqual(cnc["Pool TP"]["passed"], v["target_pool_passed"])

    if v["setup_valid"]:
        test_case.assertGreaterEqual(len(res["trades"]), 1)
    else:
        test_case.assertEqual(res["trades"], [])


class TestChartV6Validation(unittest.TestCase):
    def _build_full_series(self, confirm_bars, include_far_bsl=True, include_c1=True, bos_high=124.5):
        """Construct clean series where V6 produces CHoCH -> Reversal BOS -> SSL Sweep -> Bullish Engulfing."""
        top_pool = 128.0 if include_far_bsl else 119.8
        rev_sh = bos_high - 1.0
        bars = [
            (116, 118, 115, 117),      # 0
            (117, 119, 116, 118),      # 1
            (118, top_pool, 117, top_pool - 1),  # 2: SH0
            (top_pool - 1, top_pool - 1, 114, 115),  # 3
            (115, 116, 112, 113),      # 4
            (113, 114, 110, 111),      # 5: SL0 (low=110)
            (111, 113, 110.5, 112),    # 6
            (112, 115, 111.5, 114),    # 7
            (114, 116, 113, 115),      # 8: LH1 (high=116, protected SH)
            (115, 115.5, 111, 112),    # 9
            (112, 112.5, 108, 109),    # 10
            (109, 109.5, 105, 106),    # 11: LL1 (low=105)
            (106, 109, 106, 108),      # 12
            (108, 114, 107.5, 113.5),  # 13
            (113.5, 117.5, 113, 117),  # 14: CHoCH close > 116 (BULLISH TRANSITION)
            (117, 118.5, 116.5, 118),  # 15
            (118, rev_sh, 117.5, rev_sh - 0.5),  # 16: SH_rev
            (rev_sh - 0.5, rev_sh - 0.5, 116, 116.5),  # 17
            (116.5, 117, 114, 114.5),  # 18
            (114.5, 115, 112, 113),    # 19: HL_ssl (SSL pool at 112)
            (113, 115.5, 112.5, 115),  # 20
            (115, 118, 114.8, 117.5),  # 21
            (117.5, bos_high, 117, bos_high - 0.3),  # 22: Reversal-confirming BOS
            (bos_high - 0.3, bos_high - 0.2, 116, 116.5),  # 23
            (116.5, 116.8, 113.5, 114),# 24
            # 25: SSL Sweep of HL_ssl (112): wick below 112 to 111.2, close back >= 112.6
            (114, 114.5, 111.2, 112.6),
            # 26..27: Bullish Engulfing pattern (after sweep!)
            (113.6, 113.8, 112.4, 112.8),  # 26: bearish candle
            (112.7, 114.4, 112.5, 114.2),  # 27: bullish engulfing (body 112.7..114.2 engulfs 112.8..113.6)
        ]
        bars.extend(confirm_bars)
        if include_c1:
            last_c = bars[-1][3]
            bars.append((last_c + 0.1, last_c + 1.2, last_c - 0.1, last_c + 1.0))
        return _make_bars(bars)

    def test_finding1_rejects_fewer_than_three_confirmation_candles(self):
        rows = self._build_full_series(
            confirm_bars=[
                (114.2, 115.2, 114.0, 115.0),  # 28: confirm 1/3 only
                (115.0, 115.1, 114.3, 114.5),  # 29: bearish bar -> fails 3-candle confirm
                (114.5, 114.8, 114.2, 114.6),  # 30
            ],
            include_far_bsl=True,
        )
        res = _analyze_v6(rows, {"min_rr": 1.0, "direction": "both"})
        self.assertEqual(res["trades"], [])
        self.assertFalse(res["validation"]["confirmation_passed"])
        self.assertLess(res["validation"]["confirmation_count"], 3)
        _canonical_asserts(self, res)

    def test_finding1_accepts_three_distinct_completed_confirmation_candles(self):
        # Prior active BSL pool at 124.5; entry ~ 116.5, SL ~ 111.1 -> risk ~ 5.4, reward ~ 8.0 -> R:R ~ 1.48 >= 1.0
        rows = self._build_full_series(
            confirm_bars=[
                (114.2, 115.0, 114.0, 114.9),  # 28: confirm 1/3
                (114.9, 115.8, 114.7, 115.6),  # 29: confirm 2/3
                (115.6, 116.6, 115.4, 116.4),  # 30: confirm 3/3
            ],
            include_far_bsl=True,
            bos_high=124.5,
        )
        res = _analyze_v6(rows, {"min_rr": 1.0, "direction": "both"})
        self.assertEqual(len(res["trades"]), 1)
        tr = res["trades"][0]
        self.assertEqual(res["validation"]["confirmation_count"], 3)
        self.assertTrue(res["validation"]["confirmation_passed"])
        self.assertTrue(res["validation"]["target_pool_passed"])
        self.assertEqual(tr["entry_index"], 31)  # C+1 Open after 3rd confirmation candle (#30)
        max_hi = max(r[2] for r in rows)
        min_lo = min(r[3] for r in rows)
        self.assertLessEqual(tr["tp"], max_hi)
        self.assertGreaterEqual(tr["tp"], min_lo)
        self.assertLess(tr["tp_pool_index"], tr["entry_index"])
        _canonical_asserts(self, res)

    def test_finding3_rejects_trade_when_no_prior_opposing_pool_exists(self):
        # top_pool=119.8 (bar 2) and rev_sh=119.5 are both TAKEN by bar 22 BOS (close 120.2),
        # and confirm_bars close at 120.8 -> entry ~120.9 > bar 22 high (120.5), so NO active BSL pool > entry!
        rows = self._build_full_series(
            confirm_bars=[
                (114.2, 117.0, 114.0, 116.8),
                (116.8, 119.5, 116.6, 119.2),
                (119.2, 121.0, 119.0, 120.8),
            ],
            include_far_bsl=False,
            bos_high=120.5,
        )
        res = _analyze_v6(rows, {"min_rr": 1.0, "direction": "both"})
        self.assertEqual(res["trades"], [])
        self.assertFalse(res["validation"]["target_pool_passed"])
        self.assertFalse(res["validation"]["execution_passed"])
        self.assertTrue(any("NO_ELIGIBLE_OPPOSING_POOL" in r for r in res["validation"]["rejection_reasons"]))
        _canonical_asserts(self, res)

    def test_finding4_never_marks_open_without_c1_entry_or_all_module_e_gates(self):
        # Missing C+1 bar
        rows = self._build_full_series(
            confirm_bars=[
                (114.2, 115.0, 114.0, 114.9),
                (114.9, 115.8, 114.7, 115.6),
                (115.6, 116.6, 115.4, 116.4),
            ],
            include_far_bsl=True,
            include_c1=False,
            bos_high=124.5,
        )
        res = _analyze_v6(rows, {"min_rr": 1.0, "direction": "both"})
        self.assertEqual(res["trades"], [])
        self.assertFalse(res["validation"]["execution_passed"])
        self.assertTrue(any("C+1" in r for r in res["validation"]["rejection_reasons"]))
        _canonical_asserts(self, res)

        # Unmet min_rr
        rows_full = self._build_full_series(
            confirm_bars=[
                (114.2, 115.0, 114.0, 114.9),
                (114.9, 115.8, 114.7, 115.6),
                (115.6, 116.6, 115.4, 116.4),
            ],
            include_far_bsl=True,
            include_c1=True,
            bos_high=120.5,
        )
        res_rr = _analyze_v6(rows_full, {"min_rr": 1.0, "direction": "both"})
        self.assertEqual(res_rr["trades"], [])
        self.assertFalse(res_rr["validation"]["execution_passed"])
        _canonical_asserts(self, res_rr)

    def test_status_semantics_raw_sweeps_and_global_patterns_never_mark_setup_pass(self):
        # Simple oscillation that triggers raw sweeps & global patterns, but NO CHoCH->BOS setup qualifies
        bars = []
        for i in range(30):
            base = 100.0 + (2.0 if i % 4 < 2 else -2.0)
            bars.append((base, base + 2.5, base - 2.5, base + (1.0 if i % 2 == 0 else -1.0)))
        res = _analyze_v6(_make_bars(bars), {"min_rr": 1.0, "direction": "both"})
        v = res["validation"]
        self.assertEqual(res["trades"], [])
        self.assertEqual(v["setup_sweep_count"], 0)
        self.assertEqual(v["setup_pattern_count"], 0)
        # Even if raw sweeps or global patterns exist, setup-stage PASS must remain False
        self.assertFalse(v["liquidity_passed"])
        self.assertFalse(v["pattern_passed"])
        chk = {c["step"]: c for c in res["checklist"]}
        self.assertFalse(chk["3. Liquidity Sweep"]["passed"])
        self.assertFalse(chk["4. Candlestick Pattern"]["passed"])
        _canonical_asserts(self, res)


if __name__ == "__main__":
    unittest.main()
