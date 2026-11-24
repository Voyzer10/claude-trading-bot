"""Scanner identity, NOT CONNECTED / NOT ACTIVE / CONNECTED states, API views (read-only), runner gates, and static
isolation from V4 (no V4 imports, files, secrets or order calls)."""
import ast
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

import _fx
from v6_runtime import identity, runner, status
from v6_runtime.paths import DataRoot

REPO = _fx.ROOT
V6_DIRS = ("v6_runtime", "api_v6")


def test_identity_is_backend_verified():
    i = identity.scanner_identity()
    assert i["status"] == identity.CONNECTED == "V6 SMC Scanner"
    assert (i["scanner_name"], i["scanner_version"], i["execution_mode"]) == ("V6 SMC Scanner", "V6", "PAPER TRADING")
    assert i["paper_only"] is True and i["places_orders"] is False and re.fullmatch(r"[0-9a-f]{64}", i["package_sha256"])


def test_identity_not_connected_when_scanner_unsafe(monkeypatch):
    from scanner_v6 import config as v6cfg
    monkeypatch.setattr(v6cfg, "PLACES_ORDERS", True)
    assert identity.scanner_identity()["status"] == identity.NOT_CONNECTED


def test_status_states(tmp_path):
    missing = DataRoot(str(tmp_path / "nope"))
    o = status.overall(missing, cred_path=str(tmp_path / "c.json"))
    assert o["scanner"]["label"] == "V6 NOT CONNECTED" and o["paper_only"] is True and o["places_orders"] is False
    assert all(b["state"] == "NOT_INITIALISED" and b["summary"] is None for b in o["books"].values())
    root = DataRoot(str(tmp_path / "root"))
    os.makedirs(root.root)
    o = status.overall(root, cred_path=str(tmp_path / "c.json"))
    assert o["scanner"]["label"] == "V6 NOT ACTIVE" and o["readiness"]["US"]["ready"] is False
    assert o["readiness"]["USFNO"]["ready"] is False
    now = datetime.now(timezone.utc)
    root.write_json_atomic({"at": now.isoformat()}, "runtime", "heartbeat.json")
    assert status.overall(root, now=now)["scanner"]["label"] == "V6 SMC Scanner"
    assert status.overall(root, now=now + timedelta(minutes=4))["scanner"]["label"] == "V6 NOT ACTIVE"


def test_book_status_never_shows_zero_for_missing_or_corrupt(tmp_path):
    root, led = _fx.book(tmp_path)
    led.book_entry({"setup_id": "S", "instrument": "AAA", "entry_fill": "1", "quantity": "1", "entry_fee": "0.01"})
    p = root.path("books", "US.json")
    d = json.load(open(p))
    d["cash"] = "0"
    json.dump(d, open(p, "w"))
    b = status.book_status(root, "US")
    assert b["state"] == "NOT_READY" and b["summary"] is None


def test_api_views_and_app(tmp_path, monkeypatch):
    monkeypatch.setenv("V6_DATA_ROOT", str(tmp_path))
    root, led = _fx.book(tmp_path)
    from api_v6 import views
    assert views.health()["paper_only"] is True
    ids = views.get_identity()
    assert ids["scanner_name"] == "V6 SMC Scanner" and ids["label"] == "V6 NOT ACTIVE"
    assert views.get_books()["US"]["state"] == "LOADED" and views.get_books()["USFNO"]["state"] == "NOT_INITIALISED"
    assert views.get_book("US")["trades"] == [] and views.get_signals("US") == []
    assert views.get_performance("CRYPTO")["state"] == "NOT_INITIALISED"
    with pytest.raises(KeyError):
        views.get_book("V4")
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from api_v6.app import app
    c = TestClient(app)
    assert c.get("/api/py/v6/status").json()["scanner"]["label"] == "V6 NOT ACTIVE"
    assert c.get("/api/py/v6/books/NOPE").status_code == 404
    for r in app.routes:                                                 # read-only API
        methods = getattr(r, "methods", None) or set()
        assert methods <= {"GET", "HEAD"}, (r.path, methods)
        assert r.path.startswith("/api/py/v6/")
    assert fastapi


def test_runner_gates(tmp_path):
    root = DataRoot(str(tmp_path / "r"))
    assert runner.gates(root, "USFNO")
    g = runner.gates(root, "US")
    assert g and "does not exist" in g[0]
    os.makedirs(root.root, exist_ok=True)
    g = runner.gates(root, "US")
    assert any("ENABLED_US" in x for x in g) and any("not initialised" in x for x in g)
    assert any("NOT VERIFIED" in x for x in g) and any("credential" in x for x in g)


def test_runner_cli_refuses_without_gates(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("V6_DATA_ROOT", str(tmp_path))
    os.makedirs(str(tmp_path), exist_ok=True)
    assert runner.main(["run", "--book", "US"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NOT READY"
    with pytest.raises(Exception):
        runner.main(["init-book", "--book", "US"])                     # no --owner-authorised
    assert not os.path.exists(os.path.join(str(tmp_path), "books", "US.json"))


# ------------------------------------------------------------------ static isolation
def _py_files():
    for d in V6_DIRS:
        for dp, _, fs in os.walk(os.path.join(REPO, d)):
            for f in fs:
                if f.endswith(".py"):
                    yield os.path.join(dp, f)


V4_MODULES = {"paper", "live", "risk", "broker", "auto_crypto", "auto_nse", "auto_fno", "auto_us", "scan_crypto",
              "scan_nse", "research", "api", "kite", "alpaca", "us_ticker", "ticker", "crypto_ticker", "pov"}


def test_no_v4_imports():
    for p in _py_files():
        tree = ast.parse(open(p).read())
        for n in ast.walk(tree):
            names = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0:
                names = [n.module or ""]
            for m in names:
                top = m.split(".")[0]
                assert top not in V4_MODULES, (p, m)


def test_no_v4_paths_secrets_or_order_calls():
    for p in _py_files():
        src = open(p).read()
        for b in ("ALPACA_KEY_ID", "APCA_API_KEY_ID", "KITE_API", "place_order", "submit_order", "execute_order",
                  "scanner_version\"]", "trader/paper/ledger", "trader/live/"):
            assert b not in src, (p, b)


def test_v6_ui_uses_only_v6_api():
    for rel in ("components/v6/V6Dashboard.tsx", "components/v6/VersionSwitch.tsx", "lib/v6/api.ts", "app/v6/page.tsx"):
        src = open(os.path.join(REPO, rel)).read()
        for m in re.findall(r"""["'`](/api/[^"'`]*)""", src):
            assert m.startswith("/api/py/v6"), (rel, m)
        for imp in re.findall(r'from "(@/[^"]+)"', src):
            assert imp.startswith(("@/lib/v6/", "@/components/v6/")), (rel, imp)


def test_import_isolation_in_subprocess(tmp_path):
    code = ("import sys, json; import v6_runtime.runner, v6_runtime.portfolio, api_v6.views; "
            "bad=[m for m in sys.modules if m.split('.')[0] in %r]; print(json.dumps(bad))" % sorted(V4_MODULES))
    out = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); " % REPO + code],
                         capture_output=True, text=True, cwd=str(tmp_path), env={"V6_DATA_ROOT": str(tmp_path)})
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == []


def test_systemd_units_isolated_and_not_in_v4_deploy():
    d = os.path.join(REPO, "deploy", "v6")
    for u in ("trader-v6-api.service", "trader-v6-runner.service"):
        s = open(os.path.join(d, u)).read()
        assert "User=trader-v6" in s and "V6_DATA_ROOT=/var/lib/trader-v6" in s
        assert "EnvironmentFile" not in s and "/etc/trader/" not in s.replace("InaccessiblePaths=/etc/trader /opt", "")
        assert "WorkingDirectory=/opt/trader-v6/app" in s
    inst = open(os.path.join(d, "install_v6.sh")).read()
    assert "systemctl enable" not in inst and "systemctl start" not in inst and "init-book" not in inst
    upd = open(os.path.join(REPO, "deploy", "update.sh")).read()
    assert "v6" not in upd.lower()
