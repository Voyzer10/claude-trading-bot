"""Indian NIFTY/BANKNIFTY Market Data Adapter (Zerodha Kite Connect, read-only)."""
from __future__ import annotations

from .archive import ContractSelectionPolicy, OptionContractArchive
from .calendars import build_nse_fo_calendar, load_nse_fo_calendar_data
from .config import INTERVAL_MAX_DAYS, KiteClientWrapper, KiteRateLimiter, NSECalendar
from .contract_discovery import ContractDiscovery, parse_kite_nfo_symbol
from .exceptions import (
    CalendarError,
    ContractDiscoveryError,
    InstrumentMasterError,
    KiteAdapterError,
    KiteAuthError,
    KiteInputError,
    KiteRateLimitError,
)
from .historical import HistoricalCandle, HistoricalFetchResult, KiteHistoricalDataClient
from .instrument_master import InstrumentMasterDownloader, MasterSnapshot
from .live_bridge import KiteLiveBridge, NormalizedTick

__all__ = [
    "CalendarError",
    "ContractDiscovery",
    "ContractDiscoveryError",
    "ContractSelectionPolicy",
    "HistoricalCandle",
    "HistoricalFetchResult",
    "INTERVAL_MAX_DAYS",
    "InstrumentMasterDownloader",
    "InstrumentMasterError",
    "KiteAdapterError",
    "KiteAuthError",
    "KiteClientWrapper",
    "KiteHistoricalDataClient",
    "KiteInputError",
    "KiteLiveBridge",
    "KiteRateLimitError",
    "KiteRateLimiter",
    "MasterSnapshot",
    "NSECalendar",
    "NormalizedTick",
    "OptionContractArchive",
    "build_nse_fo_calendar",
    "load_nse_fo_calendar_data",
    "parse_kite_nfo_symbol",
]
