"""V6 deployment files, validated offline: the install / uninstall scripts run against command shims (nothing is
installed, enabled or started on this machine) and the systemd units pass `systemd-analyze verify`."""
import os
import re
import shutil
import stat
import subprocess

import pytest

import _fx

D = os.path.join(_fx.ROOT, "deploy", "v6")
SHIMS = ("id", "useradd", "install", "rsync", "chown", "chmod", "python3", "systemctl", "rm")


def _shim_env(tmp):
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    log = tmp / "calls.log"
    for name in SHIMS:
        body = '#!/bin/sh\necho "%s $*" >> "%s"\n' % (name, log)
        if name == "id":
            body += '[ "$1" = "-u" ] && { echo 0; exit 0; }\nexit 1\n'     # root, and user trader-v6 absent
        elif name == "python3":   # `python3 -m venv DIR`: create a fake venv whose pip only logs
            body += ('if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then mkdir -p "$3/bin"; '
                     'printf \'#!/bin/sh\\necho "pip $*" >> "%s"\\n\' > "$3/bin/pip"; /bin/chmod +x "$3/bin/pip"; fi\n' % log)
        elif name == "systemctl":
            body += 'case "$1" in is-enabled) echo disabled;; is-active) echo inactive;; esac\nexit 0\n'
        p = bin_dir / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, PATH="%s:%s" % (bin_dir, os.environ.get("PATH", "")), V6_APP_DIR=str(tmp / "app"))
    return env, log


def _wsl_path(p):
    return subprocess.check_output(["wsl", "wslpath", "-u", str(p)], text=True).strip()


def _run_bash(script_path, bin_dir, app_dir, log_path):
    if os.name == "nt":
        w_script = _wsl_path(script_path)
        w_bin = _wsl_path(bin_dir)
        w_app = _wsl_path(app_dir)
        # Re-write shims with WSL log path so bash shims log to the Windows temp log file
        w_log = _wsl_path(log_path)
        for p in bin_dir.iterdir():
            txt = p.read_text().replace(str(log_path), w_log)
            p.write_text(txt, newline="\n")
        cmd = 'PATH="%s:$PATH" V6_APP_DIR="%s" bash "%s"' % (w_bin, w_app, w_script)
        return subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
    env = dict(os.environ, PATH="%s:%s" % (bin_dir, os.environ.get("PATH", "")), V6_APP_DIR=str(app_dir))
    return subprocess.run(["bash", script_path], env=env, capture_output=True, text=True)


def test_install_script_never_enables_or_starts(tmp_path):
    env, log = _shim_env(tmp_path)
    out = _run_bash(os.path.join(D, "install_v6.sh"), tmp_path / "bin", tmp_path / "app", log)
    assert out.returncode == 0, out.stderr
    calls = log.read_text().splitlines()
    sysd = [c for c in calls if c.startswith("systemctl")]
    assert "systemctl daemon-reload" in sysd
    assert not [c for c in sysd if re.search(r"\b(enable|start|restart|reload-or-restart)\b", c)], sysd
    assert any(c.startswith("useradd --system") and c.endswith("trader-v6") for c in calls)
    assert any("install -d -m 0750 -o trader-v6 -g trader-v6 /var/lib/trader-v6" == c for c in calls)
    assert any(c.startswith("install -m 0644") and c.endswith("/etc/systemd/system/") for c in calls)
    assert [c for c in calls if c.startswith("pip install")]
    assert not [c for c in calls if "/opt/trader " in c + " " or "/opt/trader/" in c or "/etc/trader " in c + " "]
    assert "Nothing was enabled or started" in out.stdout and "enabled=disabled active=inactive" in out.stdout


def test_uninstall_keeps_data_unless_purge(tmp_path):
    env, log = _shim_env(tmp_path)
    out = _run_bash(os.path.join(D, "uninstall_v6.sh"), tmp_path / "bin", tmp_path / "app", log)
    assert out.returncode == 0, out.stderr
    calls = log.read_text().splitlines()
    assert not [c for c in calls if "/var/lib/trader-v6" in c] and "Kept /var/lib/trader-v6" in out.stdout
    assert not [c for c in calls if re.search(r"(^| )/opt/trader(/| |$)|/etc/trader(/| |$)", c)]
    assert "systemctl disable trader-v6-runner" in calls and "systemctl stop trader-v6-api" in calls


def test_units_verify_with_systemd_analyze(tmp_path):
    if not shutil.which("systemd-analyze"):
        pytest.skip("systemd-analyze not available")
    for name in ("trader-v6-api.service", "trader-v6-runner.service"):
        src = open(os.path.join(D, name)).read()
        assert "ExecStart=/opt/trader-v6/venv/bin/python -m " in src
        assert "--host 127.0.0.1 --port 8001" in src or "v6_runtime.runner run" in src
        # the venv does not exist here: verify the unit with the interpreter swapped for an existing one
        u = tmp_path / name
        u.write_text(src.replace("/opt/trader-v6/venv/bin/python", shutil.which("python3") or "/usr/bin/python3"))
        r = subprocess.run(["systemd-analyze", "verify", str(u)], capture_output=True, text=True)
        problems = [l for l in (r.stdout + r.stderr).splitlines()
                    if l.strip() and "trader-v6" in l and "user" not in l.lower()]
        assert r.returncode == 0 or not problems, r.stdout + r.stderr
