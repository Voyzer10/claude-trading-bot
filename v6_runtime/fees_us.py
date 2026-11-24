"""US equity fees for V6 paper / backtest fills (owner decision 24 Nov 2026: correct SELL-side SEC Section 31 + FINRA
TAF model with the TAF cap; broker commission from verified pricing only).

Per FILL (Module E ME-5 passes the fill's own side and time):
  BUY fill   commission only (no SEC fee, no TAF).
  SELL fill  commission + SEC Section 31 fee + FINRA TAF, each computed independently:
             SEC = principal (price x qty x multiplier) x rate_per_million / 1,000,000, rounded UP to the cent;
             TAF = min(qty x TAF rate per share, TAF cap per trade), rounded UP to the cent.
  A long position pays SEC / TAF on its exit; a short position pays them on its entry (the short sale).
Rounding: "rounded up to the nearest penny" per fee is Alpaca's published pass-through convention (Alpaca support,
"Regulatory Fees"); applied per fill here.

Rates are DATED. Each period is in force from its start until the next period starts (that is how the SEC / FINRA
rates work: a rate stays in force until a new advisory / schedule replaces it). A fill dated before the first period
has no rate and raises `FeeRateUnavailable` (fail closed). `RATES_VERIFIED_ON` records when the table was last checked
against the official sources; readiness blocks the US book once that check is older than `REVERIFY_AFTER_DAYS`, so a
new Section 31 advisory cannot be missed silently.

NOT MODELLED (reported, not hidden): the Consolidated Audit Trail (CAT) fee that Alpaca passes through on buys and
sells: its per-share rate is not verified here. Stock borrow / financing costs for shorts: not modelled (positions are
flattened before every close, and Alpaca states no borrow fee for easy-to-borrow shorts held overnight since
1 Oct 2025); see v6_runtime/README.md.
"""
from __future__ import annotations

import decimal
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from scanner_v6.exit.execution_config import FeeSchedule
from scanner_v6.exit.stop_loss import BUY, SELL

NY = ZoneInfo("America/New_York")
CENT = Decimal("0.01")
MODEL = "us_equity_sell_side_v1"


class FeeRateUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class SecPeriod:
    start: date
    rate_per_million: Decimal
    source: str


@dataclass(frozen=True)
class TafPeriod:
    start: date
    per_share: Decimal
    max_per_trade: Decimal
    source: str


SEC_SOURCE_2026 = ("SEC Fee Rate Advisory 2026-2 (https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2): "
                   "$20.60 per million effective 2026-04-04; $0.00 per million for charge dates through 2026-04-03")
TAF_SOURCE = ("FINRA SR-FINRA-2024-019 fee adjustment schedule "
              "(https://www.finra.org/rules-guidance/rule-filings/sr-finra-2024-019/fee-adjustment-schedule)")

# Verified 24 Nov 2026 against the official sources above. Each period runs until the next one starts.
SEC_PERIODS: Tuple[SecPeriod, ...] = (
    SecPeriod(date(2026, 1, 1), Decimal("0.00"), SEC_SOURCE_2026),
    SecPeriod(date(2026, 4, 4), Decimal("20.60"), SEC_SOURCE_2026),
)
TAF_PERIODS: Tuple[TafPeriod, ...] = (
    TafPeriod(date(2026, 1, 1), Decimal("0.000195"), Decimal("9.79"), TAF_SOURCE),
    TafPeriod(date(2027, 1, 1), Decimal("0.000232"), Decimal("11.61"), TAF_SOURCE),
)
# The date the table was last checked against the official sources. A new Section 31 advisory can change the rate at
# any time: readiness blocks once this check is older than REVERIFY_AFTER_DAYS.
RATES_VERIFIED_ON = date(2026, 11, 24)
REVERIFY_AFTER_DAYS = 120

COMMISSION_SOURCE = ("Alpaca support, 'Commission & Clearing Fees' (https://alpaca.markets/support/commission-clearing-"
                     "fees): no commission for self-directed accounts trading US-listed securities through the API")


def _up(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=decimal.ROUND_UP)


def _trade_date(at: Any) -> date:
    if isinstance(at, datetime):
        if at.tzinfo is None:
            raise FeeRateUnavailable("fee time %r has no time zone" % (at,))
        return at.astimezone(NY).date()
    if isinstance(at, date):
        return at
    raise FeeRateUnavailable("a fill time is required to pick the dated fee rates (got %r)" % (at,))


def _period(periods, d: date):
    cur = None
    for p in periods:
        if p.start <= d:
            cur = p
    return cur


@dataclass(frozen=True)
class UsEquityFeeSchedule(FeeSchedule):
    commission_per_order: Decimal
    commission_source: str
    source: str = MODEL
    verified_on: date = RATES_VERIFIED_ON
    side_aware: bool = True

    def __post_init__(self) -> None:
        c = Decimal(str(self.commission_per_order))
        if not c.is_finite() or c < 0:
            raise ValueError("commission_per_order must be a non-negative number")
        object.__setattr__(self, "commission_per_order", c)
        if not isinstance(self.commission_source, str) or not self.commission_source.strip():
            raise ValueError("commission_source must name the verified pricing source")

    def rates(self, at: Any) -> Tuple[SecPeriod, TafPeriod]:
        d = _trade_date(at)
        sec, taf = _period(SEC_PERIODS, d), _period(TAF_PERIODS, d)
        if sec is None or taf is None:
            raise FeeRateUnavailable("no verified SEC / TAF rate for %s" % d)
        return sec, taf

    def components(self, price: Decimal, qty: Decimal, multiplier: Decimal, *, fill_side: Optional[str],
                   at: Any) -> Dict[str, Decimal]:
        if qty <= 0:
            raise ValueError("a fee is computed for a positive quantity only")
        if fill_side not in (BUY, SELL):
            raise FeeRateUnavailable("the US equity fee model needs the fill side (BUY / SELL), got %r" % (fill_side,))
        sec_p, taf_p = self.rates(at)
        out = {"commission": self.commission_per_order, "sec_fee": Decimal("0.00"), "finra_taf": Decimal("0.00")}
        if fill_side == SELL:
            out["sec_fee"] = _up(Decimal(price) * qty * multiplier * sec_p.rate_per_million / Decimal(1_000_000))
            out["finra_taf"] = _up(min(qty * taf_p.per_share, taf_p.max_per_trade))
        return out

    def fee(self, price: Decimal, qty: Decimal, multiplier: Decimal, *, fill_side: Optional[str] = None,
            at: Any = None) -> Decimal:
        return sum(self.components(price, qty, multiplier, fill_side=fill_side, at=at).values(), Decimal(0))

    def describe(self) -> Dict[str, Any]:
        return {"model": MODEL, "commission_per_order": str(self.commission_per_order),
                "commission_source": self.commission_source, "rates_verified_on": self.verified_on.isoformat(),
                "sec_periods": [{"from": p.start.isoformat(), "rate_per_million": str(p.rate_per_million)}
                                for p in SEC_PERIODS],
                "taf_periods": [{"from": p.start.isoformat(), "per_share": str(p.per_share),
                                 "max_per_trade": str(p.max_per_trade)} for p in TAF_PERIODS],
                "rounding": "each component rounded UP to the cent, per fill",
                "not_modelled": ["CAT fee (rate not verified)", "short borrow / financing costs"]}


def from_config(value: Any) -> UsEquityFeeSchedule:
    """`{"model": "us_equity_sell_side_v1", "commission_per_order": "0", "commission_source": "..."}`."""
    if not isinstance(value, dict) or value.get("model") != MODEL:
        raise ValueError("fee_schedule.model must be %r" % MODEL)
    extra = set(value) - {"model", "commission_per_order", "commission_source"}
    if extra:
        raise ValueError("unknown fee_schedule keys: %s" % ", ".join(sorted(extra)))
    if value.get("commission_per_order") is None:
        raise ValueError("fee_schedule.commission_per_order is required (verified pricing, never assumed)")
    return UsEquityFeeSchedule(value["commission_per_order"], value.get("commission_source") or "")


def reverify_due(today: date, verified_on: date = RATES_VERIFIED_ON) -> Optional[str]:
    """A readiness blocker when the dated rate table was last checked too long ago (else None)."""
    if (today - verified_on).days > REVERIFY_AFTER_DAYS:
        return ("US fee rates (SEC Section 31 / FINRA TAF) last verified %s, more than %d days ago: re-verify"
                % (verified_on, REVERIFY_AFTER_DAYS))
    return None
