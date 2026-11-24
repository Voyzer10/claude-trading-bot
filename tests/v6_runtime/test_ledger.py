"""V6 book ledger: owner-authorised creation, never reset, reconciliation, duplicates, atomic state, path guard."""
import json
import os
from decimal import Decimal

import pytest

import _fx  # noqa: F401  (sys.path)
from v6_runtime import books
from v6_runtime.ledger import BookExists, BookLedger, BookMissing, DuplicateExecution, LedgerCorrupt, LedgerError
from v6_runtime.paths import DataRoot, PathGuardError, check_root

TRADE = {"setup_id": "S1", "instrument": "AAA", "entry_fill": "100.01", "quantity": "5", "entry_fee": "0.05",
         "entry_slippage": "0.05", "contract_multiplier": "1"}


def test_five_books_and_owner_budgets():
    b = {k: (v.currency, v.starting_budget) for k, v in books.BOOKS.items()}
    assert b == {"INDIA": ("INR", Decimal("100000")), "FNO": ("INR", Decimal("100000")),
                 "US": ("USD", Decimal("1000")), "USFNO": ("USD", Decimal("2000")),
                 "CRYPTO": ("USD", Decimal("1000"))}


def test_create_requires_owner_and_never_resets(tmp_path):
    root = DataRoot(str(tmp_path))
    with pytest.raises(LedgerError):
        BookLedger.create(root, "US", owner_authorised=False, created_by="t")
    with pytest.raises(LedgerError):
        BookLedger.create(root, "US", owner_authorised="yes", created_by="t")
    assert not BookLedger.exists(root, "US")
    with pytest.raises(BookMissing):
        BookLedger.load(root, "US")
    led = BookLedger.create(root, "US", owner_authorised=True, created_by="t")
    s = led.summary()
    assert (s["cash"], s["equity"], s["realized_pnl"], s["open_positions"], s["closed_trades"]) == \
        ("1000", "1000", "0", 0, 0)
    assert s["win_rate_pct"] is None                                       # no trades -> no win rate, not 0
    led.book_entry(dict(TRADE))
    with pytest.raises(BookExists):
        BookLedger.create(root, "US", owner_authorised=True, created_by="t")
    assert BookLedger.load(root, "US").open_trade["setup_id"] == "S1"     # trades survive


def test_unknown_book_refused(tmp_path):
    with pytest.raises(Exception):
        BookLedger.create(DataRoot(str(tmp_path)), "V4", owner_authorised=True, created_by="t")


def test_entry_exit_cash_model_and_reconcile(tmp_path):
    root = DataRoot(str(tmp_path))
    led = BookLedger.create(root, "US", owner_authorised=True, created_by="t")
    led.book_entry(dict(TRADE))
    assert led.cash() == Decimal("999.95")
    with pytest.raises(DuplicateExecution):
        led.book_entry(dict(TRADE))
    with pytest.raises(LedgerError):
        led.book_entry(dict(TRADE, setup_id="S2"))                         # one open position per book
    with pytest.raises(LedgerCorrupt):                                     # E realized must equal gross - fees
        led.book_exit("S1", {"status": "TARGET_HIT", "exit_fill": "102", "gross_pnl": "9.95", "exit_fee": "0.05",
                             "realized_pnl": "9.95"})
    led.book_exit("S1", {"status": "TARGET_HIT", "exit_fill": "102", "gross_pnl": "9.95", "exit_fee": "0.05",
                         "realized_pnl": "9.85", "exit_slippage": "0"})
    s = BookLedger.load(root, "US").summary()
    assert (s["cash"], s["realized_pnl"], s["fees_total"], s["closed_trades"], s["win_rate_pct"]) == \
        ("1009.85", "9.85", "0.10", 1, "100.00")
    with pytest.raises(DuplicateExecution):
        led.record_rejection("S1", "AAA", "X", "dup")


def test_tampered_ledger_does_not_load(tmp_path):
    root = DataRoot(str(tmp_path))
    led = BookLedger.create(root, "US", owner_authorised=True, created_by="t")
    led.book_entry(dict(TRADE))
    p = root.path("books", "US.json")
    d = json.load(open(p))
    d["cash"] = "5000"
    json.dump(d, open(p, "w"))
    with pytest.raises(LedgerCorrupt):
        BookLedger.load(root, "US")
    d["cash"], d["booked_setup_ids"] = "999.95", ["S1", "S1"]
    json.dump(d, open(p, "w"))
    with pytest.raises(LedgerCorrupt):
        BookLedger.load(root, "US")


def test_mtm_missing_is_unscorable_not_zero(tmp_path):
    root = DataRoot(str(tmp_path))
    led = BookLedger.create(root, "US", owner_authorised=True, created_by="t")
    led.book_entry(dict(TRADE))
    s = led.summary(None)
    assert s["mtm_status"] != "OK" and s["equity"] is None and s["unrealized_pnl"] is None


def test_atomic_write_leaves_no_temp_and_event_log(tmp_path):
    root = DataRoot(str(tmp_path))
    led = BookLedger.create(root, "US", owner_authorised=True, created_by="t")
    led.book_entry(dict(TRADE))
    names = os.listdir(root.path("books"))
    assert sorted(names) == ["US.events.jsonl", "US.json"], names
    ev = root.read_jsonl("books", "US.events.jsonl")
    assert [e["event"] for e in ev] == ["CREATED", "ENTRY"] and [e["seq"] for e in ev] == [1, 2]
    assert all(e["scanner_name"] == "V6 SMC Scanner" for e in ev)


@pytest.mark.parametrize("bad", ["/opt/trader", "/opt/trader/trader", "/etc/trader", "/home/x/trader/paper",
                                 "/srv/trader/live", "/x/trader.env"])
def test_path_guard_refuses_v4_locations(bad):
    with pytest.raises(PathGuardError):
        check_root(bad)


def test_path_guard_escape(tmp_path):
    root = DataRoot(str(tmp_path))
    with pytest.raises(PathGuardError):
        root.path("..", "..", "etc", "passwd")


def test_default_root():
    old = os.environ.pop("V6_DATA_ROOT", None)
    try:
        assert DataRoot().root == "/var/lib/trader-v6"
    finally:
        if old is not None:
            os.environ["V6_DATA_ROOT"] = old
