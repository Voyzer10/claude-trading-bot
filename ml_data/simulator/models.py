"""Order lifecycle, fill, position, equity curve, and simulation result data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class TimeInForce(str, Enum):
    DAY = "DAY"
    IOC = "IOC"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


@dataclass
class OrderIntent:
    """Strategy/signal order request submitted at decision_ts_utc."""

    order_id: str
    instrument_id: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    decision_ts_utc: datetime
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    expiry_at_utc: Optional[datetime] = None


@dataclass
class SimulatedOrder:
    """Mutable order tracking full lifecycle state."""

    order_id: str
    instrument_id: str
    side: OrderSide
    order_type: OrderType
    requested_quantity: Decimal
    remaining_quantity: Decimal
    filled_quantity: Decimal
    decision_ts_utc: datetime
    earliest_executable_utc: datetime
    status: OrderStatus = OrderStatus.CREATED
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    expiry_at_utc: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    spec_version_id: Optional[int] = None


@dataclass(frozen=True)
class FillEvent:
    fill_id: str
    order_id: str
    instrument_id: str
    ts_utc: datetime
    side: OrderSide
    quantity: Decimal
    raw_price: Decimal
    net_fill_price: Decimal
    slippage_cost: Decimal
    spread_cost: Decimal
    fee_cost: Decimal
    tax_cost: Decimal
    total_cost: Decimal
    execution_basis: str
    is_ambiguous: bool = False
    spec_version_id: Optional[int] = None


@dataclass
class PositionState:
    instrument_id: str
    quantity: Decimal = Decimal("0")          # signed: >0 long, <0 short
    avg_entry_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_costs: Decimal = Decimal("0")
    active_stop_loss: Optional[Decimal] = None
    active_take_profit: Optional[Decimal] = None


@dataclass(frozen=True)
class EquityPoint:
    ts_utc: datetime
    cash: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    gross_exposure: Decimal
    drawdown: Decimal


@dataclass(frozen=True)
class SimulationEvent:
    ts_utc: datetime
    event_type: str
    instrument_id: str
    details: Dict[str, Any]


@dataclass(frozen=True)
class SimulationMetrics:
    initial_cash: Decimal
    final_equity: Decimal
    gross_pnl: Decimal
    total_costs: Decimal
    net_pnl: Decimal
    max_drawdown: Decimal
    total_orders: int
    filled_orders: int
    partial_fills: int
    rejected_orders: int
    expired_orders: int
    cancelled_orders: int
    ambiguous_fills: int


@dataclass
class SimulationResult:
    config_id: str
    execution_mode: str
    dataset_id: Optional[str]
    dataset_version: Optional[str]
    manifest_sha256: Optional[str]
    metrics: SimulationMetrics
    orders: List[SimulatedOrder] = field(default_factory=list)
    fills: List[FillEvent] = field(default_factory=list)
    positions: Dict[str, PositionState] = field(default_factory=dict)
    equity_curve: List[EquityPoint] = field(default_factory=list)
    event_log: List[SimulationEvent] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
