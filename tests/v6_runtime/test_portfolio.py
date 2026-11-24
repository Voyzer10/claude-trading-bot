"""V6 portfolio around the unchanged Module E: booking = Module E figures, book gates, shadow trades, MTM, daily
loss, recovery without double booking, signals metadata. SYNTHETIC fixture data only."""
import json
from decimal import Decimal

import pytest

import _fx
from _fx import T
from scanner_v6.exit import execution as E
from v6_runtime.ledger import BookLedger, LedgerCorrupt
from v6_runtime.paths import DataRoot
from v6_runtime.portfolio import (BOOK_DAILY_LOSS, BOOK_POSITION_LIMIT, BOOK_RISK_EXCEEDED, Portfolio,
                                  PortfolioError)


def _run(tmp, rows=_fx.TWO_CLOSED_ROWS, equity="1000"):
    root, led = _fx.book(tmp)
    pf = Portfolio(root, led, [_fx.spec("AAA", equity=equity)])
    _fx.feed(pf, {"AAA": _fx.candles(rows, "AAA")})
    return root, led, pf


def test_booked_trades_equal_module_e_and_reconcile(tmp_path):
    root, led, pf = _run(tmp_path)
    recs = {r.setup_id: r for r in pf.streams["AAA"].records}
    closed = led.state["closed_trades"]
    assert [t["status"] for t in closed] == [E.STOPPED_OUT, E.TARGET_HIT]
    for t in closed:
        r = recs[t["setup_id"]]
        assert (t["entry_fill"], t["exit_fill"], t["quantity"], t["entry_fee"], t["exit_fee"], t["realized_pnl"]) == \
            tuple(str(x) for x in (r.entry_fill, r.exit_fill, r.quantity, r.entry_fee, r.exit_fee, r.realized_pnl))
    realized = sum(Decimal(t["realized_pnl"]) for t in closed)
    fees = sum(Decimal(t["entry_fee"]) + Decimal(t["exit_fee"]) for t in closed)
    s = BookLedger.load(root, "US").summary()
    assert Decimal(s["cash"]) == Decimal("1000") + realized and Decimal(s["fees_total"]) == fees
    assert Decimal(s["equity"]) == Decimal(s["cash"]) and s["open_positions"] == 0


def test_fees_and_slippage_reconciliation(tmp_path):
    root, led, pf = _run(tmp_path)
    tot = Decimal(0)
    for t in led.state["closed_trades"]:
        q, M = Decimal(t["quantity"]), Decimal(t["contract_multiplier"])
        es = abs(Decimal(t["entry_fill"]) - Decimal(t["entry_open"])) * q * M
        xs = abs(Decimal(t["exit_fill"]) - Decimal(t["exit_reference"])) * q * M
        assert Decimal(t["entry_slippage"]) == es and Decimal(t["exit_slippage"]) == xs
        side = 1 if t["side"] == "BUY" else -1
        gross = side * (Decimal(t["exit_fill"]) - Decimal(t["entry_fill"])) * q * M
        assert Decimal(t["gross_pnl"]) == gross
        assert Decimal(t["realized_pnl"]) == gross - Decimal(t["entry_fee"]) - Decimal(t["exit_fee"])
        tot += es + xs
    assert Decimal(led.state["slippage_total"]) == tot and tot > 0


def test_risk_gate_rejects_oversized_entry_as_shadow(tmp_path):
    root, led, pf = _run(tmp_path, equity="100000")        # E sizes for 100k, the book holds 1000
    assert led.state["closed_trades"] == [] and led.open_trade is None
    assert [r["code"] for r in led.state["rejections"]] == [BOOK_RISK_EXCEEDED, BOOK_RISK_EXCEEDED]
    assert led.cash() == Decimal("1000")
    sig = root.read_jsonl("signals", "US.jsonl")
    exits = [s for s in sig if s["stage"] in (E.STOPPED_OUT, E.TARGET_HIT)]
    assert exits and all(s["shadow"] and s["book_decision"] == "SHADOW" for s in exits)


def test_one_position_per_book_across_instruments(tmp_path):
    root, led = _fx.book(tmp_path)
    pf = Portfolio(root, led, [_fx.spec("BBB"), _fx.spec("AAA")])
    _fx.feed(pf, {"AAA": _fx.candles(_fx.OPEN_ROWS, "AAA"), "BBB": _fx.candles(_fx.OPEN_ROWS, "BBB")})
    assert led.open_trade["instrument"] == "AAA"                       # instrument-id order at the same timestamp
    assert [(r["instrument"], r["code"]) for r in led.state["rejections"]] == [("BBB", BOOK_POSITION_LIMIT)]


def test_open_position_mtm_and_committed(tmp_path):
    root, led, pf = _run(tmp_path, rows=_fx.OPEN_ROWS)
    assert led.open_trade is not None and pf.mtm["status"] == "OK"
    s = pf.summary()
    assert s["mtm_status"] == "OK" and s["equity"] is not None
    exp = led.cash() + Decimal(pf.mtm["unrealized"]) - Decimal(pf.mtm["est_exit_fee"])
    assert Decimal(s["equity"]) == exp
    assert led.summary(None)["equity"] is None                         # no mark -> no equity figure


def test_daily_loss_latch_blocks_new_entries(tmp_path):
    root, led = _fx.book(tmp_path)
    day = T.T0.date().isoformat()
    led.latch_day(day, "test latch")
    pf = Portfolio(root, led, [_fx.spec("AAA")])
    _fx.feed(pf, {"AAA": _fx.candles(_fx.TWO_CLOSED_ROWS, "AAA")})
    assert {r["code"] for r in led.state["rejections"]} == {BOOK_DAILY_LOSS} and led.state["closed_trades"] == []


def test_recovery_replays_without_double_booking(tmp_path):
    root, led, pf = _run(tmp_path, rows=_fx.OPEN_ROWS)
    seq, ot = led.state["seq"], led.open_trade["setup_id"]
    n_sig = len(root.read_jsonl("signals", "US.jsonl"))
    led2 = BookLedger.load(root, "US")
    pf2 = Portfolio(root, led2, [_fx.spec("AAA")])
    n = pf2.recover()
    assert n == len(_fx.OPEN_ROWS) and led2.state["seq"] == seq and led2.open_trade["setup_id"] == ot
    assert len(root.read_jsonl("signals", "US.jsonl")) == n_sig        # signals deduplicated
    # continuing after recovery closes the SAME trade exactly once
    rest = _fx.candles(_fx.TWO_CLOSED_ROWS, "AAA")[len(_fx.OPEN_ROWS):]
    for c in rest:
        pf2.on_candle("AAA", c)
    ids = [t["setup_id"] for t in led2.state["closed_trades"]]
    assert ids.count(ot) == 1 and len(ids) == len(set(ids)) == 2


def test_recovery_detects_ledger_mismatch(tmp_path):
    root, led, pf = _run(tmp_path, rows=_fx.OPEN_ROWS)
    p = root.path("books", "US.json")
    d = json.load(open(p))
    d["open_trade"]["quantity"] = "999"
    json.dump(d, open(p, "w"))
    pf2 = Portfolio(root, BookLedger.load(root, "US"), [_fx.spec("AAA")])
    with pytest.raises(LedgerCorrupt):
        pf2.recover()


def test_invalid_candle_is_not_journaled(tmp_path):
    root, led = _fx.book(tmp_path)
    pf = Portfolio(root, led, [_fx.spec("AAA")])
    cs = _fx.candles(_fx.OPEN_ROWS, "AAA")
    pf.on_candle("AAA", cs[0])
    with pytest.raises(Exception):
        pf.on_candle("AAA", cs[0])                                     # duplicate / out of order
    assert len(root.read_jsonl("journal", "US.jsonl")) == 1


def test_wrong_book_and_unknown_instrument(tmp_path):
    root, led = _fx.book(tmp_path)
    with pytest.raises(PortfolioError):
        Portfolio(root, led, [_fx.spec("AAA", book="CRYPTO")])
    pf = Portfolio(root, led, [_fx.spec("AAA")])
    with pytest.raises(PortfolioError):
        pf.on_candle("ZZZ", _fx.candles(_fx.OPEN_ROWS, "ZZZ")[0])


def test_signal_metadata_complete(tmp_path):
    root, led, pf = _run(tmp_path)
    need = {"book_id", "instrument", "market", "timeframe", "setup_id", "stage", "ts_utc", "ts_local", "direction",
            "entry_reference", "stop_loss", "target", "result", "rejection_reason", "data_quality", "book_decision",
            "shadow", "scanner_name", "scanner_version", "execution_mode"}
    sig = root.read_jsonl("signals", "US.jsonl")
    assert sig and all(need <= set(s) for s in sig)
    assert {s["scanner_name"] for s in sig} == {"V6 SMC Scanner"} and {s["market"] for s in sig} == {"US_EQUITY"}


def test_data_interruption_is_journaled_and_replayed(tmp_path):
    root, led = _fx.book(tmp_path)
    pf = Portfolio(root, led, [_fx.spec("AAA")])
    cs = _fx.candles(_fx.OPEN_ROWS, "AAA")
    for c in cs[:10]:
        pf.on_candle("AAA", c)
    from datetime import timedelta
    pf.on_data_interrupted("AAA", cs[9].ts + timedelta(minutes=5))
    pf.on_data_resumed("AAA", cs[10].ts)
    for c in cs[10:]:
        pf.on_candle("AAA", c)
    kinds = [e["kind"] for e in root.read_jsonl("journal", "US.jsonl")]
    assert "DATA_INTERRUPTED" in kinds and "DATA_RESUMED" in kinds
    pf2 = Portfolio(root, BookLedger.load(root, "US"), [_fx.spec("AAA")])
    assert pf2.recover() == len(kinds)
