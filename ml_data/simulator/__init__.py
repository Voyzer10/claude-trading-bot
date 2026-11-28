"""Phase 2A — Deterministic, Intraday-Only Execution Simulator."""
from __future__ import annotations

from .config import CostProfile, SimulationConfig
from .costs import CostBreakdown, TransactionCostModel
from .engine import ExecutionSimulator
from .exceptions import (
    CalendarVerificationError,
    OrderValidationError,
    SessionBoundaryError,
    SimulatorConfigError,
    SimulatorError,
)
from .fills import FillDecision, FillModel
from .models import (
    EquityPoint,
    FillEvent,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionState,
    SimulatedOrder,
    SimulationEvent,
    SimulationMetrics,
    SimulationResult,
    TimeInForce,
)
from .specs import EffectiveSpec, EffectiveSpecResolver, round_price_to_tick, round_qty_to_step

__all__ = [
    "CalendarVerificationError",
    "CostBreakdown",
    "CostProfile",
    "EffectiveSpec",
    "EffectiveSpecResolver",
    "EquityPoint",
    "ExecutionSimulator",
    "FillDecision",
    "FillEvent",
    "FillModel",
    "OrderIntent",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "OrderValidationError",
    "PositionState",
    "SessionBoundaryError",
    "SimulatedOrder",
    "SimulationConfig",
    "SimulationEvent",
    "SimulationMetrics",
    "SimulationResult",
    "SimulatorConfigError",
    "SimulatorError",
    "TimeInForce",
    "TransactionCostModel",
    "round_price_to_tick",
    "round_qty_to_step",
]
