"""The five V6 paper books (owner decisions). Each book is a separate account in its own currency, with a fresh V6
history; nothing is taken from V4. A book exists on disk only after an explicit, owner-authorised `create`.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict


@dataclass(frozen=True)
class BookSpec:
    book_id: str
    label: str
    market: str
    currency: str
    starting_budget: Decimal
    decision: str


# Owner decisions: INDIA / FNO / US / CRYPTO budgets (approved 24 Nov 2026); USFNO $2,000 (owner, 24 Nov 2026,
# replacing the earlier $1,200).
BOOKS: Dict[str, BookSpec] = {
    "INDIA": BookSpec("INDIA", "India stocks", "NSE", "INR", Decimal("100000"), "owner 2026-11-24"),
    "FNO": BookSpec("FNO", "India F&O", "NFO", "INR", Decimal("100000"), "owner 2026-11-24"),
    "US": BookSpec("US", "US Stocks", "US_EQUITY", "USD", Decimal("1000"), "owner 2026-11-24"),
    "USFNO": BookSpec("USFNO", "US F&O", "US_OPTIONS", "USD", Decimal("2000"), "owner 2026-11-24 ($2,000)"),
    "CRYPTO": BookSpec("CRYPTO", "Crypto", "CRYPTO", "USD", Decimal("1000"), "owner 2026-11-24"),
}


def spec(book_id: str) -> BookSpec:
    try:
        return BOOKS[book_id]
    except KeyError:
        raise KeyError("unknown V6 book %r (known: %s)" % (book_id, ", ".join(BOOKS))) from None
