"""US Stocks data path: Alpaca DATA-ONLY adapter (no network: injected transport, SYNTHETIC payloads), credential
refusals, completed-bar feed validation, US Stocks config (NOT APPROVED -> no trading), NYSE calendar, US F&O BLOCKED."""
import copy
import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest

import _fx  # noqa: F401
from scanner_v6.exit import execution as E
from v6_runtime import options, us_stocks
from v6_runtime.data import alpaca as A
from v6_runtime.data.feed import (ACCEPT, DUPLICATE, INVALID, LATE, MISALIGNED, NOT_COMPLETE, OUT_OF_SESSION,
                                  REVISION, BarFeed)

UTC = timezone.utc
CRED = A.DataCredential("SYNTHKEY0000", "synthetic-secret", "test")
SYNTH = {"bars": [{"t": "2026-11-23T14:30:00Z", "o": 10.0, "h": 10.2, "l": 9.9, "c": 10.1, "v": 1200},
                  {"t": "2026-11-23T14:35:00Z", "o": 10.1, "h": 10.3, "l": 10.0, "c": 10.2, "v": 900}],
         "next_page_token": None, "_label": "SYNTHETIC (not recorded market data)"}


# ------------------------------------------------------------------ Alpaca adapter
@pytest.mark.parametrize("method,url", [
    ("POST", "https://data.alpaca.markets/v2/stocks/AAPL/bars"),
    ("DELETE", "https://data.alpaca.markets/v2/stocks/AAPL/bars"),
    ("GET", "https://api.alpaca.markets/v2/orders"),
    ("GET", "https://paper-api.alpaca.markets/v2/orders"),
    ("GET", "https://paper-api.alpaca.markets/v2/stocks/AAPL/bars"),
    ("GET", "https://data.alpaca.markets/v2/account"),
    ("GET", "https://data.alpaca.markets/v2/orders"),
    ("GET", "http://data.alpaca.markets/v2/stocks/AAPL/bars"),
    ("GET", "https://evil.example/v2/stocks/AAPL/bars"),
])
def test_only_get_bars_on_the_data_host(method, url):
    with pytest.raises(A.AlpacaDataError):
        A.check_request(method, url)


def test_fetch_uses_injected_transport_and_paginates():
    calls = []
    pages = [dict(SYNTH, next_page_token="p2"), {"bars": [{"t": "2026-11-23T14:40:00Z", "o": 10.2, "h": 10.4,
                                                          "l": 10.1, "c": 10.3, "v": 800}], "next_page_token": None}]

    def transport(m, url, headers):
        A.check_request(m, url)
        calls.append((m, url, sorted(headers)))
        return pages[len(calls) - 1]
    bars = A.AlpacaBars(CRED, "iex", transport).fetch("AAPL", "5m", datetime(2026, 11, 23, 14, 30, tzinfo=UTC),
                                                      datetime(2026, 11, 23, 15, 0, tzinfo=UTC))
    assert [b.close for b in bars] == [10.1, 10.2, 10.3] and len(calls) == 2
    assert all(c[0] == "GET" and "feed=iex" in c[1] and "/v2/stocks/AAPL/bars" in c[1] for c in calls)
    assert "page_token=p2" in calls[1][1]
    assert bars[0].start == datetime(2026, 11, 23, 14, 30, tzinfo=UTC)


def test_feed_choice_and_credential_type_required():
    with pytest.raises(A.AlpacaDataError):
        A.AlpacaBars(CRED, None)
    with pytest.raises(A.CredentialError):
        A.AlpacaBars({"key_id": "x", "secret": "y"}, "iex")


def test_malformed_payload_refused():
    with pytest.raises(A.AlpacaDataError):
        A.parse_bars("AAPL", {"bars": [{"t": "2026-11-23T14:30:00Z", "o": 1}]})
    assert A.parse_bars("AAPL", {"bars": None}) == []


def test_credential_rules(tmp_path):
    assert A.load_credential(str(tmp_path / "absent.json")) is None
    for bad in ("/etc/trader/trader.env", "/etc/trader/alpaca.json", "/opt/trader/x.json", str(tmp_path / "trader.env")):
        with pytest.raises(A.CredentialError):
            A.load_credential(bad)
    p = tmp_path / "alpaca-data.json"
    p.write_text(json.dumps({"purpose": "v6-data-only", "key_id": "SYNTHKEY", "secret": "s3cr3t"}))
    os.chmod(p, 0o644)
    with pytest.raises(A.CredentialError):
        A.load_credential(str(p))                                    # group/other readable
    os.chmod(p, 0o600)
    c = A.load_credential(str(p))
    assert c.key_id == "SYNTHKEY" and "s3cr3t" not in repr(c)
    p.write_text(json.dumps({"purpose": "v4", "key_id": "k", "secret": "s"}))
    with pytest.raises(A.CredentialError):
        A.load_credential(str(p))


# ------------------------------------------------------------------ completed-bar feed


def _session():
    cal = us_stocks.load_calendar()
    return us_stocks.session_calendar(cal, date(2026, 11, 23), date(2026, 11, 23))


def _bar(minute, o=10.0, h=10.2, l=9.9, c=10.1, v=100.0):
    return A.Bar("AAPL", datetime(2026, 11, 23, 14, 30, tzinfo=UTC) + timedelta(minutes=minute), o, h, l, c, v)


def _feed(**kw):
    return BarFeed("AAPL", timedelta(minutes=5), _session(), kw.get("settle", 10), kw.get("stale", 2),
                   kw.get("align", "session_grid"))


def test_feed_requires_configured_thresholds():
    with pytest.raises(ValueError):
        BarFeed("AAPL", timedelta(minutes=5), _session(), None, 2, None)
    with pytest.raises(ValueError):
        BarFeed("AAPL", timedelta(minutes=5), _session(), 10, 2, "guess")


def test_feed_statuses():
    f = _feed()
    t = lambda m, s=0: datetime(2026, 11, 23, 14, 30, tzinfo=UTC) + timedelta(minutes=m, seconds=s)  # noqa: E731
    assert f.offer(_bar(0), t(5, 5)).status == NOT_COMPLETE                 # before end + settle
    r = f.offer(_bar(0), t(5, 10))
    assert r.status == ACCEPT and r.candle.index == 0 and r.events == []
    assert f.offer(_bar(0), t(6)).status == DUPLICATE
    assert f.offer(_bar(0, c=10.15), t(6)).status == REVISION
    assert f.offer(_bar(7), t(20)).status == MISALIGNED
    assert f.offer(_bar(5, h=9.0), t(20)).status == INVALID                 # high < open
    assert f.offer(_bar(-60), t(20)).status == LATE
    assert f.offer(_bar(390), t(400)).status == OUT_OF_SESSION              # 21:00Z = 16:00 NY close
    assert f.offer(_bar(5), t(20)).status == ACCEPT
    assert f.health()["counts"][ACCEPT] == 2


def test_feed_stale_then_resumed_inside_fd2_window():
    f = _feed()
    base = datetime(2026, 11, 23, 14, 30, tzinfo=UTC)
    assert f.offer(_bar(0), base + timedelta(minutes=6)).status == ACCEPT
    assert f.check_stale(base + timedelta(minutes=12)) is None
    ev = f.check_stale(base + timedelta(minutes=21))
    assert ev and ev[0] == "DATA_INTERRUPTED"
    assert f.check_stale(base + timedelta(minutes=22)) is None               # reported once
    assert f.offer(_bar(10), base + timedelta(minutes=19)).status == LATE    # older than the data event
    r = f.offer(_bar(25), base + timedelta(minutes=31))
    assert r.status == ACCEPT and r.events == [("DATA_RESUMED", _bar(25).start)]
    assert ev[1] <= r.events[0][1]                                           # interruption <= resume <= next open


def test_feed_out_of_session_on_holiday():
    cal = us_stocks.load_calendar()
    sess = us_stocks.session_calendar(cal, date(2026, 11, 26), date(2026, 11, 27))      # Thanksgiving + early close
    f = BarFeed("AAPL", timedelta(minutes=5), sess, 10, 2, "session_grid")
    thx = A.Bar("AAPL", datetime(2026, 11, 26, 15, 0, tzinfo=UTC), 1, 1, 1, 1, 1)
    assert f.offer(thx, datetime(2026, 11, 26, 16, 0, tzinfo=UTC)).status == OUT_OF_SESSION
    late = A.Bar("AAPL", datetime(2026, 11, 27, 18, 30, tzinfo=UTC), 1, 1, 1, 1, 1)  # 13:30 NY after the 13:00 close
    assert f.offer(late, datetime(2026, 11, 27, 19, 0, tzinfo=UTC)).status == OUT_OF_SESSION


# ------------------------------------------------------------------ US Stocks config / calendar
def _template():
    with open(os.path.join(os.path.dirname(us_stocks.__file__), "config", "us_stocks.template.json")) as fh:
        return json.load(fh)


def test_calendar_marked_not_verified_and_bounded():
    cal = us_stocks.load_calendar()
    assert cal["verified"] is False
    with pytest.raises(us_stocks.USConfigError):
        us_stocks.trading_sessions(cal, date(2030, 1, 2), date(2030, 1, 3))


def test_template_is_all_not_approved_and_blocks():
    cfg = us_stocks.parse_config(_template())
    assert cfg.approved == {} and not cfg.feed_approved
    r = us_stocks.readiness(cfg, us_stocks.load_calendar(), credentials_present=False)
    assert r["ready"] is False
    for k in ("fee_schedule", "quantity_step", "exchange_day_rule", "mtm_exit_slippage_ticks", "alignment_rule"):
        assert "%s: NOT APPROVED" % k in r["blockers"]
    assert any("credential" in b for b in r["blockers"]) and any("NOT VERIFIED" in b for b in r["blockers"])
    assert us_stocks.readiness(None, us_stocks.load_calendar(), False)["ready"] is False


def test_not_approved_values_never_reach_module_e():
    raw = _template()
    raw["instruments"] = ["AAPL"]
    raw["values"]["tick_size"] = {"value": 0.01, "approval": "APPROVED", "decision": "test"}
    raw["values"]["fee_schedule"] = {"value": {"rate": "0.001"}, "approval": "NOT_APPROVED", "decision": "IC-1"}
    cfg = us_stocks.parse_config(raw)
    assert cfg.approved == {"tick_size": 0.01} and "fee_schedule" in cfg.not_approved
    sp = us_stocks.instrument_specs(cfg, us_stocks.load_calendar(), date(2026, 11, 23), date(2026, 11, 24))[0]
    assert sp.execution.fee_schedule is None and str(sp.execution.starting_equity) == "1000"
    assert sp.execution.missing(sp.market)                                    # -> EXECUTION_CONFIG_INCOMPLETE
    assert hasattr(E, "ExecutionStream")


@pytest.mark.parametrize("mut", [
    lambda d: d.update(book_id="INDIA"),
    lambda d: d["data_provider"].update(name="polygon"),
    lambda d: d["values"].update(made_up={"value": 1, "approval": "APPROVED", "decision": "x"}),
    lambda d: d.update(instruments=["aapl"]),
    lambda d: d.update(timeframe="2m"),
])
def test_config_validation(mut):
    raw = copy.deepcopy(_template())
    mut(raw)
    with pytest.raises(us_stocks.USConfigError):
        us_stocks.parse_config(raw)


def test_options_always_blocked():
    r = options.readiness()
    assert r["ready"] is False and r["status"] == "US F&O PAPER EXECUTION: BLOCKED / NOT READY"
    all_ok = {k: True for k in options.REQUIREMENTS}
    assert options.readiness(provider=object(), approvals=all_ok)["ready"] is False
