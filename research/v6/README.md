# research/v6: Scanner V6 research workspace

Research only, PAPER ONLY. Nothing here is imported by the live runner, the API or the paper broker.

| Folder | What goes in it | In git? |
|---|---|---|
| `data/` | Candle files for experiments (chart JSON `{t,o,h,l,c,v}` or row CSV) | **No** (large and re-downloadable; see `data/.gitignore`) |
| `configs/` | One file per experiment's frozen settings (JSON), written **before** the run | yes |
| `experiments/` | The scripts that run an experiment (they import `scanner_v6`, never V4) | yes |
| `reports/` | Results: one Markdown report per experiment, plus small CSV summaries | yes (no raw data dumps) |

## Workflow

1. **Declare first.** Write `configs/<date>_<name>.json` before running:
   - concept and version
   - symbols, markets, timeframe
   - data source and date range
   - the in-sample / out-of-sample split
   - cost model
   - the acceptance rule
2. **Run** `experiments/<name>.py`. It reads only `scanner_v6`, `data/` and its config, and it writes to `reports/`.
3. **Report** in `reports/<date>_<name>.md`:
   - the config used and the commit hash
   - trade counts
   - in-sample and out-of-sample results **after costs**, with standard errors
   - what failed and the limitations
4. **No tuning on the evaluation data.** Parameters are chosen on in-sample data only. Out-of-sample is looked at once, per declared rule. A rule that fails stays rejected.
5. Every detector used in an experiment must already pass its unit tests and the no-look-ahead test (`tests/scanner_v6/`).
