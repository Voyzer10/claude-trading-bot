"""US Stocks intraday decisions (owner, 24 Nov 2026): verified NYSE calendar over the full 2026-2027 range, mandatory
end-of-day flattening (ME-6), long AND short paper trades with side-specific parameters (ME-7), the 0.01 fractional
grid, and the sell-side SEC Section 31 + FINRA TAF fee model (ME-5). SYNTHETIC price paths only (the independent Module
E test path); nothing here is market performance."""
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_UP, Decimal

import pytest

import _fx
from _fx import T
from scanner_v6.data.candle_models import Candle
from scanner_v6.data.market_config import ConfigError, MarketDataConfig
from scanner_v6.exit import execution as E
from v6_runtime import fees_us, us_stocks
from v6_runtime.backtest import config as bcfg
from v6_runtime.backtest.engine import BacktestRun
from v6_runtime.ledger import BookLedger
from v6_runtime.paths import DataRoot
from v6_runtime.portfolio import BOOK_SHORT_NOT_READY, InstrumentSpec, Portfolio

UTC = timezone.utc
D = Decimal
CAL = us_stocks.load_calendar()

# Independent copy of the official NYSE Group list (ICE press release, 2026-2028 calendar), typed from the source.
OFFICIAL_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
    "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}
OFFICIAL_EARLY = {"2026-11-27", "2026-12-24", "2027-11-26"}


# ------------------------------------------------------------------ A. calendar
def test_calendar_matches_official_list_and_is_verified():
    assert set(CAL["holidays"]) == OFFICIAL_HOLIDAYS and set(CAL["early_closes"]) == OFFICIAL_EARLY
    assert CAL["verified"] is True and CAL["covered_years"] == [2026, 2027]
    assert us_stocks.calendar_range(CAL) == (date(2026, 1, 1), date(2027, 12, 31))


def _sessions(d0, d1):
    return {o.astimezone(us_stocks.ZoneInfo("America/New_York")).date(): (o, c)
            for o, c in us_stocks.trading_sessions(CAL, d0, d1)}


def test_sessions_holidays_early_closes_and_dst():
    s = _sessions(date(2026, 1, 1), date(2027, 12, 31))
    weekdays = sum(1 for n in range(730) if (date(2026, 1, 1) + timedelta(days=n)).weekday() < 5)
    assert len(s) == weekdays - len(OFFICIAL_HOLIDAYS)                       # 2026-2027: every weekday but holidays
    for h in OFFICIAL_HOLIDAYS:
        assert date.fromisoformat(h) not in s
    for e in OFFICIAL_EARLY:
        o, c = s[date.fromisoformat(e)]
        assert c.astimezone(us_stocks.ZoneInfo("America/New_York")).strftime("%H:%M") == "13:00"
    assert s[date(2026, 11, 27)][1] == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)          # EST: 13:00 = 18:00Z
    # DST: 2026-03-08 (spring forward) and 2026-11-01 (fall back)
    assert s[date(2026, 3, 6)] == (datetime(2026, 3, 6, 14, 30, tzinfo=UTC), datetime(2026, 3, 6, 21, 0, tzinfo=UTC))
    assert s[date(2026, 3, 9)] == (datetime(2026, 3, 9, 13, 30, tzinfo=UTC), datetime(2026, 3, 9, 20, 0, tzinfo=UTC))
    assert s[date(2026, 10, 30)][1] == datetime(2026, 10, 30, 20, 0, tzinfo=UTC)
    assert s[date(2026, 11, 2)][1] == datetime(2026, 11, 2, 21, 0, tzinfo=UTC)
    with pytest.raises(us_stocks.USConfigError):                              # never guessed outside the range
        us_stocks.trading_sessions(CAL, date(2028, 1, 3), date(2028, 1, 3))


def test_runner_specs_cover_the_full_range_not_a_rolling_week():
    from test_iex_feed import _approved                                        # noqa: E402 (shared approved fixture)
    cfg = us_stocks.parse_config(_approved("iex"))
    sp = us_stocks.instrument_specs(cfg, CAL)[0]
    sess = sp.market.session.sessions
    assert sess[0][0] == datetime(2026, 1, 2, 14, 30, tzinfo=UTC) and sess[-1][1].date() == date(2027, 12, 31)
    later = datetime(2027, 6, 30, 15, 0, tzinfo=UTC)                          # far beyond the old +-7 days
    assert sp.market.session.session_index(later) is not None
    assert sp.execution.eod_flatten_buffer == timedelta(minutes=5) and sp.execution.entry_cutoff_buffer == timedelta(minutes=15)


def test_readiness_blocks_outside_coverage_and_stale_fee_table():
    from test_iex_feed import _approved                                        # noqa: E402
    cfg = us_stocks.parse_config(_approved("iex"))
    assert us_stocks.readiness(cfg, CAL, True, today=date(2026, 11, 24))["ready"] is True
    r = us_stocks.readiness(cfg, CAL, True, today=date(2028, 1, 3))
    assert any("not covered" in b for b in r["blockers"]) and any("re-verify" in b for b in r["blockers"])


# ------------------------------------------------------------------ B. EOD flattening (Module E, ME-6)
def tts(k):
    return T.T0 + timedelta(minutes=5 * k)


def mkt(ins, sessions):
    return T.market(ins, session={"kind": "exchange_sessions", "timezone": "UTC",
                                  "sessions": [[a.timestamp(), b.timestamp()] for a, b in sessions]})


def eod_cfg(**kw):
    base = dict(mtm_exit_slippage_ticks=2, eod_flatten_buffer=5, entry_cutoff_buffer=15)
    base.update(kw)
    return T.cfg(**base)


def run_rows(after, side="BUY", sessions=((0, 56),), conf=None):
    ins = "EOD-%s" % side
    rows = T.BASE + T.CONFIRM + list(after)
    if side == "SELL":
        rows = T.mirror(rows)
    return E.analyze_execution(T.series(rows, ins), ins, T.TF, mkt(ins, [(tts(a), tts(b)) for a, b in sessions]),
                               conf or eod_cfg())


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_open_position_is_flattened_before_the_session_close(side):
    rep = run_rows([T.N, T.Q, T.Q, T.Q], side)                                # 51 entry .. 54; close at t(56)
    r = T.only(rep)
    assert r.status == E.EOD_FLATTEN and r.exit_index == 54                    # candle 54 ends at t(55) = close - 5 min
    close54 = D(repr(T.Q[3] if side == "BUY" else 200 - T.Q[3]))
    exp = close54 - D("0.01") if side == "BUY" else close54 + D("0.01")      # adverse stop_exit_ticks (1)
    assert r.exit_fill == exp and r.exit_gap is False
    gross = (r.exit_fill - r.entry_fill if side == "BUY" else r.entry_fill - r.exit_fill) * r.quantity
    assert r.gross_pnl == gross and r.realized_pnl == gross - r.entry_fee - r.exit_fee
    assert rep.end_of_data.open_unresolved == ()                               # nothing carried


def test_sl_tp_take_precedence_on_the_flatten_candle():
    rep = run_rows([T.N, T.Q, T.Q, (116.55, 116.60, 115.00, 115.10)])          # candle 54 trades through the SL
    assert T.only(rep).status == E.STOPPED_OUT and T.only(rep).exit_index == 54


def test_entry_cutoff_blocks_late_entries():
    rep = run_rows([T.N, T.Q, T.Q, T.Q], conf=eod_cfg(entry_cutoff_buffer=30))  # cutoff t(50): entry t(51) too late
    r = T.only(rep)
    assert (r.status, r.disposition_reason, r.entry_fill) == (E.EXPIRED, E.AFTER_ENTRY_CUTOFF, None)


def test_flatten_uses_the_actual_early_close():
    """The flatten time follows the configured session close, not a fixed 16:00: an early close at t(54) flattens on
    candle 52 (ends t(53) = t(54) - 5 min)."""
    rep = run_rows([T.N, T.Q, T.Q, T.Q][:3], sessions=((0, 54),), conf=eod_cfg(entry_cutoff_buffer=10))
    assert T.only(rep).status == E.EOD_FLATTEN and T.only(rep).exit_index == 52


def test_nyse_flatten_time_across_dst_and_early_close():
    ins = "SPY"
    sess = us_stocks.session_calendar(CAL, date(2026, 3, 6), date(2026, 11, 27))
    st = E.ExecutionStream(ins, "5m", MarketDataConfig.from_fixture({"instrument_id": ins, "timeframe_seconds": 300,
                                                                     "tick_size": 0.01}).__class__(
        origin=T.market(ins).origin, instrument_id=ins, timeframe=timedelta(minutes=5), tick_size=0.01, session=sess),
        eod_cfg())
    assert st._session_close(datetime(2026, 3, 6, 20, 0, tzinfo=UTC)) == datetime(2026, 3, 6, 21, 0, tzinfo=UTC)
    assert st._session_close(datetime(2026, 3, 9, 19, 0, tzinfo=UTC)) == datetime(2026, 3, 9, 20, 0, tzinfo=UTC)
    assert st._session_close(datetime(2026, 11, 27, 17, 0, tzinfo=UTC)) == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    assert st._session_close(datetime(2026, 11, 26, 17, 0, tzinfo=UTC)) is None             # Thanksgiving: closed


def test_missing_data_at_the_close_flattens_at_the_next_open_and_says_so():
    """Data stops after candle 52; the session closes at t(56) without a candle reaching the flatten time. The next
    candle (next session, t(100)) closes the position at its OPEN, EOD_FLATTEN / EOD_DATA_MISSING: no price invented."""
    ins = "GAP"
    rows = T.BASE + T.CONFIRM + [T.N, T.Q]
    cs = list(T.series(rows, ins))
    st = E.ExecutionStream(ins, T.TF, mkt(ins, [(tts(0), tts(56)), (tts(100), tts(160))]), eod_cfg())
    for c in cs:
        st.on_candle(c)
    assert st.records[0].status == E.ENTERED
    st.mark_data_interrupted(tts(53))
    st.mark_data_resumed(tts(100))
    nxt = Candle(len(cs), tts(100), 116.70, 116.80, 116.65, 116.75, 1.0)
    out = st.on_candle(nxt)
    r = out[0]
    assert r.status == E.EOD_FLATTEN and r.detail == E.EOD_DATA_MISSING and "EOD_DATA_MISSING" in r.diagnostics
    assert r.exit_fill == D("116.70") - D("0.01") and r.exit_gap is True


def test_config_rules_for_eod():
    with pytest.raises(ConfigError):
        T.cfg(eod_flatten_buffer=5)                                          # both or neither
    with pytest.raises(ConfigError):
        T.cfg(eod_flatten_buffer=15, entry_cutoff_buffer=5)                  # cutoff >= flatten buffer
    rep = E.analyze_execution(T.series(T.BASE + T.CONFIRM + [T.N], "C"), "C", T.TF, T.market("C"),
                              eod_cfg(trading_day_start="00:00"))             # 24/7 calendar: EOD not possible
    assert T.only(rep).reason_code == E.EXECUTION_CONFIG_INCOMPLETE and "eod_flatten" in T.only(rep).detail


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_portfolio_books_eod_exit_once_and_restart_never_duplicates(tmp_path, side):
    root, led = _fx.book(tmp_path)
    ins = "AAA"
    rows = T.BASE + T.CONFIRM + [T.N, T.Q, T.Q, T.Q]
    if side == "SELL":
        rows = T.mirror(rows)
    sp = InstrumentSpec(ins, "US", "5m", mkt(ins, [(tts(0), tts(56))]), eod_cfg(starting_equity="1000"))
    pf = Portfolio(root, led, [sp])
    for c in T.series(rows, ins):
        pf.on_candle(ins, c)
    t = led.state["closed_trades"][0]
    assert (t["status"], t["exit_reason"], t["position_side"]) == ("EOD_FLATTEN", "EOD_FLATTEN",
                                                                    "LONG" if side == "BUY" else "SHORT")
    assert led.summary()["by_side"]["LONG" if side == "BUY" else "SHORT"]["eod_flatten"] == 1
    seq = led.state["seq"]
    pf2 = Portfolio(root, BookLedger.load(root, "US"), [sp])
    pf2.recover()
    led2 = pf2.ledger
    assert led2.state["seq"] == seq and len(led2.state["closed_trades"]) == 1 and led2.open_trade is None


# ------------------------------------------------------------------ C. long / short
def test_long_and_short_accounting_by_side(tmp_path):
    root, led = _fx.book(tmp_path)
    pf = Portfolio(root, led, [_fx.spec("AAA")])
    _fx.feed(pf, {"AAA": _fx.candles(_fx.TWO_CLOSED_ROWS, "AAA")})
    s = led.summary()
    long_t, short_t = led.state["closed_trades"]
    assert (long_t["position_side"], short_t["position_side"]) == ("LONG", "SHORT")
    assert s["by_side"]["LONG"]["realized_pnl"] == long_t["realized_pnl"]
    assert s["by_side"]["SHORT"]["realized_pnl"] == short_t["realized_pnl"]
    assert D(s["realized_pnl"]) == D(long_t["realized_pnl"]) + D(short_t["realized_pnl"])
    # short P&L is entry - exit (sold high, bought back lower = profit)
    q = D(short_t["quantity"])
    assert D(short_t["gross_pnl"]) == (D(short_t["entry_fill"]) - D(short_t["exit_fill"])) * q


def test_shorts_refused_when_short_side_not_ready(tmp_path):
    root, led = _fx.book(tmp_path)
    sp = _fx.spec("AAA")
    sp = InstrumentSpec(sp.instrument_id, "US", "5m", sp.market, sp.execution, shorts_enabled=False)
    pf = Portfolio(root, led, [sp])
    _fx.feed(pf, {"AAA": _fx.candles(_fx.TWO_CLOSED_ROWS, "AAA")})
    assert [t["side"] for t in led.state["closed_trades"]] == ["BUY"]
    assert [r["code"] for r in led.state["rejections"]] == [BOOK_SHORT_NOT_READY]


def test_short_side_parameters_are_used_for_sell_entries():
    conf = T.cfg(quantity_step="0.01", lot_size="0.01", min_quantity="0.01", short_quantity_step="1",
                 short_min_quantity="1", short_margin_rate="1.5", mtm_exit_slippage_ticks=2)
    rep = E.analyze_execution(T.series(T.mirror(T.BASE + T.CONFIRM + [T.N]), "S"), "S", T.TF, T.market("S"), conf)
    r = T.only(rep)
    assert r.side == "SELL" and r.quantity == r.quantity.to_integral_value()   # whole shares for shorts
    assert r.required_margin == r.entry_fill * r.quantity * D("1.5")
    rep = E.analyze_execution(T.series(T.BASE + T.CONFIRM + [T.N], "L"), "L", T.TF, T.market("L"), conf)
    q = T.only(rep).quantity
    assert q != q.to_integral_value()                                           # longs on the 0.01 grid


# ------------------------------------------------------------------ D. fractional sizing
def test_fractional_grid_never_exceeds_risk_or_capital():
    for eq in ("1000", "250", "100"):
        conf = T.cfg(starting_equity=eq, quantity_step="0.01", lot_size="0.01", min_quantity="0.01",
                     initial_margin_rate="1", mtm_exit_slippage_ticks=2)
        r = T.only(E.analyze_execution(T.series(T.BASE + T.CONFIRM + [T.N], "F"), "F", T.TF, T.market("F"), conf))
        assert r.status == E.ENTERED
        assert (r.quantity / D("0.01")) == (r.quantity / D("0.01")).to_integral_value()
        assert r.loss_estimate <= D("0.01") * D(eq)                            # 1% risk budget holds after rounding
        assert r.required_margin <= D(eq)                                       # never more capital than available
        bigger = r.quantity + D("0.01")                                         # one more step would break a limit
        assert (bigger * r.entry_fill > D(eq)) or (bigger * (r.entry_fill - r.planned_stop_fill) > D("0.01") * D(eq) - (
            r.loss_estimate - r.quantity * (r.entry_fill - r.planned_stop_fill)))


def test_min_quantity_and_grid_validation():
    conf = T.cfg(starting_equity="1000", quantity_step="0.01", lot_size="0.01", min_quantity="50",
                 mtm_exit_slippage_ticks=2)
    r = T.only(E.analyze_execution(T.series(T.BASE + T.CONFIRM + [T.N], "M"), "M", T.TF, T.market("M"), conf))
    assert r.reason_code == E.MIN_QTY_EXCEEDS_RISK_BUDGET
    for bad in (dict(lot_size="0.01", quantity_step="0.015"), dict(quantity_step="0.01", min_quantity="0.005"),
                dict(lot_size="0.01", short_quantity_step="0.005")):
        with pytest.raises(ConfigError):
            T.cfg(**bad)


def test_insufficient_capital_reduces_then_refuses():
    conf = T.cfg(starting_equity="1000", quantity_step="0.01", lot_size="0.01", min_quantity="0.01",
                 initial_margin_rate="2", mtm_exit_slippage_ticks=2)          # risk alone would want > $500 notional
    r = T.only(E.analyze_execution(T.series(T.BASE + T.CONFIRM + [T.N], "Q"), "Q", T.TF, T.market("Q"), conf))
    assert "QUANTITY_REDUCED_FOR_MARGIN" in r.diagnostics and r.required_margin <= D("1000")
    assert r.quantity < r.risk_quantity and (r.quantity + D("0.01")) * r.entry_fill * 2 > D("1000")
    conf = T.cfg(starting_equity="1", quantity_step="0.01", lot_size="0.01", min_quantity="0.01",
                 initial_margin_rate="1", mtm_exit_slippage_ticks=2)
    r = T.only(E.analyze_execution(T.series(T.BASE + T.CONFIRM + [T.N], "Q"), "Q", T.TF, T.market("Q"), conf))
    assert r.reason_code in (E.INSUFFICIENT_MARGIN, E.MIN_QTY_EXCEEDS_RISK_BUDGET) and r.status == E.NO_TRADE
    assert r.quantity is None and r.entry_fee is None                           # nothing was filled


# ------------------------------------------------------------------ E. sell-side fees
FEE = fees_us.UsEquityFeeSchedule("0", "TEST: verified $0 commission")
APR4 = datetime(2026, 4, 6, 15, 0, tzinfo=UTC)


def up(x):
    return x.quantize(D("0.01"), rounding=ROUND_UP)


def test_buy_fills_pay_no_sec_or_taf():
    assert FEE.components(D("600"), D("10"), D(1), fill_side="BUY", at=APR4) == {
        "commission": D(0), "sec_fee": D("0.00"), "finra_taf": D("0.00")}


def test_sell_fill_sec_and_taf_rounded_up_per_component():
    c = FEE.components(D("612.34"), D("3.27"), D(1), fill_side="SELL", at=APR4)
    assert c["sec_fee"] == up(D("612.34") * D("3.27") * D("20.60") / 1000000) == D("0.05")
    assert c["finra_taf"] == up(D("3.27") * D("0.000195")) == D("0.01")
    assert FEE.fee(D("612.34"), D("3.27"), D(1), fill_side="SELL", at=APR4) == D("0.06")


def test_taf_cap_and_dated_rates():
    big = FEE.components(D("10"), D("100000"), D(1), fill_side="SELL", at=APR4)
    assert big["finra_taf"] == D("9.79")                                     # 2026 cap
    assert FEE.components(D("10"), D("100000"), D(1), fill_side="SELL",
                          at=datetime(2027, 2, 1, 15, 0, tzinfo=UTC))["finra_taf"] == D("11.61")   # 2027 cap
    before = FEE.components(D("600"), D("10"), D(1), fill_side="SELL", at=datetime(2026, 4, 3, 15, 0, tzinfo=UTC))
    assert before["sec_fee"] == D("0.00")                                    # $0.00 per million through 2026-04-03
    assert FEE.components(D("600"), D("10"), D(1), fill_side="SELL",
                          at=datetime(2026, 4, 3, 22, 0, tzinfo=UTC))["sec_fee"] == D("0.00")  # 18:00 NY, still 3 Apr
    with pytest.raises(fees_us.FeeRateUnavailable):
        FEE.fee(D("1"), D("1"), D(1), fill_side="SELL", at=datetime(2025, 12, 31, 15, 0, tzinfo=UTC))
    with pytest.raises(fees_us.FeeRateUnavailable):
        FEE.fee(D("1"), D("1"), D(1), fill_side=None, at=APR4)              # side is mandatory
    assert fees_us.reverify_due(date(2026, 12, 1)) is None and fees_us.reverify_due(date(2027, 6, 1))


def test_fee_config_requires_verified_commission():
    with pytest.raises(ValueError):
        fees_us.from_config({"model": fees_us.MODEL, "commission_per_order": "0"})     # no source
    with pytest.raises(ValueError):
        fees_us.from_config({"model": fees_us.MODEL, "commission_source": "x"})       # no value
    with pytest.raises(ValueError):
        fees_us.from_config({"rate": "0.0001"})                                       # linear refused for US


def test_short_pays_sell_fees_on_entry_and_long_on_exit_net_pnl(tmp_path):
    root, led = _fx.book(tmp_path)
    ex = _fx.cfg()
    import dataclasses
    ex = dataclasses.replace(ex, fee_schedule=FEE, quantity_step=D("0.01"), lot_size=D("0.01"), min_quantity=D("0.01"))
    mk = T.market("AAA", session={"kind": "exchange_sessions", "timezone": "UTC",
                                  "sessions": [[datetime(2026, 4, 6, 9, tzinfo=UTC).timestamp(),
                                                datetime(2026, 4, 6, 23, tzinfo=UTC).timestamp()]]})
    sp = InstrumentSpec("AAA", "US", "5m", mk, ex)
    pf = Portfolio(root, led, [sp])
    t0 = datetime(2026, 4, 6, 9, 0, tzinfo=UTC)
    rows = _fx.TWO_CLOSED_ROWS
    from scanner_v6.data.candle_models import CandleSeries
    series = CandleSeries.from_rows([(t0 + timedelta(minutes=5 * i), o, h, l, c) for i, (o, h, l, c) in enumerate(rows)],
                                    "AAA", "5m")
    for c in series:
        pf.on_candle("AAA", c)
    long_t, short_t = led.state["closed_trades"]
    assert D(long_t["entry_fee"]) == 0 and D(long_t["exit_fee"]) > 0           # long: sell on exit
    assert D(short_t["entry_fee"]) > 0 and D(short_t["exit_fee"]) == 0         # short: sell on entry
    assert long_t["exit_fee_components"]["sec_fee"] == str(up(D(long_t["exit_fill"]) * D(long_t["quantity"])
                                                              * D("20.60") / 1000000))
    for t in (long_t, short_t):
        assert D(t["realized_pnl"]) == D(t["gross_pnl"]) - D(t["entry_fee"]) - D(t["exit_fee"])


# ------------------------------------------------------------------ F. backtest reflects every decision
def test_backtest_identifies_shorts_eod_and_fee_components(tmp_path):
    raw = json.load(open(os.path.join(_fx.HERE, "fixtures", "backtest_us_synthetic.json")))
    r = BacktestRun(DataRoot(str(tmp_path)), bcfg.parse(raw), {"SYNTH": os.path.join(_fx.HERE, "fixtures",
                                                                                     "synth_nyse_5m.csv")},
                    date(2026, 11, 23), date(2026, 11, 23))
    res = r.execute()
    m = res["metrics"]
    assert set(m["by_side"]) == {"LONG", "SHORT"} and m["exit_reasons"] == {"STOPPED_OUT": 1, "TARGET_HIT": 1}
    assert [t["position_side"] for t in res["trades"]] == ["LONG", "SHORT"]
    assert D(m["fee_components"]["sec_fee"]) + D(m["fee_components"]["finra_taf"]) + D(
        m["fee_components"]["commission"]) == D(m["fees_total"])
    assert all((D(t["quantity"]) / D("0.01")) == (D(t["quantity"]) / D("0.01")).to_integral_value() for t in res["trades"])
    eod_raw = dict(raw, execution=dict(raw["execution"], eod_flatten_buffer=40, entry_cutoff_buffer=45))
    res2 = BacktestRun(DataRoot(str(tmp_path / "b")), bcfg.parse(eod_raw), {"SYNTH": os.path.join(
        _fx.HERE, "fixtures", "synth_nyse_5m.csv")}, date(2026, 11, 23), date(2026, 11, 23)).execute()
    assert res2["metrics"]["exit_reasons"].get("EOD_FLATTEN", 0) + res2["metrics"]["exit_reasons"].get(
        "STOPPED_OUT", 0) >= 1 and res2["metrics"]["open_trades_at_end"] == 0


def test_backtest_us_requires_sell_side_fees_and_eod():
    raw = json.load(open(os.path.join(_fx.HERE, "fixtures", "backtest_us_synthetic.json")))
    bad = dict(raw, execution=dict(raw["execution"], fee_schedule={"rate": "0", "per_unit": "0", "per_order": "0",
                                                                    "rounding_places": 2, "rounding_mode": "ROUND_UP",
                                                                    "source": "x"}))
    with pytest.raises(bcfg.BacktestConfigError, match="sell-side"):
        bcfg.parse(bad)
    ex = dict(raw["execution"])
    ex.pop("eod_flatten_buffer")
    with pytest.raises(bcfg.BacktestConfigError, match="flatten"):
        bcfg.parse(dict(raw, execution=ex))
    with pytest.raises(bcfg.BacktestConfigError, match="shorts_enabled"):
        bcfg.parse({k: v for k, v in raw.items() if k != "shorts_enabled"})


# ------------------------------------------------------------------ G. audit follow-ups (independent audit F-2...F-15)
def test_eod_buffers_must_fit_the_timeframe():
    r = T.only(run_rows([T.N], conf=eod_cfg(eod_flatten_buffer=2, entry_cutoff_buffer=15)))        # 2 min < 5m bar
    assert r.reason_code == E.EXECUTION_CONFIG_INCOMPLETE and "eod_flatten_buffer<timeframe" in r.detail
    r = T.only(run_rows([T.N], conf=eod_cfg(eod_flatten_buffer=5, entry_cutoff_buffer=5)))         # same-bar entry/flat
    assert r.reason_code == E.EXECUTION_CONFIG_INCOMPLETE and "entry_cutoff_buffer<" in r.detail


def test_readiness_reports_module_e_refusal_instead_of_crash_looping():
    from test_iex_feed import _approved                                        # noqa: E402
    raw = _approved("iex")
    raw["values"]["entry_cutoff_minutes"]["value"] = 5                        # == flatten buffer: refused by Module E
    r = us_stocks.readiness(us_stocks.parse_config(raw), CAL, True, today=date(2026, 11, 24))
    assert r["ready"] is False and any("entry_cutoff_buffer<eod_flatten_buffer+timeframe" in b for b in r["blockers"])


def test_disabled_short_never_occupies_the_stream():
    """A SELL setup with shorts disabled is NO_TRADE in Module E itself, so a later long on the same instrument can
    still trade (the earlier book-level refusal left a SHADOW short holding the stream's single position)."""
    conf = T.cfg(shorts_enabled=False, mtm_exit_slippage_ticks=2)
    rows = T.mirror(T.BASE + T.CONFIRM + T.TWO_CLOSED)                         # SELL setup first, then a BUY setup
    rep = E.analyze_execution(T.series(rows, "X"), "X", T.TF, T.market("X"), conf)
    first, second = rep.records
    assert (first.side, first.status, first.disposition_reason) == ("SELL", E.NO_TRADE, E.SHORT_SIDE_DISABLED)
    assert second.side == "BUY" and second.status in (E.TARGET_HIT, E.STOPPED_OUT, E.ENTERED, E.NO_TRADE)
    assert second.disposition_reason != E.POSITION_LIMIT_REACHED and second.entry_fill is not None


def test_late_flatten_is_flagged():
    ins = "LATE"
    cs = list(T.series(T.BASE + T.CONFIRM + [T.N, T.Q, T.Q], ins))           # 51..53 present
    st = E.ExecutionStream(ins, T.TF, mkt(ins, [(tts(0), tts(57))]), eod_cfg())   # flatten time t(56)
    for c in cs:
        st.on_candle(c)
    st.mark_data_interrupted(tts(54))
    st.mark_data_resumed(tts(56))
    r = st.on_candle(Candle(len(cs), tts(56), 116.6, 116.7, 116.5, 116.6, 1.0))[0]     # 54, 55 never arrived
    assert r.status == E.EOD_FLATTEN and r.detail == "EOD_FLATTEN_LATE" and "EOD_FLATTEN_LATE" in r.diagnostics


def test_bars_too_old_for_real_time_are_never_traded():
    from v6_runtime.data.alpaca import Bar
    from v6_runtime.data.feed import ACCEPT, TOO_OLD, BarFeed
    f = BarFeed("SPY", timedelta(minutes=5), us_stocks.session_calendar(CAL, date(2026, 11, 23), date(2026, 11, 23)),
                10, 2, "session_grid")
    o = datetime(2026, 11, 23, 14, 30, tzinfo=UTC)
    b = lambda k: Bar("SPY", o + timedelta(minutes=5 * k), 100.0, 100.2, 99.9, 100.1, 5.0)   # noqa: E731
    assert f.offer(b(0), o + timedelta(minutes=6)).status == ACCEPT
    now = o + timedelta(minutes=60)                                            # the runner was down ~50 minutes
    assert f.offer(b(2), now).status == TOO_OLD                                # never filled retroactively
    r = f.offer(b(10), o + timedelta(minutes=56))                              # first fresh bar
    assert r.status == ACCEPT and [e[0] for e in r.events] == ["DATA_INTERRUPTED", "DATA_RESUMED"]


def test_data_adapter_refuses_redirects():
    from v6_runtime.data import alpaca as A
    h = A._NoRedirect()
    with pytest.raises(A.AlpacaDataError, match="redirect"):
        h.redirect_request(None, None, 302, "Found", {}, "https://evil.example/v2/stocks/AAPL/bars")
