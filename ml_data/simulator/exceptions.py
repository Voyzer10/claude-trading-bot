"""Exceptions for the Phase 2A Execution Simulator."""
from __future__ import annotations


class SimulatorError(RuntimeError):
    """Base error for execution simulation."""


class SimulatorConfigError(SimulatorError):
    """Raised on invalid simulation or cost-profile configuration."""


class OrderValidationError(SimulatorError):
    """Raised when an order violates instrument constraints, quantity steps, or timing."""


class CalendarVerificationError(SimulatorError):
    """Raised when simulation requires a verified calendar for an unverified year."""


class SessionBoundaryError(SimulatorError):
    """Raised when an operation violates intraday session or expiry boundaries."""
