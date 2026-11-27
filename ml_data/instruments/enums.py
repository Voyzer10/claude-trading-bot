"""Validated enumerations for the Universal Instrument Schema."""
from __future__ import annotations

from enum import Enum


class Market(str, Enum):
    US = "US"
    IN = "IN"
    CRYPTO = "CRYPTO"


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    INDEX = "INDEX"
    OPTION = "OPTION"
    FUTURE = "FUTURE"
    CRYPTO_SPOT = "CRYPTO_SPOT"
    CRYPTO_FUTURE = "CRYPTO_FUTURE"
    CRYPTO_PERPETUAL = "CRYPTO_PERPETUAL"


class Segment(str, Enum):
    US_EQUITY = "US_EQUITY"
    US_INDEX = "US_INDEX"
    US_OPTIONS = "US_OPTIONS"
    US_FUTURES = "US_FUTURES"
    IN_INDEX = "IN_INDEX"
    IN_INDEX_FUTURES = "IN_INDEX_FUTURES"
    IN_INDEX_OPTIONS = "IN_INDEX_OPTIONS"
    CRYPTO_SPOT = "CRYPTO_SPOT"
    CRYPTO_FUTURES = "CRYPTO_FUTURES"
    CRYPTO_PERPETUALS = "CRYPTO_PERPETUALS"


class OptionRight(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class InstrumentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    HALTED = "HALTED"
    EXPIRED = "EXPIRED"
    DELISTED = "DELISTED"
    PRELISTING = "PRELISTING"
    UNKNOWN = "UNKNOWN"


class SettlementType(str, Enum):
    CASH = "CASH"
    PHYSICAL = "PHYSICAL"
    CRYPTO = "CRYPTO"
    UNKNOWN = "UNKNOWN"


class MarginType(str, Enum):
    LINEAR = "LINEAR"
    INVERSE = "INVERSE"
    STANDARD = "STANDARD"
    PORTFOLIO = "PORTFOLIO"
    UNKNOWN = "UNKNOWN"


class ContractType(str, Enum):
    SPOT = "SPOT"
    EQUITY = "EQUITY"
    ETF = "ETF"
    INDEX = "INDEX"
    OPTION = "OPTION"
    DATED_FUTURE = "DATED_FUTURE"
    PERPETUAL = "PERPETUAL"
    UNKNOWN = "UNKNOWN"
