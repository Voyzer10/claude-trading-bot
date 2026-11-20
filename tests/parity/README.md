# Parity replay (not in CI: needs the long broker history from research_data.py)

Replays the LIVE paper pipeline (`paper.setup_decision` -> `cmd_buy` -> `check_position` / `close_position`) over
historical 5-minute candles for two code versions and lists every difference in decisions, entries, SL / TP, sizing,
exits, P&L, cash and the order journal.

    git worktree add ../base_wt <base commit>
    PARITY_ROWS=3000 python tests/parity/prep.py ../base_wt <long data dir> data.pkl
    python tests/parity/harness.py ../base_wt data.pkl default base_default.json
    python tests/parity/harness.py . data.pkl default new_default.json      # and: risk_on
    python tests/parity/compare.py                                            # in the folder with the four files
