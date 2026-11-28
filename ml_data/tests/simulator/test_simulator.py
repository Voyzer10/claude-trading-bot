"""Comprehensive synthetic tests for Phase 2A Execution Simulator."""
from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

import pytest

from ml_data.calendars import (
    CalendarMetadata,
    CryptoCalendarAdapter,
    ExchangeCalendar,
    build_verified_nse_calendar,
    build_verified_us_equity_calendar,
)
from ml_data.instruments import (
    AssetClass,
    ContractType,
    Instrument,
    InstrumentRegistry,
    Market,
    Segment,
    SettlementType,
)
from ml_data.simulator import (
    CalendarVerificationError,
    CostProfile,
    ExecutionSimulator,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    SimulationConfig,
    TimeInForce,
)
from ml_data.storage.canonical_schema import CanonicalCandle, CanonicalQuote

UTC = timezone.utc


def _make_equity(
    symbol: str = "AAPL",
    *,
    market: Market = Market.US,
    exchange: str = "NASDAQ",
    segment: Segment = Segment.US_EQUITY,
    currency: str = "USD",
    tick_size: Decimal = Decimal("0.01"),
    lot_size: Decimal = Decimal("1"),
    contract_multiplier: Optional[Decimal] = None,
    effective_from: Optional[datetime] = None,
) -> Instrument:
    return Instrument(
        instrument_id="",
        market=market,
        asset_class=AssetClass.EQUITY,
        segment=segment,
        exchange=exchange,
        canonical_symbol=symbol,
        trading_symbol=symbol,
        display_name=symbol,
        price_currency=currency,
        primary_provider="alpaca",
        tick_size=tick_size,
        lot_size=lot_size,
        contract_multiplier=contract_multiplier,
        quantity_step=lot_size,
        minimum_order_quantity=lot_size,
        effective_from=effective_from,
    )


def _make_index(symbol: str = "NIFTY") -> Instrument:
    return Instrument(
        instrument_id="",
        market=Market.IN,
        asset_class=AssetClass.INDEX,
        segment=Segment.IN_INDEX,
        exchange="NSE",
        canonical_symbol=symbol,
        trading_symbol=symbol,
        display_name=symbol,
        price_currency="INR",
        primary_provider="kite",
        is_tradable=False,
    )


def _make_future(
    symbol: str = "NIFTY26MARFUT",
    *,
    underlying_instrument_id: str,
    expiry: date = date(2026, 3, 30),
    lot_size: Decimal = Decimal("25"),
    tick_size: Decimal = Decimal("0.05"),
    multiplier: Decimal = Decimal("1"),
    effective_from: Optional[datetime] = None,
) -> Instrument:
    return Instrument(
        instrument_id="",
        market=Market.IN,
        asset_class=AssetClass.FUTURE,
        segment=Segment.IN_INDEX_FUTURES,
        exchange="NFO",
        canonical_symbol=symbol,
        trading_symbol=symbol,
        display_name=symbol,
        price_currency="INR",
        primary_provider="kite",
        underlying_instrument_id=underlying_instrument_id,
        expiry_date=expiry,
        last_trade_date=expiry,
        contract_type=ContractType.DATED_FUTURE,
        settlement_type=SettlementType.CASH,
        tick_size=tick_size,
        lot_size=lot_size,
        contract_multiplier=multiplier,
        quantity_step=lot_size,
        minimum_order_quantity=lot_size,
        effective_from=effective_from,
    )


def _make_crypto_perp(symbol: str = "BTCUSDT_PERP") -> Instrument:
    return Instrument(
        instrument_id="",
        market=Market.CRYPTO,
        asset_class=AssetClass.CRYPTO_PERPETUAL,
        segment=Segment.CRYPTO_PERPETUALS,
        exchange="COINDCX",
        canonical_symbol=symbol,
        trading_symbol=symbol,
        display_name=symbol,
        price_currency="USDT",
        primary_provider="coindcx",
        base_currency="BTC",
        quote_currency="USDT",
        settlement_currency="USDT",
        contract_type=ContractType.PERPETUAL,
        settlement_type=SettlementType.CASH,
        tick_size=Decimal("0.1"),
        lot_size=Decimal("0.001"),
        contract_multiplier=Decimal("1"),
        quantity_step=Decimal("0.001"),
        minimum_order_quantity=Decimal("0.001"),
    )


def _bar(
    inst: Instrument,
    start_utc: datetime,
    o: str,
    h: str,
    l: str,
    c: str,
    v: str = "1000",
    *,
    minutes: int = 5,
    trading_date: Optional[date] = None,
    session: str = "REGULAR",
) -> CanonicalCandle:
    end_utc = start_utc + timedelta(minutes=minutes)
    td = trading_date or start_utc.date()
    return CanonicalCandle(
        instrument_id=inst.instrument_id,
        market=inst.market.value,
        asset_class=inst.asset_class.value,
        segment=inst.segment.value,
        exchange=inst.exchange,
        provider=inst.primary_provider,
        provider_symbol=inst.trading_symbol,
        provider_instrument_id=inst.trading_symbol,
        timestamp_start_utc=start_utc,
        timestamp_end_utc=end_utc,
        event_time_utc=end_utc,
        received_at_utc=end_utc,
        timeframe=f"{minutes}m",
        trading_date=td,
        trading_session=session,
        session_id=f"{inst.exchange}_{td.isoformat()}",
        calendar_id=f"{inst.exchange}_CAL",
        calendar_version="1.0.0",
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(l),
        close=Decimal(c),
        volume=Decimal(v),
        provider_feed="synthetic",
        source_snapshot_id="snap-1",
        source_record_id=f"rec-{start_utc.isoformat()}",
        dataset_version="test-v1",
        adjustment_mode="RAW",
        retrieval_run_id="run-1",
        quality_status="VERIFIED",
    )


def _zero_cost() -> CostProfile:
    return CostProfile(profile_id="zero", version="1.0")


def _us_bars_sequence(inst: Instrument, d: date = date(2026, 1, 5), n: int = 6) -> List[CanonicalCandle]:
    # US regular session: 14:30 UTC .. 21:00 UTC
    base = datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC)
    bars: List[CanonicalCandle] = []
    for i in range(n):
        px = Decimal("100") + Decimal(i)
        bars.append(
            _bar(
                inst,
                base + timedelta(minutes=5 * i),
                str(px),
                str(px + Decimal("2")),
                str(px - Decimal("1")),
                str(px + Decimal("1")),
                v="1000",
                trading_date=d,
            )
        )
    return bars


def test_next_bar_execution_never_fills_on_same_bar_close() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    bars = _us_bars_sequence(inst)
    cal = build_verified_us_equity_calendar()

    # Decision made at close of bar[0] (14:35 UTC) -> must NOT fill on bar[0]; fills on bar[1] open (14:35 UTC)
    intent = OrderIntent(
        order_id="ord-1",
        instrument_id=inst.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
        decision_ts_utc=bars[0].timestamp_end_utc,
    )
    cfg = SimulationConfig(
        config_id="cfg-1",
        initial_cash=Decimal("10000"),
        cost_profile=_zero_cost(),
        next_bar_execution=True,
        enforce_intraday_cutoff=False,
    )
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run(bars, [intent])
    assert len(res.fills) == 1
    fill = res.fills[0]
    assert fill.ts_utc == bars[1].timestamp_start_utc
    assert fill.raw_price == bars[1].open
    assert res.orders[0].status == OrderStatus.FILLED


def test_latency_bars_delays_execution() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    bars = _us_bars_sequence(inst)
    cal = build_verified_us_equity_calendar()

    intent = OrderIntent(
        order_id="ord-lat",
        instrument_id=inst.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
        decision_ts_utc=bars[0].timestamp_end_utc,
    )
    cfg = SimulationConfig(
        config_id="cfg-lat",
        initial_cash=Decimal("10000"),
        cost_profile=_zero_cost(),
        next_bar_execution=True,
        latency_bars=1,
        enforce_intraday_cutoff=False,
    )
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run(bars, [intent])
    assert len(res.fills) == 1
    assert res.fills[0].ts_utc == bars[2].timestamp_start_utc
    assert res.fills[0].raw_price == bars[2].open


def test_spread_slippage_fees_and_net_pnl() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    d = date(2026, 1, 5)
    base = datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC)
    bars = [
        _bar(inst, base, "100", "101", "99", "100", trading_date=d),
        _bar(inst, base + timedelta(minutes=5), "100", "102", "99", "101", trading_date=d),
        _bar(inst, base + timedelta(minutes=10), "110", "111", "109", "110", trading_date=d),
    ]
    cal = build_verified_us_equity_calendar()
    costs = CostProfile(
        profile_id="std",
        version="1.0",
        fee_bps=Decimal("10"),        # 0.10%
        slippage_bps=Decimal("5"),    # 0.05%
        spread_half_bps=Decimal("5"), # 0.05%
        fixed_fee_per_order=Decimal("1"),
    )
    intents = [
        OrderIntent("buy-1", inst.instrument_id, OrderSide.BUY, OrderType.MARKET, Decimal("10"), bars[0].timestamp_end_utc),
        OrderIntent("sell-1", inst.instrument_id, OrderSide.SELL, OrderType.MARKET, Decimal("10"), bars[1].timestamp_end_utc),
    ]
    cfg = SimulationConfig(config_id="cfg-cost", initial_cash=Decimal("10000"), cost_profile=costs)
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run(bars, intents)

    assert len(res.fills) == 2
    assert res.metrics.gross_pnl == Decimal("100")  # (110 - 100) * 10
    assert res.metrics.total_costs > Decimal("0")
    assert res.metrics.net_pnl == res.metrics.gross_pnl - res.metrics.total_costs
    assert res.metrics.final_equity == Decimal("10000") + res.metrics.net_pnl


def test_partial_fills_and_participation_limits() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    d = date(2026, 1, 5)
    base = datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC)
    # Volume=100 per bar; max_participation_rate=0.25 -> max 25 shares per bar
    bars = [
        _bar(inst, base + timedelta(minutes=5 * i), "100", "101", "99", "100", v="100", trading_date=d)
        for i in range(4)
    ]
    cal = build_verified_us_equity_calendar()
    intent = OrderIntent(
        order_id="big-buy",
        instrument_id=inst.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("60"),
        decision_ts_utc=bars[0].timestamp_end_utc,
    )
    cfg = SimulationConfig(
        config_id="cfg-part",
        initial_cash=Decimal("50000"),
        cost_profile=_zero_cost(),
        max_participation_rate=Decimal("0.25"),
        allow_partial_fills=True,
        enforce_intraday_cutoff=False,
    )
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run(bars, [intent])
    # Remaining 3 bars * 25 = 75 capacity >= 60 -> 25 + 25 + 10
    assert [f.quantity for f in res.fills] == [Decimal("25"), Decimal("25"), Decimal("10")]
    assert res.orders[0].status == OrderStatus.FILLED
    assert res.metrics.partial_fills >= 2


def test_limit_order_non_fill_and_ioc_expiry() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    bars = _us_bars_sequence(inst)
    cal = build_verified_us_equity_calendar()

    # Limit buy at 50 when bars low >= 99 -> never fills
    day_limit = OrderIntent(
        order_id="lim-day",
        instrument_id=inst.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50"),
        quantity=Decimal("10"),
        decision_ts_utc=bars[0].timestamp_end_utc,
        time_in_force=TimeInForce.DAY,
    )
    ioc_limit = OrderIntent(
        order_id="lim-ioc",
        instrument_id=inst.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50"),
        quantity=Decimal("10"),
        decision_ts_utc=bars[0].timestamp_end_utc,
        time_in_force=TimeInForce.IOC,
    )
    cfg = SimulationConfig(config_id="cfg-lim", initial_cash=Decimal("10000"), cost_profile=_zero_cost())
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run(bars, [day_limit, ioc_limit])
    assert len(res.fills) == 0
    statuses = {o.order_id: o.status for o in res.orders}
    assert statuses["lim-ioc"] == OrderStatus.CANCELLED
    assert statuses["lim-day"] in (OrderStatus.ACCEPTED, OrderStatus.EXPIRED)


def test_stop_loss_gap_through_fills_at_open() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    d = date(2026, 1, 5)
    base = datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC)
    bars = [
        _bar(inst, base, "100", "101", "99", "100", trading_date=d),
        _bar(inst, base + timedelta(minutes=5), "100", "101", "99", "100", trading_date=d),
        # Gaps down to open=90 below stop_loss=95 -> must fill at 90 (gap price), NOT 95!
        _bar(inst, base + timedelta(minutes=10), "90", "92", "89", "91", trading_date=d),
    ]
    cal = build_verified_us_equity_calendar()
    intent = OrderIntent(
        order_id="buy-sl",
        instrument_id=inst.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
        decision_ts_utc=bars[0].timestamp_end_utc,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
    )
    cfg = SimulationConfig(config_id="cfg-gap", initial_cash=Decimal("10000"), cost_profile=_zero_cost())
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run(bars, [intent])
    assert len(res.fills) == 2
    sl_fill = res.fills[1]
    assert sl_fill.side == OrderSide.SELL
    assert sl_fill.raw_price == Decimal("90")
    assert res.positions[inst.instrument_id].quantity == Decimal("0")


def test_ambiguous_intrabar_sl_and_tp_touch_takes_adverse_sl() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    d = date(2026, 1, 5)
    base = datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC)
    bars = [
        _bar(inst, base, "100", "101", "99", "100", trading_date=d),
        _bar(inst, base + timedelta(minutes=5), "100", "101", "99", "100", trading_date=d),
        # Bar[2] touches BOTH SL=95 (low=94) and TP=105 (high=106)
        _bar(inst, base + timedelta(minutes=10), "100", "106", "94", "102", trading_date=d),
    ]
    cal = build_verified_us_equity_calendar()
    intent = OrderIntent(
        order_id="buy-amb",
        instrument_id=inst.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
        decision_ts_utc=bars[0].timestamp_end_utc,
        stop_loss=Decimal("95"),
        take_profit=Decimal("105"),
    )
    cfg = SimulationConfig(
        config_id="cfg-amb",
        initial_cash=Decimal("10000"),
        cost_profile=_zero_cost(),
        ambiguous_intrabar_rule="ADVERSE",
    )
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run(bars, [intent])
    assert len(res.fills) == 2
    exit_fill = res.fills[1]
    assert exit_fill.raw_price == Decimal("95")
    assert exit_fill.is_ambiguous is True
    assert res.metrics.ambiguous_fills == 1


def test_intraday_session_close_auto_flattens_no_overnight() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    d1 = date(2026, 1, 5)
    # Last two bars of US regular session: 20:50-20:55 and 20:55-21:00 UTC
    b0 = _bar(inst, datetime(2026, 1, 5, 20, 45, tzinfo=UTC), "100", "101", "99", "100", trading_date=d1)
    b1 = _bar(inst, datetime(2026, 1, 5, 20, 50, tzinfo=UTC), "100", "101", "99", "100", trading_date=d1)
    b2 = _bar(inst, datetime(2026, 1, 5, 20, 55, tzinfo=UTC), "102", "103", "101", "102", trading_date=d1)

    cal = build_verified_us_equity_calendar()
    intent = OrderIntent(
        order_id="buy-eod",
        instrument_id=inst.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
        decision_ts_utc=b0.timestamp_end_utc,
    )
    cfg = SimulationConfig(
        config_id="cfg-eod",
        initial_cash=Decimal("10000"),
        cost_profile=_zero_cost(),
        enforce_intraday_cutoff=True,
    )
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run([b0, b1, b2], [intent])
    # Entered at b1 open (100), auto-flattened at session close b2 close (102)
    assert res.positions[inst.instrument_id].quantity == Decimal("0")
    assert any(e.event_type == "INTRADAY_FLATTEN" for e in res.event_log)
    assert res.metrics.net_pnl == Decimal("20")


def test_unverified_calendar_raises_and_early_close_flattened() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    # Early close day on US equities: 2026-11-27 (Black Friday closes 13:00 ET = 18:00 UTC)
    d_early = date(2026, 11, 27)
    b0 = _bar(inst, datetime(2026, 11, 27, 17, 45, tzinfo=UTC), "100", "101", "99", "100", trading_date=d_early)
    b1 = _bar(inst, datetime(2026, 11, 27, 17, 50, tzinfo=UTC), "100", "101", "99", "100", trading_date=d_early)
    b2 = _bar(inst, datetime(2026, 11, 27, 17, 55, tzinfo=UTC), "101", "102", "100", "101", trading_date=d_early)

    cal = build_verified_us_equity_calendar()
    intent = OrderIntent("buy-early", inst.instrument_id, OrderSide.BUY, OrderType.MARKET, Decimal("5"), b0.timestamp_end_utc)
    cfg = SimulationConfig(config_id="cfg-early", initial_cash=Decimal("10000"), cost_profile=_zero_cost())
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run([b0, b1, b2], [intent])
    assert res.positions[inst.instrument_id].quantity == Decimal("0")
    assert any(e.event_type == "INTRADAY_FLATTEN" for e in res.event_log)

    # Unverified calendar must raise CalendarVerificationError
    class _UnverifiedCal(ExchangeCalendar):
        @property
        def metadata(self) -> CalendarMetadata:
            return CalendarMetadata(
                calendar_id="FAKE",
                calendar_version="0.1",
                timezone="America/New_York",
                verified_years=frozenset(),
                verification_status="UNVERIFIED",
            )

        def is_trading_day(self, day: date, *, require_verified: bool = False) -> bool:
            return False

        def classify_session(self, ts: datetime, *, require_verified: bool = False) -> str:
            return "CLOSED"

        def trade_date_for(self, ts: datetime) -> date:
            return ts.date()

    with pytest.raises(CalendarVerificationError):
        ExecutionSimulator(config=cfg, registry=reg, calendar=_UnverifiedCal()).run([b0, b1], [intent])


def test_contract_multiplier_lot_size_tick_rounding_and_expiry_spec() -> None:
    reg = InstrumentRegistry(":memory:")
    idx = reg.register(_make_index())
    fut = reg.register(
        _make_future(
            underlying_instrument_id=idx.instrument_id,
            expiry=date(2026, 3, 30),
            lot_size=Decimal("25"),
            tick_size=Decimal("0.05"),
            multiplier=Decimal("2"),
            effective_from=datetime(2026, 3, 1, 0, 0, tzinfo=UTC),
        )
    )
    # NSE trading day 2026-03-30 (expiry date) - 09:15 IST = 03:45 UTC
    d = date(2026, 3, 30)
    base = datetime(2026, 3, 30, 3, 45, tzinfo=UTC)
    bars = [
        _bar(fut, base, "22000.00", "22010.00", "21995.00", "22005.00", trading_date=d),
        _bar(fut, base + timedelta(minutes=5), "22005.00", "22020.00", "21995.00", "22015.00", trading_date=d),
        _bar(fut, base + timedelta(minutes=10), "22015.00", "22025.00", "22010.00", "22020.00", trading_date=d),
    ]
    cal = build_verified_nse_calendar()
    # Request qty=30 -> rounded down to lot_size=25; limit_price=22005.03 -> rounded favorably for BUY to 22005.00
    intent = OrderIntent(
        order_id="fut-buy",
        instrument_id=fut.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("22005.03"),
        quantity=Decimal("30"),
        decision_ts_utc=bars[0].timestamp_end_utc,
    )
    cfg = SimulationConfig(
        config_id="cfg-fut",
        initial_cash=Decimal("5000000"),
        cost_profile=_zero_cost(),
        enforce_intraday_cutoff=True,
    )
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run(bars, [intent])
    assert len(res.fills) >= 1
    assert res.fills[0].quantity == Decimal("25")
    assert res.fills[0].raw_price == Decimal("22005.00")


def test_crypto_24_7_intraday_cutoff_flattens_at_23_55_utc() -> None:
    reg = InstrumentRegistry(":memory:")
    perp = reg.register(_make_crypto_perp())
    d = date(2026, 1, 5)
    b0 = _bar(perp, datetime(2026, 1, 5, 23, 40, tzinfo=UTC), "90000", "90100", "89900", "90000", trading_date=d)
    b1 = _bar(perp, datetime(2026, 1, 5, 23, 45, tzinfo=UTC), "90000", "90100", "89900", "90050", trading_date=d)
    b2 = _bar(perp, datetime(2026, 1, 5, 23, 50, tzinfo=UTC), "90100", "90200", "90000", "90150", trading_date=d)

    cal = CryptoCalendarAdapter()
    intent = OrderIntent("btc-1", perp.instrument_id, OrderSide.BUY, OrderType.MARKET, Decimal("0.010"), b0.timestamp_end_utc)
    cfg = SimulationConfig(
        config_id="cfg-crypto",
        initial_cash=Decimal("10000"),
        cost_profile=_zero_cost(),
        crypto_cutoff_utc=dt_time(23, 55),
    )
    res = ExecutionSimulator(config=cfg, registry=reg, calendar=cal).run([b0, b1, b2], [intent])
    assert res.positions[perp.instrument_id].quantity == Decimal("0")
    assert any(e.event_type == "INTRADAY_FLATTEN" for e in res.event_log)


def test_quote_mode_bbo_and_deterministic_replay() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    bars = _us_bars_sequence(inst)
    cal = build_verified_us_equity_calendar()
    q1 = CanonicalQuote(
        instrument_id=inst.instrument_id,
        event_time_utc=bars[1].timestamp_start_utc,
        received_at_utc=bars[1].timestamp_start_utc,
        bid_price=Decimal("100.90"),
        ask_price=Decimal("101.10"),
        bid_size=Decimal("500"),
        ask_size=Decimal("500"),
        exchange=inst.exchange,
        provider=inst.primary_provider,
        feed="iex",
    )
    intent = OrderIntent("q-buy", inst.instrument_id, OrderSide.BUY, OrderType.MARKET, Decimal("10"), bars[0].timestamp_end_utc)
    cfg = SimulationConfig(
        config_id="cfg-q",
        initial_cash=Decimal("10000"),
        cost_profile=_zero_cost(),
        execution_mode="QUOTE_OR_TRADE",
    )
    sim = ExecutionSimulator(config=cfg, registry=reg, calendar=cal)
    r1 = sim.run(bars, [intent], quotes=[q1])
    r2 = sim.run(bars, [intent], quotes=[q1])
    assert r1.fills[0].raw_price == Decimal("101.10")
    assert r1.fills[0].execution_basis == "QUOTE_BBO"
    assert r1.metrics == r2.metrics
    assert r1.equity_curve == r2.equity_curve
