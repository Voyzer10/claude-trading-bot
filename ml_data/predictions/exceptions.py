"""Exceptions for the Phase 0 Step 3 Prediction Contract. Every error carries a stable machine-readable code."""
from __future__ import annotations

from enum import Enum
from typing import Union


class PredictionContractError(ValueError):
    """A prediction, prediction-state record or nested structure violates the Prediction Contract."""

    def __init__(self, code: Union[Enum, str], message: str) -> None:
        self.code = code.value if isinstance(code, Enum) else str(code)
        super().__init__(f"[{self.code}] {message}")


class RiskAssessmentContractError(PredictionContractError):
    """A risk-assessment record, limit check or override violates the risk-assessment contract boundary."""
