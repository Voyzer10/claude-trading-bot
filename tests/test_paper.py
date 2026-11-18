"""
Money math of the paper account (paper.py): sizing, fees, closing, shorts, futures margin, stops.
A wrong sign here quietly changes every paper result, so these must pass before real money.

    python -m unittest discover tests
"""
import copy
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paper as P  # noqa: E402


def order(symbol, stop, target, price, side="long", force=False):
    return SimpleNamespace(symbol=symbol, stop=str(stop), target=str(target), price=str(price), qty=None, lots=None,
                           note="test", force=force, side=side)


class PaperMoney(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)  # paper.py's files are relative: keep the real ledger out of it
        self.cfg = copy.deepcopy(P.DEFAULT_CONFIG)
        self.led = P.load_ledger(self.cfg)
        self.now = datetime.now(timezone.utc)
        self._out = sys.stdout
        sys.stdout = open(os.devnull, "w")  # cmd_buy/close_position print a report

    def tearDown(self):
        sys.stdout.close()
        sys.stdout = self._out
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def cash(self, acc):
        return self.led["accounts"][acc]["cash"]

    def test_long_loss_at_stop_is_capped_and_cash_matches_pnl(self):
        start = self.cash("CRYPTO")
        pos = P.cmd_buy(order("CRYPTO:BTC", 98, 104, 100), self.cfg, self.led)
        rec = P.close_position(self.led, self.cfg, pos, pos["stop"], "stop", self.now)
        self.assertAlmostEqual(self.cash("CRYPTO") - start, rec["pnl"], places=3)
        self.assertLess(rec["pnl"], 0)
        # the size includes the fees, so the loss at the stop stays within max_loss_per_trade
        self.assertLessEqual(-rec["pnl"], self.cfg["accounts"]["CRYPTO"]["max_loss_per_trade"] + 1e-6)
        self.assertAlmostEqual(rec["r"], rec["pnl"] / (pos["qty"] * 2), places=2)

    def test_short_profit_at_target(self):
        start = self.cash("CRYPTO")
        pos = P.cmd_buy(order("CRYPTO:ETH", 102, 96, 100, side="short"), self.cfg, self.led)
        self.assertEqual(pos["side"], "short")
        rec = P.close_position(self.led, self.cfg, pos, pos["target"], "target", self.now)
        fees = rec["entry_fee"] + rec["exit_fee"]
        self.assertAlmostEqual(rec["pnl"], 4 * pos["qty"] - fees, places=3)  # a short gains when the price falls
        self.assertAlmostEqual(self.cash("CRYPTO") - start, rec["pnl"], places=3)

    def test_futures_book_margin_not_full_value(self):
        self.cfg["accounts"]["INDIA"].update(capital=1000000, max_loss_per_trade_fno=10000)  # one lot needs Rs 195,000
        self.led = P.load_ledger(self.cfg)
        start = self.cash("INDIA")
        pos = P.cmd_buy(order("NFO:NIFTY-FUT-20991231", 24990, 25030, 25000, force=True), self.cfg, self.led)
        self.assertEqual(pos["kind"], "futures")
        self.assertEqual(pos["qty"] % 65, 0)  # whole Nifty lots
        self.assertAlmostEqual(pos["margin"], round(pos["qty"] * 25000 * 0.12, 2), places=2)
        self.assertAlmostEqual(start - self.cash("INDIA"), pos["margin"] + pos["entry_fee"], places=3)
        rec = P.close_position(self.led, self.cfg, pos, 25100, "manual", self.now)
        self.assertAlmostEqual(self.cash("INDIA") - start, rec["pnl"], places=3)

    def test_india_equity_charges(self):
        # Rs 10,000 intraday: brokerage min(20, 0.03%) = 3, exchange 0.297, SEBI 0.01, GST 18% of those;
        # stamp 0.003% on the buy, STT 0.025% on the sell
        gst = (3 + 0.297 + 0.01) * 0.18
        self.assertAlmostEqual(P.charges(self.cfg, "NSE", "RELIANCE", "buy", 10000), 3 + 0.297 + 0.01 + 0.3 + gst, places=6)
        self.assertAlmostEqual(P.charges(self.cfg, "NSE", "RELIANCE", "sell", 10000), 3 + 0.297 + 0.01 + 2.5 + gst, places=6)

    def test_stop_fills_at_stop_when_watched_and_at_price_after_a_gap(self):
        pos = P.cmd_buy(order("CRYPTO:SOL", 98, 104, 100), self.cfg, self.led)
        real = P.fetch_price
        try:
            P.fetch_price = lambda m, t: (97.0, datetime.now(timezone.utc))
            P.check_once(self.cfg, self.led)  # watched a moment ago: a resting stop fills at the stop
            self.assertEqual(self.led["closed"][-1]["exit"], 98)
            pos = P.cmd_buy(order("CRYPTO:ADA", 98, 104, 100), self.cfg, self.led)
            pos["last_seen"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            P.check_once(self.cfg, self.led)  # nobody watched for an hour: fills at the worse price
            self.assertEqual(self.led["closed"][-1]["exit"], 97)
        finally:
            P.fetch_price = real

    def test_rejects_a_stop_on_the_wrong_side(self):
        with self.assertRaises(P.PaperError):
            P.cmd_buy(order("CRYPTO:BTC", 101, 104, 100), self.cfg, self.led)
        with self.assertRaises(P.PaperError):
            P.cmd_buy(order("CRYPTO:BTC", 99, 96, 100, side="short"), self.cfg, self.led)

    def test_ist_day_files_late_utc_trades_on_the_india_date(self):
        self.assertEqual(P.ist_day({"exit_time": "2026-11-18T20:40:00+00:00", "exit_date": "2026-11-18"}), "2026-11-19")
        self.assertEqual(P.ist_day({"exit_date": "2026-11-18"}), "2026-11-18")


if __name__ == "__main__":
    unittest.main()
