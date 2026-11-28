"""Leakage-safe LabelEngine supporting fixed-horizon and triple-barrier targets."""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from ..instruments import InstrumentRegistry
from ..simulator.costs import TransactionCostModel
from ..simulator.models import OrderSide
from ..simulator.specs import EffectiveSpecResolver
from ..storage.canonical_schema import CanonicalCandle
from .config import LabelConfig
from .models import LabelRecord

_BPS = Decimal("10000")


class LabelEngine:
    """Generates reproducible, leakage-safe labels from CanonicalCandle sequences."""

    def __init__(
        self,
        *,
        config: LabelConfig,
        registry: Optional[InstrumentRegistry] = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.spec_resolver = EffectiveSpecResolver(registry) if registry is not None else None
        self.cost_model = TransactionCostModel(config.cost_profile) if config.cost_profile is not None else None

    def generate(self, candles: Sequence[CanonicalCandle]) -> List[LabelRecord]:
        by_inst: Dict[str, List[CanonicalCandle]] = {}
        for c in candles:
            by_inst.setdefault(c.instrument_id, []).append(c)

        out: List[LabelRecord] = []
        for iid in sorted(by_inst):
            bars = sorted(by_inst[iid], key=lambda x: x.timestamp_start_utc)
            n = len(bars)
            for i, dec_bar in enumerate(bars):
                spec = self.spec_resolver.resolve(iid, dec_bar.timestamp_end_utc) if self.spec_resolver else None
                spec_ver = spec.spec_version_id if spec else None
                mult = spec.contract_multiplier if spec else Decimal("1")

                for h in self.config.horizons_bars:
                    rec = self._build_label(bars, i, n, h, spec_ver, mult)
                    out.append(rec)
        return out

    def _round_trip_cost_return(self, entry_px: Decimal, exit_px: Decimal, mult: Decimal) -> Decimal:
        if self.cost_model is None or entry_px <= 0:
            return Decimal("0")
        entry_side = OrderSide.BUY if self.config.side == "LONG" else OrderSide.SELL
        exit_side = OrderSide.SELL if self.config.side == "LONG" else OrderSide.BUY
        c1 = self.cost_model.compute(side=entry_side, raw_price=entry_px, quantity=Decimal("1"), multiplier=mult)
        c2 = self.cost_model.compute(side=exit_side, raw_price=exit_px, quantity=Decimal("1"), multiplier=mult)
        return (c1.total_cost + c2.total_cost) / (entry_px * mult)

    def _build_label(
        self,
        bars: Sequence[CanonicalCandle],
        i: int,
        n: int,
        horizon: int,
        spec_ver: Optional[int],
        mult: Decimal,
    ) -> LabelRecord:
        dec_bar = bars[i]
        decision_ts = dec_bar.timestamp_end_utc
        feature_cutoff = decision_ts  # strictly no feature access beyond decision bar close

        if i + horizon >= n:
            return LabelRecord(
                instrument_id=dec_bar.instrument_id,
                market=dec_bar.market,
                exchange=dec_bar.exchange,
                asset_class=dec_bar.asset_class,
                timeframe=dec_bar.timeframe,
                horizon_bars=horizon,
                label_method=self.config.method,
                config_version=self.config.config_version,
                decision_ts_utc=decision_ts,
                feature_cutoff_utc=feature_cutoff,
                earliest_executable_utc=bars[i + 1].timestamp_start_utc if i + 1 < n else None,
                label_start_ts_utc=bars[i + 1].timestamp_start_utc if i + 1 < n else None,
                label_end_ts_utc=None,
                label_available_ts_utc=None,
                gross_return=None,
                net_return=None,
                direction=None,
                mfe=None,
                mae=None,
                bars_to_exit=None,
                completion_status="INCOMPLETE_HORIZON",
                dataset_id=self.config.dataset_id or dec_bar.dataset_version,
                dataset_version=self.config.dataset_version or dec_bar.dataset_version,
                manifest_sha256=self.config.manifest_sha256,
                spec_version_id=spec_ver,
                quality_flags=dec_bar.quality_flags,
            )

        entry_bar = bars[i + 1]
        window = bars[i + 1 : i + 1 + horizon]
        entry_px = entry_bar.open
        earliest_exec = entry_bar.timestamp_start_utc

        # Check intraday session boundary & bar continuity
        if self.config.require_same_session and dec_bar.market != "CRYPTO":
            if any(b.trading_date != dec_bar.trading_date or b.trading_session != dec_bar.trading_session for b in window):
                return LabelRecord(
                    instrument_id=dec_bar.instrument_id,
                    market=dec_bar.market,
                    exchange=dec_bar.exchange,
                    asset_class=dec_bar.asset_class,
                    timeframe=dec_bar.timeframe,
                    horizon_bars=horizon,
                    label_method=self.config.method,
                    config_version=self.config.config_version,
                    decision_ts_utc=decision_ts,
                    feature_cutoff_utc=feature_cutoff,
                    earliest_executable_utc=earliest_exec,
                    label_start_ts_utc=earliest_exec,
                    label_end_ts_utc=None,
                    label_available_ts_utc=None,
                    gross_return=None,
                    net_return=None,
                    direction=None,
                    mfe=None,
                    mae=None,
                    bars_to_exit=None,
                    completion_status="INCOMPLETE_SESSION_BOUNDARY",
                    dataset_id=self.config.dataset_id or dec_bar.dataset_version,
                    dataset_version=self.config.dataset_version or dec_bar.dataset_version,
                    manifest_sha256=self.config.manifest_sha256,
                    spec_version_id=spec_ver,
                    quality_flags=dec_bar.quality_flags,
                )

        # Check for missing bar gaps inside forward window
        for a, b in zip(window, window[1:]):
            if b.timestamp_start_utc != a.timestamp_end_utc:
                return LabelRecord(
                    instrument_id=dec_bar.instrument_id,
                    market=dec_bar.market,
                    exchange=dec_bar.exchange,
                    asset_class=dec_bar.asset_class,
                    timeframe=dec_bar.timeframe,
                    horizon_bars=horizon,
                    label_method=self.config.method,
                    config_version=self.config.config_version,
                    decision_ts_utc=decision_ts,
                    feature_cutoff_utc=feature_cutoff,
                    earliest_executable_utc=earliest_exec,
                    label_start_ts_utc=earliest_exec,
                    label_end_ts_utc=None,
                    label_available_ts_utc=None,
                    gross_return=None,
                    net_return=None,
                    direction=None,
                    mfe=None,
                    mae=None,
                    bars_to_exit=None,
                    completion_status="MISSING_BAR_GAP",
                    dataset_id=self.config.dataset_id or dec_bar.dataset_version,
                    dataset_version=self.config.dataset_version or dec_bar.dataset_version,
                    manifest_sha256=self.config.manifest_sha256,
                    spec_version_id=spec_ver,
                    quality_flags=tuple(dict.fromkeys(list(dec_bar.quality_flags) + ["missing_bar_gap_in_horizon"])),
                )

        is_long = self.config.side == "LONG"
        max_hi = max(b.high for b in window)
        min_lo = min(b.low for b in window)
        if is_long:
            mfe = (max_hi - entry_px) / entry_px
            mae = (min_lo - entry_px) / entry_px
        else:
            mfe = (entry_px - min_lo) / entry_px
            mae = (entry_px - max_hi) / entry_px

        exit_bar = window[-1]
        exit_px = exit_bar.close
        bars_used = horizon
        status = "COMPLETE"

        if self.config.method == "TRIPLE_BARRIER":
            assert self.config.take_profit_bps is not None and self.config.stop_loss_bps is not None
            tp_frac = self.config.take_profit_bps / _BPS
            sl_frac = self.config.stop_loss_bps / _BPS
            tp_px = entry_px * (Decimal("1") + tp_frac) if is_long else entry_px * (Decimal("1") - tp_frac)
            sl_px = entry_px * (Decimal("1") - sl_frac) if is_long else entry_px * (Decimal("1") + sl_frac)

            for k_idx, wb in enumerate(window, start=1):
                tp_hit = (wb.high >= tp_px) if is_long else (wb.low <= tp_px)
                sl_hit = (wb.low <= sl_px) if is_long else (wb.high >= sl_px)
                if tp_hit and sl_hit:
                    # Conservative adverse rule: assume SL hit when both touched in same candle
                    exit_bar = wb
                    exit_px = sl_px
                    bars_used = k_idx
                    status = "AMBIGUOUS_BARRIER"
                    break
                if sl_hit:
                    exit_bar = wb
                    exit_px = sl_px
                    bars_used = k_idx
                    break
                if tp_hit:
                    exit_bar = wb
                    exit_px = tp_px
                    bars_used = k_idx
                    break

        gross_ret = ((exit_px - entry_px) / entry_px) if is_long else ((entry_px - exit_px) / entry_px)
        cost_ret = self._round_trip_cost_return(entry_px, exit_px, mult)
        net_ret = gross_ret - cost_ret

        thresh = self.config.neutral_threshold_bps / _BPS
        if net_ret > thresh:
            direction = 1
        elif net_ret < -thresh:
            direction = -1
        else:
            direction = 0

        label_end = exit_bar.timestamp_end_utc
        return LabelRecord(
            instrument_id=dec_bar.instrument_id,
            market=dec_bar.market,
            exchange=dec_bar.exchange,
            asset_class=dec_bar.asset_class,
            timeframe=dec_bar.timeframe,
            horizon_bars=horizon,
            label_method=self.config.method,
            config_version=self.config.config_version,
            decision_ts_utc=decision_ts,
            feature_cutoff_utc=feature_cutoff,
            earliest_executable_utc=earliest_exec,
            label_start_ts_utc=earliest_exec,
            label_end_ts_utc=label_end,
            label_available_ts_utc=label_end,
            gross_return=gross_ret,
            net_return=net_ret,
            direction=direction,
            mfe=mfe,
            mae=mae,
            bars_to_exit=bars_used,
            completion_status=status,
            dataset_id=self.config.dataset_id or dec_bar.dataset_version,
            dataset_version=self.config.dataset_version or dec_bar.dataset_version,
            manifest_sha256=self.config.manifest_sha256,
            spec_version_id=spec_ver,
            quality_flags=dec_bar.quality_flags,
        )
