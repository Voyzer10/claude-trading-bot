"""Comprehensive synthetic & anti-leakage tests for Phase 2B Label Engine."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import List

import pytest

from ml_data.instruments import AssetClass, Instrument, InstrumentRegistry, Market, Segment
from ml_data.labels import (
    LabelConfig,
    LabelEngine,
    LabelRecord,
    LeakageError,
    purged_embargo_split,
    read_labels_parquet,
    validate_no_leakage,
    write_labels_parquet,
)
from ml_data.simulator import CostProfile
from ml_data.storage.canonical_schema import CanonicalCandle

UTC = timezone.utc


def _make_equity(symbol: str = "MSFT") -> Instrument:
    return Instrument(
        instrument_id="",
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        segment=Segment.US_EQUITY,
        exchange="NASDAQ",
        canonical_symbol=symbol,
        trading_symbol=symbol,
        display_name=symbol,
        price_currency="USD",
        primary_provider="alpaca",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("1"),
        quantity_step=Decimal("1"),
        minimum_order_quantity=Decimal("1"),
    )


def _bar(
    inst: Instrument,
    start_utc: datetime,
    o: str,
    h: str,
    l: str,
    c: str,
    *,
    minutes: int = 5,
    trading_date: date | None = None,
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
        trading_session="REGULAR",
        session_id=f"{inst.exchange}_{td.isoformat()}",
        calendar_id=f"{inst.exchange}_CAL",
        calendar_version="1.0.0",
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(l),
        close=Decimal(c),
        volume=Decimal("1000"),
        provider_feed="synthetic",
        source_snapshot_id="snap-1",
        source_record_id=f"rec-{start_utc.isoformat()}",
        dataset_version="test-v1",
        adjustment_mode="RAW",
        retrieval_run_id="run-1",
        quality_status="VERIFIED",
    )


def _make_bars(inst: Instrument, n: int = 20, *, start_date: date = date(2025, 1, 6)) -> List[CanonicalCandle]:
    base = datetime(start_date.year, start_date.month, start_date.day, 14, 30, tzinfo=UTC)
    out: List[CanonicalCandle] = []
    for i in range(n):
        px = Decimal("100") + Decimal(i)
        out.append(
            _bar(
                inst,
                base + timedelta(minutes=5 * i),
                str(px),
                str(px + Decimal("2")),
                str(px - Decimal("1")),
                str(px + Decimal("0.5")),
                trading_date=start_date,
            )
        )
    return out


def test_fixed_horizon_labels_multi_horizon_and_costs() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    bars = _make_bars(inst, n=20)
    costs = CostProfile(profile_id="std", version="1.0", fee_bps=Decimal("10"), slippage_bps=Decimal("5"))
    cfg = LabelConfig(
        config_id="fh-1",
        config_version="1.0",
        method="FIXED_HORIZON",
        horizons_bars=(1, 3, 5, 15),
        neutral_threshold_bps=Decimal("5"),
        cost_profile=costs,
    )
    labels = LabelEngine(config=cfg, registry=reg).generate(bars)
    assert len(labels) == 20 * 4

    # Check bar 0, horizon 1: entry at bar[1].open (101), exit at bar[1].close (101.5)
    r_h1 = next(r for r in labels if r.decision_ts_utc == bars[0].timestamp_end_utc and r.horizon_bars == 1)
    assert r_h1.completion_status == "COMPLETE"
    assert r_h1.feature_cutoff_utc == r_h1.decision_ts_utc
    assert r_h1.earliest_executable_utc == bars[1].timestamp_start_utc
    assert r_h1.label_start_ts_utc == bars[1].timestamp_start_utc
    assert r_h1.label_end_ts_utc == bars[1].timestamp_end_utc
    assert r_h1.label_available_ts_utc == bars[1].timestamp_end_utc
    expected_gross = (Decimal("101.5") - Decimal("101")) / Decimal("101")
    assert r_h1.gross_return == expected_gross
    assert r_h1.net_return is not None and r_h1.net_return < r_h1.gross_return
    assert r_h1.mfe is not None and r_h1.mfe >= expected_gross
    assert r_h1.mae is not None and r_h1.mae <= Decimal("0")

    # Last bar must be INCOMPLETE_HORIZON
    last_h1 = next(r for r in labels if r.decision_ts_utc == bars[-1].timestamp_end_utc and r.horizon_bars == 1)
    assert last_h1.completion_status == "INCOMPLETE_HORIZON"
    assert last_h1.gross_return is None
    assert last_h1.label_available_ts_utc is None


def test_triple_barrier_tp_sl_and_ambiguous_adverse() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    d = date(2025, 1, 6)
    base = datetime(2025, 1, 6, 14, 30, tzinfo=UTC)
    bars = [
        _bar(inst, base, "100", "101", "99", "100", trading_date=d),
        # Entry at 100; bar[1] hits neither TP (+5%) nor SL (-3%)
        _bar(inst, base + timedelta(minutes=5), "100", "102", "99", "101", trading_date=d),
        # bar[2] hits BOTH TP (high=106 >= 105) and SL (low=96 <= 97) -> conservative SL (-1) & AMBIGUOUS_BARRIER
        _bar(inst, base + timedelta(minutes=10), "101", "106", "96", "103", trading_date=d),
        _bar(inst, base + timedelta(minutes=15), "103", "104", "102", "103", trading_date=d),
    ]
    cfg = LabelConfig(
        config_id="tb-1",
        config_version="1.0",
        method="TRIPLE_BARRIER",
        horizons_bars=(3,),
        take_profit_bps=Decimal("500"),  # +5%
        stop_loss_bps=Decimal("300"),    # -3%
    )
    labels = LabelEngine(config=cfg, registry=reg).generate(bars)
    r0 = labels[0]
    assert r0.completion_status == "AMBIGUOUS_BARRIER"
    assert r0.direction == -1
    assert r0.bars_to_exit == 2
    assert r0.gross_return == Decimal("-0.03")


def test_session_boundary_and_missing_bar_gap_mark_incomplete() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    d1 = date(2025, 1, 6)
    d2 = date(2025, 1, 7)
    b0 = _bar(inst, datetime(2025, 1, 6, 20, 50, tzinfo=UTC), "100", "101", "99", "100", trading_date=d1)
    b1 = _bar(inst, datetime(2025, 1, 6, 20, 55, tzinfo=UTC), "100", "101", "99", "100", trading_date=d1)
    # Next bar is on next trading day -> INCOMPLETE_SESSION_BOUNDARY for horizon=2 from b0
    b2 = _bar(inst, datetime(2025, 1, 7, 14, 30, tzinfo=UTC), "102", "103", "101", "102", trading_date=d2)
    # Gap on same trading day (10 minutes instead of 5 minutes) -> MISSING_BAR_GAP
    b3 = _bar(inst, datetime(2025, 1, 7, 14, 45, tzinfo=UTC), "103", "104", "102", "103", trading_date=d2)

    cfg = LabelConfig(config_id="gap", config_version="1.0", method="FIXED_HORIZON", horizons_bars=(2,))
    labels = LabelEngine(config=cfg, registry=reg).generate([b0, b1, b2, b3])
    by_ts = {r.decision_ts_utc: r for r in labels}
    assert by_ts[b0.timestamp_end_utc].completion_status == "INCOMPLETE_SESSION_BOUNDARY"
    assert by_ts[b1.timestamp_end_utc].completion_status == "INCOMPLETE_SESSION_BOUNDARY"


def test_parquet_round_trip_and_deterministic_replay(tmp_path: Path) -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    bars = _make_bars(inst, n=12)
    cfg = LabelConfig(config_id="rt", config_version="1.0", method="FIXED_HORIZON", horizons_bars=(1, 3))
    eng = LabelEngine(config=cfg, registry=reg)
    l1 = eng.generate(bars)
    l2 = eng.generate(bars)
    assert l1 == l2

    pq_path = str(tmp_path / "labels.parquet")
    digest = write_labels_parquet(l1, pq_path)
    assert len(digest) == 64
    loaded = read_labels_parquet(pq_path)
    assert len(loaded) == len(l1)
    assert loaded[0].decision_ts_utc == l1[0].decision_ts_utc
    assert l1[0].gross_return is not None
    assert loaded[0].gross_return == l1[0].gross_return.quantize(Decimal("1e-12")).normalize()
    assert loaded[-1].completion_status == l1[-1].completion_status


def test_purged_embargo_split_and_leakage_detection() -> None:
    reg = InstrumentRegistry(":memory:")
    inst = reg.register(_make_equity())
    bars = _make_bars(inst, n=30)
    cfg = LabelConfig(config_id="split", config_version="1.0", method="FIXED_HORIZON", horizons_bars=(5,))
    labels = [r for r in LabelEngine(config=cfg, registry=reg).generate(bars) if r.completion_status == "COMPLETE"]

    test_start = labels[10].decision_ts_utc
    test_end = labels[15].decision_ts_utc
    split = purged_embargo_split(
        labels,
        test_start_utc=test_start,
        test_end_utc=test_end,
        embargo_delta=timedelta(minutes=15),
    )
    assert split.purged_count > 0
    assert split.embargoed_count > 0
    validate_no_leakage(split.train, split.test, embargo_delta=timedelta(minutes=15))

    # Deliberately inject overlapping train record -> LeakageError
    overlapping = next(r for r in labels if r.decision_ts_utc < test_start and (r.label_available_ts_utc or r.decision_ts_utc) >= test_start)
    with pytest.raises(LeakageError):
        validate_no_leakage([overlapping], split.test)

    # Deliberately inject future feature_cutoff -> LeakageError
    bad_rec = LabelRecord(
        **{
            **labels[0].__dict__,
            "feature_cutoff_utc": labels[0].decision_ts_utc + timedelta(seconds=1),
        }
    )
    with pytest.raises(LeakageError):
        validate_no_leakage([bad_rec], [])
