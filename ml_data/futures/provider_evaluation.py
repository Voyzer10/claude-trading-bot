"""Structured evaluation of US equity-index futures market data providers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class FuturesProviderEvaluation:
    provider_id: str
    name: str
    verification_date: str
    primary_dataset: str
    cme_globex_coverage: str
    historical_depth: str
    schemas_supported: Tuple[str, ...]
    continuous_symbology: str
    oi_availability: str
    pricing_model: str
    licensing_notes: str
    selected_as_initial: bool
    selection_reason: str


PROVIDER_EVALUATIONS: Dict[str, FuturesProviderEvaluation] = {
    "databento": FuturesProviderEvaluation(
        provider_id="databento",
        name="Databento",
        verification_date="2026-11-28",
        primary_dataset="GLBX.MDP3",
        cme_globex_coverage="Full CME Globex MDP 3.0 equity-index futures (ES, MES, NQ, MNQ, YM, MYM, RTY, M2K)",
        historical_depth="Multi-year historical depth (GLBX.MDP3 from 2010+ depending on schema)",
        schemas_supported=("definition", "ohlcv-1s", "ohlcv-1m", "ohlcv-1h", "trades", "mbp-1", "statistics", "status"),
        continuous_symbology="Supports continuous symbology (e.g. ES.c.0 / ES.v.0 / ES.n.0); raw unadjusted prices by default",
        oi_availability="Provided via statistics schema (daily exchange-published open interest)",
        pricing_model="Usage-based pay-as-you-go + monthly plans; non-billable metadata endpoints available",
        licensing_notes=(
            "API access does not grant CME commercial redistribution or unverified non-display exchange fee waivers; "
            "internal research requires verifying Databento + CME non-display/internal-use terms."
        ),
        selected_as_initial=True,
        selection_reason=(
            "Best balance of clean REST/streaming API, full CME Globex definition & continuous symbology, "
            "1m/1s/trade/BBO/statistics schemas, and usage-based research cost."
        ),
    ),
    "cme_datamine": FuturesProviderEvaluation(
        provider_id="cme_datamine",
        name="CME DataMine",
        verification_date="2026-11-28",
        primary_dataset="CME_GLOBEX_MDP3",
        cme_globex_coverage="Authoritative CME Group historical archive",
        historical_depth="Deep multi-decade historical archive",
        schemas_supported=("BBO", "Trades", "Settlement", "EOD/OI"),
        continuous_symbology="Raw dated contracts; continuous series must be constructed locally",
        oi_availability="Authoritative daily settlement & OI",
        pricing_model="Per-dataset / enterprise licensing, higher minimum cost for intraday research",
        licensing_notes="Direct CME DataMine historical license required; no real-time stream included.",
        selected_as_initial=False,
        selection_reason="Higher upfront cost and batch-only workflow compared to Databento for initial Phase 1.",
    ),
    "dxfeed": FuturesProviderEvaluation(
        provider_id="dxfeed",
        name="dxFeed",
        verification_date="2026-11-28",
        primary_dataset="CME",
        cme_globex_coverage="CME Globex real-time and historical feeds",
        historical_depth="Multi-year intraday depending on contract",
        schemas_supported=("Candle", "Trade", "Quote", "Summary"),
        continuous_symbology="Provider-specific continuous symbols",
        oi_availability="Via Summary events",
        pricing_model="Enterprise/custom quote subscription",
        licensing_notes="Requires direct commercial/research agreement and CME exchange reporting.",
        selected_as_initial=False,
        selection_reason="Enterprise onboarding overhead makes Databento preferable for initial Phase 1.",
    ),
}
