"""The budgets and limits from before 17 Nov 2026, for the tests written against them (they test the engine's logic,
not the budget; tests/test_budget.py tests the budget). Call apply(P) right after importing paper."""

OLD = {"INDIA": {"capital": 50000, "max_loss_per_trade": 500, "max_loss_per_trade_fno": 1500, "daily_loss_limit": 2500},
       "FNO": {"capital": 100000, "max_loss_per_trade": 1500, "max_loss_per_trade_fno": 1500, "daily_loss_limit": 5000},
       "US": {"capital": 50000, "max_loss_per_trade": 50, "daily_loss_limit": 150},
       "USFNO": {"capital": 50000, "max_loss_per_trade": 500, "max_loss_per_trade_fno": 500, "daily_loss_limit": 1500},
       "CRYPTO": {"capital": 1000, "max_loss_per_trade": 10, "daily_loss_limit": 30}}


def apply(P):
    for name, v in OLD.items():
        P.DEFAULT_CONFIG["accounts"][name].update(v)
    P.BUDGET_1117 = {}                              # the one-time config change: nothing to change
    P.budget_reset = lambda led, cfg: False         # the one-time ledger reset: off
