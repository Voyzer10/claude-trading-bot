"""IEX real-time feed policy (owner 2026-11-24, provisional): IEX only, no delayed-SIP fallback, in-session missing
bars interrupt the stream (never filled in), fetch failures fail closed, and the feed source is recorded everywhere.
SYNTHETIC bars and an injected data source only; no network."""
import copy
import json
import os
from datetime import date, datetime, timedelta, timezone

# pyrefly: ignore[missing-import]
import pytest

import _fx
from v6_runtime import runner, us_stocks
from v6_runtime.data.alpaca import AlpacaDataError, Bar
from v6_runtime.data.feed import ACCEPT, BarFeed
from v6_runtime.ledger import BookLedger
from v6_runtime.paths import DataRoot

UTC = timezone.utc
OPEN = datetime(2026, 11, 23, 14, 30, tzinfo=UTC)        # Mon 23 Nov 2026 09:30 New York
TF = timedelta(minutes=5)


def _sess(d0=date(2026, 11, 23), d1=date(2026, 11, 24)):
    return us_stocks.session_calendar(us_stocks.load_calendar(), d0, d1)


def bar(t, px=100.0):
    return Bar("SPY", t, px, px + 0.2, px - 0.2, px + 0.1, 500.0)


def feed():
    return BarFeed("SPY", TF, _sess(), 10, 3, "session_grid")


def late(t):
    return t + TF + timedelta(minutes=1)


def test_in_session_missing_bars_interrupt_and_are_never_filled():
    f = feed()
    assert f.offer(bar(OPEN), late(OPEN)).status == ACCEPT
    assert f.offer(bar(OPEN + TF), late(OPEN + TF)).events == []
    t = OPEN + 4 * TF                                     # bars at +2 and +3 never arrived
    r = f.offer(bar(t), late(t))
    assert r.status == ACCEPT
    assert r.events == [("DATA_INTERRUPTED", OPEN + 2 * TF), ("DATA_RESUMED", t)]
    assert r.candle.index == 2                            # third ACCEPTED candle: nothing was invented
    h = f.health()
    assert (h["gaps"], h["missing_bars"], h["max_consecutive_missing"]) == (1, 2, 2)
    assert h["last_gap"] == {"after": (OPEN + TF).isoformat(), "resumed": t.isoformat(), "missing": 2}
    r = f.offer(bar(t + 2 * TF), late(t + 2 * TF))        # one more single hole
    assert [e[0] for e in r.events] == ["DATA_INTERRUPTED", "DATA_RESUMED"]
    assert (f.health()["gaps"], f.health()["missing_bars"], f.health()["max_consecutive_missing"]) == (2, 3, 2)


def test_overnight_is_not_a_gap_but_a_missing_open_bar_is():
    f = feed()
    close_bar = datetime(2026, 11, 23, 20, 55, tzinfo=UTC)               # last bar of Monday
    f.offer(bar(close_bar), late(close_bar))
    nxt = datetime(2026, 11, 24, 14, 30, tzinfo=UTC)                      # Tuesday open bar
    assert f.offer(bar(nxt), late(nxt)).events == []
    g = feed()
    g.offer(bar(close_bar), late(close_bar))
    r = g.offer(bar(nxt + TF), late(nxt + TF))                            # Tuesday's first bar missing
    assert [e[0] for e in r.events] == ["DATA_INTERRUPTED", "DATA_RESUMED"] and g.health()["missing_bars"] == 1


def test_stale_feed_interrupts_and_resumes_once():
    f = feed()
    f.offer(bar(OPEN), late(OPEN))
    ev = f.check_stale(OPEN + 6 * TF)
    assert ev == ("DATA_INTERRUPTED", OPEN + 6 * TF)
    t = OPEN + 7 * TF
    r = f.offer(bar(t), late(t))
    assert r.events == [("DATA_RESUMED", t)]                              # no second interruption for the same hole
    assert f.health()["missing_bars"] == 6


# ------------------------------------------------------------------ config: IEX selected, SIP never a fallback
def _approved(feed_name="iex"):
    raw = json.load(open(os.path.join(os.path.dirname(us_stocks.__file__), "config", "us_stocks.template.json")))
    vals = dict(tick_size=0.01, entry_ticks=1, stop_exit_ticks=1, target_exit_ticks=0, max_gap_ticks=50,
                sl_buffer_ticks=2, tp_offset_ticks=1, contract_multiplier="1", lot_size="0.01", quantity_step="0.01",
                min_quantity="0.01", fee_schedule={"model": "us_equity_sell_side_v1", "commission_per_order": "0",
                                                   "commission_source": "TEST ONLY"},
                price_rounding_mode="ROUND_HALF_UP", initial_margin_rate="1", mtm_exit_slippage_ticks=2,
                exchange_day_rule="exchange session date", bar_settle_seconds=10, stale_after_bars=3,
                alignment_rule="session_grid", eod_flatten_buffer_minutes=5, entry_cutoff_minutes=15)
    for k, v in vals.items():
        raw["values"][k] = {"value": v, "approval": "APPROVED", "decision": "TEST FIXTURE ONLY"}
    raw["instruments"] = ["SPY"]
    raw["data_provider"] = {"name": "alpaca", "feed": feed_name, "approval": "APPROVED", "decision": "test"}
    return raw


def test_feed_policy_in_readiness():
    cal = dict(us_stocks.load_calendar(), verified=True)
    ok = us_stocks.readiness(us_stocks.parse_config(_approved("iex")), cal, True, today=date(2026, 11, 24))
    assert ok["ready"] is True, ok["blockers"]
    sip = us_stocks.readiness(us_stocks.parse_config(_approved("sip")), cal, True, today=date(2026, 11, 24))
    assert sip["ready"] is False and any("delayed SIP is never used" in b for b in sip["blockers"])
    raw = _approved("iex")
    raw["data_provider"]["approval"] = "NOT_APPROVED"
    assert any("feed: NOT APPROVED" in b for b in us_stocks.readiness(us_stocks.parse_config(raw), cal, True)["blockers"])
    tmpl = us_stocks.parse_config(json.load(open(os.path.join(os.path.dirname(us_stocks.__file__), "config",
                                                              "us_stocks.template.json"))))
    assert tmpl.feed == "iex" and not any("feed" in b for b in us_stocks.readiness(tmpl, cal, True)["blockers"])


def test_specs_record_the_iex_source_and_never_claim_consolidated():
    cfg = us_stocks.parse_config(_approved("iex"))
    sp = us_stocks.instrument_specs(cfg, us_stocks.load_calendar(), date(2026, 11, 23), date(2026, 11, 24))[0]
    assert "iex" in sp.data_source and "not consolidated" in sp.data_source
    assert sp.execution.missing(sp.market) == ()                          # EXCHANGE calendar: no trading_day_start


# ------------------------------------------------------------------ runner: fail closed, no fallback, source recorded
def _runner(tmp, source):
    root = DataRoot(str(tmp))
    BookLedger.create(root, "US", owner_authorised=True, created_by="test")
    cfg = us_stocks.parse_config(_approved("iex"))
    return root, runner.USRunner(root, cfg, us_stocks.load_calendar(), source, date(2026, 11, 23), date(2026, 11, 24))


def test_fetch_failure_fails_closed_without_fallback(tmp_path):
    calls = []

    def source(sym, tf, since, now):
        calls.append(sym)
        if len(calls) > 1:
            raise AlpacaDataError("HTTP 403 subscription does not permit querying recent SIP data")
        return [bar(OPEN), bar(OPEN + TF)]
    root, r = _runner(tmp_path, source)
    assert r.poll_once(late(OPEN + TF))["accepted"] == 2
    out = r.poll_once(late(OPEN + 2 * TF))
    assert out["fetch_errors"] == 1 and out["accepted"] == 0 and calls == ["SPY", "SPY"]   # no second feed tried
    h = root.read_json("runtime", "heartbeat.json")
    assert h["feeds"]["SPY"]["fetch_errors"] == 1 and "403" in h["feeds"]["SPY"]["last_fetch_error"]
    assert "not consolidated" in h["data_source"]
    r.poll_once(OPEN + 7 * TF)                                            # still failing -> stale -> interrupted
    assert root.read_json("runtime", "heartbeat.json")["feeds"]["SPY"]["state"] == "INTERRUPTED"
    kinds = [e["kind"] for e in root.read_jsonl("journal", "US.jsonl")]
    assert kinds == ["candle", "candle", "DATA_INTERRUPTED"]


def test_runner_has_no_feed_fallback_path():
    src = open(runner.__file__).read() + open(os.path.join(os.path.dirname(runner.__file__), "data", "feed.py")).read()
    assert '"sip"' not in src and "'sip'" not in src


def test_signals_carry_the_data_source(tmp_path):
    root, led = _fx.book(tmp_path)
    sp = _fx.spec("AAA")
    sp = type(sp)(sp.instrument_id, sp.book_id, sp.timeframe, sp.market, sp.execution, data_source="SYNTHETIC src")
    pf = _fx.Portfolio(root, led, [sp])
    _fx.feed(pf, {"AAA": _fx.candles(_fx.TWO_CLOSED_ROWS, "AAA")})
    sig = root.read_jsonl("signals", "US.jsonl")
    assert sig and {s["data_source"] for s in sig} == {"SYNTHETIC src"}
    assert {t["data_source"] for t in led.state["closed_trades"]} == {"SYNTHETIC src"}


# ------------------------------------------------------------------ allowlist and thresholds
def test_symbol_allowlist_is_spy_qqq_aapl_msft():
    assert us_stocks.SYMBOL_ALLOWLIST == ("SPY", "QQQ", "AAPL", "MSFT")
    raw = _approved("iex")
    raw["instruments"] = ["SPY", "QQQ", "AAPL", "MSFT"]
    assert us_stocks.parse_config(raw).instruments == ("SPY", "QQQ", "AAPL", "MSFT")
    for bad in (["TSLA"], ["SPY", "NVDA"], ["SPY", "SPY"]):
        raw["instruments"] = bad
        with pytest.raises(us_stocks.USConfigError):
            us_stocks.parse_config(raw)


def test_thresholds_are_config_values_never_assumed_approved():
    tmpl = us_stocks.parse_config(json.load(open(os.path.join(os.path.dirname(us_stocks.__file__), "config",
                                                              "us_stocks.template.json"))))
    assert "bar_settle_seconds" not in tmpl.approved and "stale_after_bars" not in tmpl.approved
    blockers = us_stocks.readiness(tmpl, dict(us_stocks.load_calendar(), verified=True), True)["blockers"]
    assert "bar_settle_seconds: NOT APPROVED" in blockers and "stale_after_bars: NOT APPROVED" in blockers
    raw = _approved("iex")
    raw["values"]["stale_after_bars"]["approval"] = "PROPOSED"                 # anything but APPROVED is not approved
    assert "stale_after_bars" in us_stocks.parse_config(raw).not_approved
    for settle, stale in ((None, 2), (30, None), (-1, 2), (30, 0), (30.5, 2), (True, 2)):
        with pytest.raises(ValueError):
            BarFeed("SPY", TF, _sess(), settle, stale, "session_grid")


def test_invalid_and_incomplete_bars_are_never_accepted():
    f = feed()
    from v6_runtime.data.feed import INVALID, NOT_COMPLETE
    assert f.offer(bar(OPEN), OPEN + TF).status == NOT_COMPLETE              # before end + settle
    bad = Bar("SPY", OPEN, 100.0, 99.0, 98.0, 100.5, 10.0)                   # high below open/close
    assert f.offer(bad, late(OPEN)).status == INVALID and f.last is None
    assert f.offer(bar(OPEN), late(OPEN)).status == ACCEPT


# ------------------------------------------------------------------ runner restart, stale ordering, and gates
def test_runner_restart_preserves_gate_index_and_data_state(tmp_path):
    root = DataRoot(str(tmp_path))
    BookLedger.create(root, "US", owner_authorised=True, created_by="test")
    cfg = us_stocks.parse_config(_approved("iex"))
    cal = us_stocks.load_calendar()
    batches = [
        [bar(OPEN), bar(OPEN + TF)],
        [],
        [bar(OPEN + 8 * TF)],
    ]

    def source(sym, tf, since, now):
        return batches.pop(0)

    r1 = runner.USRunner(root, cfg, cal, source, date(2026, 11, 23), date(2026, 11, 24))
    assert r1.poll_once(late(OPEN + TF))["accepted"] == 2
    assert r1.poll_once(OPEN + 7 * TF)["events"] == 1                    # check_stale -> DATA_INTERRUPTED

    # Restart over the same DataRoot while DATA_INTERRUPTED: must resume cleanly without index=0 collision
    r2 = runner.USRunner(root, cfg, cal, source, date(2026, 11, 23), date(2026, 11, 24))
    assert r2.feeds["SPY"].interrupted is True
    assert len(r2.feeds["SPY"].gate.completed) == 2
    out = r2.poll_once(late(OPEN + 8 * TF))
    assert out["accepted"] == 1 and out["events"] == 1                   # DATA_RESUMED + candle index 2
    candles = r2.portfolio.streams["SPY"].candles
    assert [c.index for c in candles] == [0, 1, 2]


def test_runner_delayed_poll_accepts_fresh_bars_before_check_stale(tmp_path):
    """When a poll arrives past stale_after but returns fresh bars, offer() must run before check_stale() so the
    fresh bar is not rejected as LATE against a check_stale timestamp."""
    root = DataRoot(str(tmp_path))
    BookLedger.create(root, "US", owner_authorised=True, created_by="test")
    cfg = us_stocks.parse_config(_approved("iex"))
    cal = us_stocks.load_calendar()
    batches = [[bar(OPEN)], [bar(OPEN + 5 * TF)]]

    def source(sym, tf, since, now):
        return batches.pop(0)

    r = runner.USRunner(root, cfg, cal, source, date(2026, 11, 23), date(2026, 11, 24))
    assert r.poll_once(late(OPEN))["accepted"] == 1
    out = r.poll_once(late(OPEN + 5 * TF))
    assert out["accepted"] == 1 and out["events"] == 2                   # DATA_INTERRUPTED + DATA_RESUMED for real gap
    assert r.feeds["SPY"].health()["counts"].get("LATE", 0) == 0


def test_runner_multi_instrument_orders_bars_by_timestamp_then_symbol(tmp_path):
    root = DataRoot(str(tmp_path))
    BookLedger.create(root, "US", owner_authorised=True, created_by="test")
    raw = _approved("iex")
    raw["instruments"] = ["SPY", "AAPL"]
    cfg = us_stocks.parse_config(raw)
    cal = us_stocks.load_calendar()

    def source(sym, tf, since, now):
        return [Bar(sym, OPEN, 100.0, 100.2, 99.9, 100.1, 100.0),
                Bar(sym, OPEN + TF, 100.1, 100.3, 100.0, 100.2, 100.0)]

    seen = []
    r = runner.USRunner(root, cfg, cal, source, date(2026, 11, 23), date(2026, 11, 24))
    orig = r.portfolio.on_candle

    def spy_on_candle(iid, c):
        seen.append((c.ts, iid))
        return orig(iid, c)

    r.portfolio.on_candle = spy_on_candle
    assert r.poll_once(late(OPEN + TF))["accepted"] == 4
    assert seen == [(OPEN, "AAPL"), (OPEN, "SPY"), (OPEN + TF, "AAPL"), (OPEN + TF, "SPY")]


def test_gates_and_readiness_catch_corrupt_ledger_invalid_config_and_feed_bounds(tmp_path):
    root = DataRoot(str(tmp_path))
    BookLedger.create(root, "US", owner_authorised=True, created_by="test")
    os.makedirs(root.path("runtime"), exist_ok=True)
    open(root.path("runtime", "ENABLED_US"), "w").close()
    os.makedirs(root.path("config"), exist_ok=True)
    open(root.path("config", "us_stocks.json"), "w").write("{bad json")
    assert any("invalid" in b for b in runner.gates(root, "US"))

    raw = _approved("iex")
    raw["values"]["stale_after_bars"]["value"] = 0
    r = us_stocks.readiness(us_stocks.parse_config(raw), us_stocks.load_calendar(), True, today=date(2026, 11, 24))
    assert r["ready"] is False and any("stale_after_bars" in b for b in r["blockers"])

    p = root.path("books", "US.json")
    d = json.load(open(p))
    d["cash"] = "9999"
    json.dump(d, open(p, "w"))
    open(root.path("config", "us_stocks.json"), "w").write(json.dumps(_approved("iex")))
    assert any("ledger error" in b for b in runner.gates(root, "US"))
