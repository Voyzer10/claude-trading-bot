"""Scanner V6: an independent Smart Money Concepts scanner (research branch research/v6-smc-scanner).

Foundation only: models, candle handling and the no-look-ahead harness. No trading rule is implemented, nothing is
wired to the live runner or the paper broker, and V6 never places orders. See scanner_v6/README.md.
"""
from .config import PAPER_ONLY, PLACES_ORDERS, VERSION  # noqa: F401
