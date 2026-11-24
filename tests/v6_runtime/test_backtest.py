"""V6 historical backtesting: data validation, chronological / no-look-ahead processing, strategy sequence, entries
and exits, fees / spread / slippage, sizing and risk, metrics, equity curve, ledger isolation, restart, reproducibility
and configuration errors. Data: the SYNTHETIC fixture tests/v6_runtime/fixtures/synth_nyse_5m.csv (engine tests
only; it is not market data and its results are not performance)."""
import copy
import csv
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import pytest

import _fx
from _fx import T
from scanner_v6.exit import execution as E
from v6_runtime.backtest import ENGINE_VERSION, config as bcfg, metrics
from v6_runtime.backtest.__main__ import fetch_to_csv, main as cli
from v6_runtime.backtest.dataset import DatasetError, load_dataset
from v6_runtime.backtest.engine import COMPLETE, RUNNING, BacktestError, BacktestRun, get_run, list_runs
from v6_runtime.data.alpaca import Bar
from v6_runtime.ledger import BACKTEST, BookLedger, LedgerCorrupt
from v6_runtime.paths import DataRoot

FX = os.path.join(_fx.HERE, "fixtures")
CSV = os.path.join(FX, "synth_nyse_5m.csv")
CFG_FILE = os.path.join(FX, "backtest_us_synthetic.json")
DAY = date(2026, 11, 23)
UTC = timezone.utc
STAGES = ["CHOCH_DETECTED", "BOS_CONFIRMED", "SWEEP_DETECTED", "PATTERN_DETECTED", "CONFIRMED", "ENTERED"]


def raw_cfg(**over):
    d = json.load(open(CFG_FILE))
    for k, v in over.items():
        if k in d.get("execution", {}):
            d["execution"][k] = v
        else:
            d[k] = v
    return d


def rows():
    with open(CSV) as fh:
        return list(csv.reader(fh))


def write(tmp, name, body, source="SYNTHETIC variant"):
    p = os.path.join(str(tmp), name)
    with open(p, "w", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows(body)
    json.dump({"source": source}, open(p + ".meta.json", "w"))
    return p


def run(tmp, cfg=None, data=None, **kw):
    r = BacktestRun(DataRoot(str(tmp)), bcfg.parse(cfg or raw_cfg()), data or {"SYNTH": CSV}, DAY, DAY)
    return r, r.execute(**kw)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("base")
    r, res = run(tmp)
    return r, res


def _sess():
    return bcfg.parse(raw_cfg()).session(DAY, DAY)


# ------------------------------------------------------------------ 1 / 2 chronological, no look-ahead
def test_chronological_one_candle_at_a_time(tmp_path):
    seen = []

    def spy(i, pf):
        st = pf.streams["SYNTH"]
        seen.append((i, st.candles[-1].ts, len(st.candles)))
        assert len(st.candles) == i + 1                       # the pipeline holds exactly the candles given so far
    run(tmp_path, on_step=spy)
    assert [s[1] for s in seen] == sorted(s[1] for s in seen) and len({s[1] for s in seen}) == 77


def test_no_lookahead_prefix_and_future_mutation(tmp_path, base):
    full = base[1]
    body = rows()
    k = 62                                                   # stop after the first trade closed (58), before trade 2
    p_prefix = write(tmp_path, "prefix.csv", body[:1 + k])
    mutated = body[:1 + k] + [[r[0], "130.0", "131.0", "129.5", "130.5", "1000.0"] for r in body[1 + k:]]
    p_mut = write(tmp_path, "mut.csv", mutated)
    _, a = run(tmp_path / "a", data={"SYNTH": p_prefix})
    _, b = run(tmp_path / "b", data={"SYNTH": p_mut})
    curve_full = full["equity_curve"][:k]
    assert a["equity_curve"][:k] == curve_full == b["equity_curve"][:k]
    t_full = [t for t in full["trades"] if t["exit_index"] is not None and t["exit_index"] < k]
    assert t_full and [t for t in a["trades"] if t["status"] != "ENTERED"] == t_full
    assert [t for t in b["trades"] if t.get("exit_index") is not None and t["exit_index"] < k] == t_full


# ------------------------------------------------------------------ 3 / 4 duplicates, missing and invalid data
def test_duplicate_and_out_of_order_rows_refused(tmp_path):
    body = rows()
    dup = write(tmp_path, "dup.csv", body[:10] + [body[9]] + body[10:])
    with pytest.raises(DatasetError, match="duplicate timestamp"):
        load_dataset(dup, "SYNTH", timedelta(minutes=5), _sess(), DAY, DAY)
    ooo = write(tmp_path, "ooo.csv", body[:5] + [body[6], body[5]] + body[7:])
    with pytest.raises(DatasetError, match="out of order"):
        load_dataset(ooo, "SYNTH", timedelta(minutes=5), _sess(), DAY, DAY)


@pytest.mark.parametrize("edit,msg", [
    (lambda b: b.__setitem__(3, [b[3][0], "120.0", "119.0", "119.5", "119.8", "1"]), "invalid OHLCV"),
    (lambda b: b.__setitem__(3, [b[3][0], "x", "1", "1", "1", "1"]), "unparsable"),
    (lambda b: b.__setitem__(3, ["2026-11-23T14:40:00", "1", "1", "1", "1", "1"]), "no UTC offset"),
    (lambda b: b.__setitem__(3, ["2026-11-23T14:42:00Z", "1", "1", "1", "1", "1"]), "not on the"),
    (lambda b: b.append(["2026-11-23T21:00:00Z", "1", "1", "1", "1", "1"]), "outside every trading session"),
    (lambda b: b.__setitem__(3, [b[3][0], "1", "1", "1", "1", "-5"]), "invalid OHLCV"),
])
def test_invalid_rows_refused_with_reasons(tmp_path, edit, msg):
    body = rows()
    edit(body)
    p = write(tmp_path, "bad.csv", body)
    with pytest.raises(DatasetError, match=msg):
        load_dataset(p, "SYNTH", timedelta(minutes=5), _sess(), DAY, DAY)


def test_header_source_and_range_errors(tmp_path):
    body = rows()
    p = write(tmp_path, "hdr.csv", [["time", "o", "h", "l", "c", "v"]] + body[1:])
    with pytest.raises(DatasetError, match="header"):
        load_dataset(p, "SYNTH", timedelta(minutes=5), _sess(), DAY, DAY)
    p = os.path.join(str(tmp_path), "nosrc.csv")
    with open(p, "w") as fh:
        fh.write(open(CSV).read())
    with pytest.raises(DatasetError, match="source is not declared"):
        load_dataset(p, "SYNTH", timedelta(minutes=5), _sess(), DAY, DAY)
    with pytest.raises(DatasetError, match="no bars"):
        load_dataset(CSV, "SYNTH", timedelta(minutes=5), _sess(), date(2026, 11, 24), date(2026, 11, 24))
    with pytest.raises(DatasetError, match="declared for symbol"):
        load_dataset(CSV, "AAPL", timedelta(minutes=5), _sess(), DAY, DAY)
    with pytest.raises(DatasetError, match="does not exist"):
        load_dataset(str(tmp_path / "nope.csv"), "SYNTH", timedelta(minutes=5), _sess(), DAY, DAY)


def test_gaps_reported_and_handled_by_policy(tmp_path):
    body = rows()
    p = write(tmp_path, "gap.csv", body[:21] + body[23:])          # two bars missing after the 20th
    with pytest.raises(DatasetError, match="gap_policy is 'fail'"):
        load_dataset(p, "SYNTH", timedelta(minutes=5), _sess(), DAY, DAY, gap_policy="fail")
    ds = load_dataset(p, "SYNTH", timedelta(minutes=5), _sess(), DAY, DAY)
    assert ds.integrity["gaps"] == 1 and ds.integrity["missing_bars"] == 2 and ds.integrity["rows_used"] == 75
    r, res = run(tmp_path / "g", data={"SYNTH": p})
    kinds = [e["kind"] for e in r.run.read_jsonl("journal", "US.jsonl")]
    assert kinds.count("DATA_INTERRUPTED") == 1 and kinds.count("DATA_RESUMED") == 1
    i = kinds.index("DATA_INTERRUPTED")
    assert kinds[i + 1] == "DATA_RESUMED" and kinds[i + 2] == "candle"
    assert res["metrics"]["equity_points"] == 75


def test_integrity_metadata(base):
    d = base[0].run.read_json("run.json")["datasets"][0]
    assert d["sha256"] == json.load(open(CSV + ".meta.json"))["sha256"]
    assert d["source"].startswith("SYNTHETIC") and d["rows_used"] == 77 and d["duplicates"] == 0 and d["gaps"] == 0
    assert (d["first_bar"], d["last_bar"]) == ("2026-11-23T14:30:00+00:00", "2026-11-23T20:50:00+00:00")


# ------------------------------------------------------------------ 5 / 6 / 7 strategy sequence, entries, exits
def test_strategy_sequence_on_every_trade(base):
    for t in base[1]["trades"]:
        stages = [s[0] for s in t["stage_path"]]
        pos = [stages.index(s) for s in STAGES]
        assert pos == sorted(pos), stages
        assert stages[-1] in (E.STOPPED_OUT, E.TARGET_HIT)


def test_entries_exits_sl_tp(base):
    t1, t2 = base[1]["trades"]
    tick, half = Decimal("0.01"), 1
    assert (t1["side"], t1["status"], t2["side"], t2["status"]) == ("BUY", E.STOPPED_OUT, "SELL", E.TARGET_HIT)
    assert Decimal(t1["entry_fill"]) == Decimal(t1["entry_open"]) + (1 + half) * tick
    assert Decimal(t2["entry_fill"]) == Decimal(t2["entry_open"]) - (1 + half) * tick
    assert t1["exit_gap"] is False and Decimal(t1["exit_fill"]) == Decimal(t1["sl"]) - (1 + half) * tick
    assert Decimal(t2["exit_fill"]) == Decimal(t2["tp"])                       # target: exact TP, no spread
    assert t1["entry_index"] == 51 and t1["exit_index"] == 58 and (t2["entry_index"], t2["exit_index"]) == (72, 76)


def test_same_logic_as_module_e_paper_pipeline(base):
    """The backtest's fills equal a direct Module E run on the same candles with the same (spread-folded) config."""
    r = base[0]
    spec = r.specs[0]
    series = T.CandleSeries.from_rows([(c.ts, c.open, c.high, c.low, c.close) for c in r.datasets[0].candles()],
                                      "SYNTH", "5m")
    rep = E.analyze_execution(series, "SYNTH", "5m", spec.market, spec.execution)
    direct = [(x.setup_id, str(x.entry_fill), str(x.exit_fill), str(x.quantity), str(x.realized_pnl))
              for x in rep.records if x.entry_fill is not None]
    got = [(t["setup_id"], t["entry_fill"], t["exit_fill"], t["quantity"], t["realized_pnl"]) for t in base[1]["trades"]]
    assert got == direct


# ------------------------------------------------------------------ 8 / 9 costs, sizing, risk
def test_fees_spread_and_slippage(base, tmp_path):
    res = base[1]
    slip = Decimal(0)
    for t in res["trades"]:
        q = Decimal(t["quantity"])
        for px, fee in ((t["entry_fill"], t["entry_fee"]), (t["exit_fill"], t["exit_fee"])):
            exp = (Decimal("0.0001") * Decimal(px) * q).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            assert Decimal(fee) == exp
        slip += Decimal(t["entry_slippage"]) + Decimal(t["exit_slippage"])
    m = res["metrics"]
    assert Decimal(m["slippage_total"]) == slip
    t1, t2 = res["trades"]
    spread = Decimal("0.01") * (Decimal(t1["quantity"]) * 2 + Decimal(t2["quantity"]))
    assert Decimal(m["spread_cost_included_in_slippage"]) == spread
    assert Decimal(m["fees_total"]) == sum(Decimal(t["entry_fee"]) + Decimal(t["exit_fee"]) for t in res["trades"])
    _, nos = run(tmp_path, cfg=raw_cfg(half_spread_ticks=0))
    assert Decimal(nos["trades"][0]["entry_fill"]) == Decimal(t1["entry_fill"]) - Decimal("0.01")
    assert Decimal(nos["metrics"]["spread_cost_included_in_slippage"]) == 0
    # (net P&L is not compared: the spread also changes Module E's risk distance and therefore the quantities)


def test_position_sizing_and_risk_limit(base, tmp_path):
    eq = Decimal("1000")
    for t in base[1]["trades"]:
        assert Decimal(t["loss_estimate"]) <= Decimal("0.01") * eq + Decimal("0.5")   # 1% of the equity at entry
        q = Decimal(t["quantity"])
        assert q == q.to_integral_value() and q >= 1
        eq += Decimal(t["realized_pnl"])
    _, small = run(tmp_path, cfg=raw_cfg(starting_equity="100"))
    big_q = [Decimal(t["quantity"]) for t in base[1]["trades"]]
    small_q = [Decimal(t["quantity"]) for t in small["trades"]]
    assert all(s < b for s, b in zip(small_q, big_q))


# ------------------------------------------------------------------ 10 / 11 / 12 metrics, drawdown, equity curve
def test_win_rate_profit_factor_averages(base):
    m, tr = base[1]["metrics"], base[1]["trades"]
    pnl = [Decimal(t["realized_pnl"]) for t in tr]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    assert (m["total_trades"], m["winning_trades"], m["losing_trades"]) == (2, len(wins), len(losses))
    assert Decimal(m["win_rate_pct"]) == Decimal(len(wins) * 100) / 2
    assert Decimal(m["profit_factor"]) == (sum(wins) / -sum(losses)).quantize(Decimal("0.0001"))
    assert Decimal(m["average_win"]) == sum(wins) / len(wins) and Decimal(m["average_loss"]) == sum(losses) / len(losses)
    assert Decimal(m["net_pnl"]) == sum(pnl) and Decimal(m["gross_pnl"]) == sum(Decimal(t["gross_pnl"]) for t in tr)
    assert Decimal(m["ending_equity"]) == Decimal("1000") + sum(pnl)
    assert Decimal(m["return_pct"]) == (sum(pnl) / 10).quantize(Decimal("0.0001"))


def test_undefined_metrics_are_null_not_zero():
    st = {"starting_budget": "1000", "currency": "USD", "rejections": [], "fees_total": "0", "slippage_total": "0"}
    sm = {"equity": "1000", "mtm_status": "OK", "cash": "1000", "open_positions": 0}
    m = metrics.compute(st, sm, [], [], 0, 0.01)
    assert m["win_rate_pct"] is None and m["profit_factor"] is None and m["average_win"] is None
    assert m["profit_factor_note"] == "no closed trades"


def test_max_drawdown_independent(base):
    curve = base[0].run.read_jsonl("equity.jsonl")
    peak, worst = Decimal(1000), Decimal(0)
    for p in curve:
        e = Decimal(p["equity"])
        peak = max(peak, e)
        worst = max(worst, peak - e)
    assert Decimal(base[1]["metrics"]["max_drawdown"]) == worst and worst > 0
    dd = metrics.drawdown([Decimal(x) for x in ("110", "90", "120", "60", "100")], Decimal(100))
    assert (dd["max_drawdown"], dd["max_drawdown_pct"]) == ("60", "50.0000")


def test_equity_curve(base):
    curve = base[0].run.read_jsonl("equity.jsonl")
    assert len(curve) == 77 and all(p["status"] == "OK" for p in curve)
    for p in curve:
        if p["open"] == 0:
            assert p["equity"] == p["cash"]
    assert curve[-1]["equity"] == base[1]["metrics"]["ending_equity"]
    assert curve[0]["equity"] == "1000" and base[1]["equity_curve"][-1]["equity"] == curve[-1]["equity"]


# ------------------------------------------------------------------ 13 ledger isolation
def test_backtest_never_touches_paper_books(tmp_path):
    root = DataRoot(str(tmp_path))
    paper = BookLedger.create(root, "US", owner_authorised=True, created_by="test paper")
    before = {p: open(root.path("books", p), "rb").read() for p in os.listdir(root.path("books"))}
    r, res = run(tmp_path)
    after = {p: open(root.path("books", p), "rb").read() for p in os.listdir(root.path("books"))}
    assert before == after and paper.state["seq"] == BookLedger.load(root, "US").state["seq"]
    assert sorted(os.listdir(str(tmp_path))) == ["backtests", "books"]
    assert BookLedger.load(r.run, "US", expect_kind=BACKTEST).state["ledger_kind"] == BACKTEST
    with pytest.raises(LedgerCorrupt):
        BookLedger.load(r.run, "US")                                     # a simulation ledger never loads as paper
    with pytest.raises(LedgerCorrupt):
        BookLedger.load(root, "US", expect_kind=BACKTEST)
    with pytest.raises(Exception):
        BookLedger.create(root, "CRYPTO", owner_authorised=True, created_by="x", starting_budget=Decimal("5"))


# ------------------------------------------------------------------ 14 / 15 restart, reproducibility
def test_restart_resumes_to_identical_result(tmp_path, base):
    r1, part = run(tmp_path, max_steps=40)
    assert part["status"] == RUNNING and r1.run.read_json("run.json")["status"] == RUNNING
    r2, res = run(tmp_path)
    assert res["results_sha256"] == base[1]["results_sha256"]
    led = BookLedger.load(r2.run, "US", expect_kind=BACKTEST)
    ids = led.state["booked_setup_ids"]
    assert len(ids) == len(set(ids)) == 2


def test_restart_after_crash_between_journal_and_curve(tmp_path, base):
    r1, _ = run(tmp_path, max_steps=55)
    p = r1.run.path("equity.jsonl")
    lines = open(p).read().splitlines()
    open(p, "w").write("\n".join(lines[:-1]) + "\n")                      # lose the last curve point
    _, res = run(tmp_path)
    assert res["results_sha256"] == base[1]["results_sha256"]


def test_reproducible_runs_and_cached_result(tmp_path, base):
    r, res = run(tmp_path / "x")
    assert r.run_id == base[0].run_id and res["results_sha256"] == base[1]["results_sha256"]
    seq = BookLedger.load(r.run, "US", expect_kind=BACKTEST).state["seq"]
    _, again = run(tmp_path / "x")                                       # same run: stored result, nothing re-executed
    assert again["results_sha256"] == res["results_sha256"]
    assert BookLedger.load(r.run, "US", expect_kind=BACKTEST).state["seq"] == seq
    other, _ = run(tmp_path / "y", cfg=raw_cfg(half_spread_ticks=0))
    assert other.run_id != r.run_id and ENGINE_VERSION in json.dumps(r.run.read_json("run.json"))
    p = r.run.path("results.json")
    d = json.load(open(p))
    d["metrics"]["net_pnl"] = "999"
    json.dump(d, open(p, "w"))
    with pytest.raises(BacktestError, match="SHA-256"):
        run(tmp_path / "x")


# ------------------------------------------------------------------ 16 invalid configuration
@pytest.mark.parametrize("mut,msg", [
    (lambda d: d["execution"].pop("fee_schedule"), "missing"),
    (lambda d: d["execution"].update(target_exit_ticks=1), "target_exit_ticks"),
    (lambda d: d["execution"].update(stop_exit_ticks=-1), "non-negative"),
    (lambda d: d["execution"].update(bogus=1), "unknown execution"),
    (lambda d: d.update(bogus=1), "unknown configuration"),
    (lambda d: d.update(book_id="USFNO"), "BLOCKED"),
    (lambda d: d.update(book_id="V4"), "book_id"),
    (lambda d: d.update(book_id="CRYPTO"), "NYSE calendar is for the US book"),
    (lambda d: d.update(timeframe="2m"), "timeframe"),
    (lambda d: d.update(half_spread_ticks=-1), "half_spread_ticks"),
    (lambda d: d.pop("half_spread_ticks"), "half_spread_ticks"),
    (lambda d: d.update(starting_equity="0"), "positive"),
    (lambda d: d.update(tick_size=0), "tick_size"),
    (lambda d: d.update(gap_policy="fill"), "gap_policy"),
    (lambda d: d.update(session={"kind": "continuous_24_7", "timezone": "Mars/Base", "trading_day_start": "00:00"}),
     "session"),
    (lambda d: d["execution"]["fee_schedule"].update(rounding_mode="NEAREST"), "rounding_mode"),
])
def test_invalid_configuration(mut, msg):
    d = copy.deepcopy(raw_cfg())
    mut(d)
    with pytest.raises(bcfg.BacktestConfigError, match=msg):
        bcfg.parse(d)


def test_nyse_needs_dates_and_symbol_rules(tmp_path):
    c = bcfg.parse(raw_cfg())
    with pytest.raises(BacktestError, match="--start and --end"):
        BacktestRun(DataRoot(str(tmp_path)), c, {"SYNTH": CSV})
    with pytest.raises(BacktestError, match="upper-case"):
        BacktestRun(DataRoot(str(tmp_path)), c, {"synth": CSV}, DAY, DAY)
    with pytest.raises(BacktestError, match="at least one"):
        BacktestRun(DataRoot(str(tmp_path)), c, {}, DAY, DAY)


def test_continuous_session_backtest(tmp_path):
    body = rows()
    shifted = [body[0]] + [[(datetime.fromisoformat(r[0].replace("Z", "+00:00")) - timedelta(hours=5, minutes=30))
                            .isoformat().replace("+00:00", "Z")] + r[1:] for r in body[1:]]
    p = write(tmp_path, "c.csv", shifted)
    cfg = raw_cfg(book_id="CRYPTO", session={"kind": "continuous_24_7", "timezone": "UTC", "trading_day_start": "00:00"})
    r = BacktestRun(DataRoot(str(tmp_path)), bcfg.parse(cfg), {"SYNTH": p})
    res = r.execute()
    assert res["metrics"]["total_trades"] == 2 and res["metrics"]["currency"] == "USD"


# ------------------------------------------------------------------ CLI, fetch, API
def test_cli_run_list_show_validate(tmp_path, capsys):
    args = ["--config", CFG_FILE, "--data", "SYNTH=" + CSV, "--start", "2026-11-23", "--end", "2026-11-23",
            "--root", str(tmp_path)]
    assert cli(["validate"] + args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "VALID"
    assert cli(["run"] + args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == COMPLETE and out["metrics"]["total_trades"] == 2
    assert cli(["list", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["run_id"] == out["run_id"]
    assert cli(["show", out["run_id"], "--trades", "--equity", "--root", str(tmp_path)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert len(shown["trades"]) == 2 and shown["equity_curve"]
    assert cli(["show", "bt-0000000000000000", "--root", str(tmp_path)]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert cli(["run", "--config", str(bad), "--data", "SYNTH=" + CSV, "--root", str(tmp_path)]) == 2
    assert "INVALID" in capsys.readouterr().err


def test_cli_fetch_refuses_without_v6_credential(tmp_path, capsys):
    code = cli(["fetch", "--symbol", "AAPL", "--timeframe", "5m", "--start", "2026-11-23", "--end", "2026-11-23",
                "--feed", "iex", "--out", str(tmp_path / "a.csv"), "--credential", str(tmp_path / "none.json")])
    assert code == 3 and "NOT CONNECTED" in capsys.readouterr().err and not (tmp_path / "a.csv").exists()
    code = cli(["fetch", "--symbol", "AAPL", "--timeframe", "5m", "--start", "2026-11-23", "--end", "2026-11-23",
                "--feed", "iex", "--out", str(tmp_path / "a.csv"), "--credential", "/etc/trader/trader.env"])
    assert code == 3


def test_fetch_to_csv_with_injected_client(tmp_path):
    class Fake:
        def fetch(self, symbol, tf, a, b):
            assert (a, b) == (datetime(2026, 11, 23, tzinfo=UTC), datetime(2026, 11, 24, tzinfo=UTC))
            return [Bar(symbol, datetime(2026, 11, 23, 14, 30, tzinfo=UTC), 10.0, 10.5, 9.9, 10.2, 100.0),
                    Bar(symbol, datetime(2026, 11, 23, 14, 35, tzinfo=UTC), 10.2, 10.4, 10.1, 10.3, 90.0)]
    out = fetch_to_csv(Fake(), "AAPL", "5m", DAY, DAY, str(tmp_path / "aapl.csv"), "iex")
    assert out["rows"] == 2
    ds = load_dataset(str(tmp_path / "aapl.csv"), "AAPL", timedelta(minutes=5), _sess(), DAY, DAY)
    assert ds.source.startswith("alpaca") and ds.integrity["rows_used"] == 2


def test_api_backtest_views(tmp_path, monkeypatch):
    monkeypatch.setenv("V6_DATA_ROOT", str(tmp_path))
    from api_v6 import views
    assert views.list_backtests()["runs"] == []
    r, res = run(tmp_path)
    lst = views.list_backtests()
    assert [x["run_id"] for x in lst["runs"]] == [r.run_id] and "BACKTEST" in lst["kind"]
    d = views.get_backtest(r.run_id)
    assert d["metrics"] == res["metrics"] and len(d["trades"]) == 2
    for bad in ("../../etc", "bt-zzzz", "bt-0000000000000000"):
        with pytest.raises(KeyError):
            views.get_backtest(bad)
    assert get_run(DataRoot(str(tmp_path)), r.run_id)["run"]["status"] == COMPLETE
    assert list_runs(DataRoot(str(tmp_path / "empty"))) == []
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from api_v6.app import app
    c = TestClient(app)
    assert c.get("/api/py/v6/backtests/%s" % r.run_id).json()["run"]["run_id"] == r.run_id
    assert c.get("/api/py/v6/backtests/bt-0000000000000000").status_code == 404
