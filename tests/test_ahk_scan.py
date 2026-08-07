"""ahk_generator PID-scan tests: silent-except removal (T-032), throttle
vs zero distinction (T-087), PID identity verification (T-088)."""

import os
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import ahk_generator as ag


class FakeOut:
    def __init__(self, text=""):
        self.stdout = text.encode("utf-8")
        self.stderr = b""


def _monkey_ts(monkeypatch, value=99.0):
    monkeypatch.setattr(ag, "_last_scan_ts", 0.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: value)


# --- _probe_pids -----------------------------------------------------------

def test_probe_parses_pid_lines(monkeypatch):
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return FakeOut("123\n456\n\nnot-a-pid\n")

    monkeypatch.setattr(ag.subprocess, "run", fake_run)
    assert ag._probe_pids("SOME CMD") == [123, 456]
    assert "powershell" in calls[0][0]


def test_probe_empty_output(monkeypatch):
    monkeypatch.setattr(ag.subprocess, "run", lambda *a, **k: FakeOut(""))
    assert ag._probe_pids("") == []

def test_probe_returns_empty_for_no_pids(monkeypatch):
    monkeypatch.setattr(ag.subprocess, "run", lambda *a, **k: FakeOut("nothing here\n"))
    assert ag._probe_pids("CMD") == []


# --- _find_our_pids (state, pids) contract ---------------------------------

def test_find_our_pids_success(monkeypatch):
    _monkey_ts(monkeypatch)
    monkeypatch.setattr(ag.subprocess, "run", lambda *a, **k: FakeOut("777\n"))
    state, pids = ag._find_our_pids()
    assert state == "ok"
    assert pids == [777]


def test_find_our_pids_throttle_reuses_cached(monkeypatch):
    _monkey_ts(monkeypatch)
    monkeypatch.setattr(ag.subprocess, "run", lambda *a, **k: FakeOut("1\n"))
    state, pids = ag._find_our_pids()  # first call runs the scan
    assert state == "ok"
    assert pids == [1]
    # second call inside the throttle window: cache reuse, NOT [] - a skipped
    # scan is never converted into an authoritative zero (T-087).
    state2, pids2 = ag._find_our_pids()
    assert state2 == "cached"
    assert pids2 == [1]


def test_find_our_pids_force_bypasses_throttle(monkeypatch):
    _monkey_ts(monkeypatch)
    calls = []

    def fake_run(*a, **k):
        calls.append(1)
        return FakeOut("42\n")

    monkeypatch.setattr(ag.subprocess, "run", fake_run)
    ag._find_our_pids()
    state, pids = ag._find_our_pids(force=True)
    assert state == "ok"
    assert pids == [42]
    assert len(calls) == 2


def test_find_our_pids_timeout_retries_once(monkeypatch, capsys):
    _monkey_ts(monkeypatch, value=99.0)
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired("powershell", 10)
        return FakeOut("42\n")

    monkeypatch.setattr(ag.subprocess, "run", flaky)
    state, pids = ag._find_our_pids()
    assert state == "ok"
    assert pids == [42]
    assert len(calls) == 2
    assert "retrying once" in capsys.readouterr().err


def test_find_our_pids_double_timeout_gives_up(monkeypatch, capsys):
    _monkey_ts(monkeypatch, value=99.0)
    calls = []

    def always_timeout(*a, **k):
        calls.append(1)
        raise subprocess.TimeoutExpired("powershell", 10)

    monkeypatch.setattr(ag.subprocess, "run", always_timeout)
    state, pids = ag._find_our_pids()
    assert state == "failed"
    assert pids == []
    assert len(calls) == 2
    assert "timed out again" in capsys.readouterr().err


def test_find_our_pids_other_exception_logs(monkeypatch, capsys):
    _monkey_ts(monkeypatch, value=99.0)

    def boom(*a, **k):
        raise OSError("powershell missing")

    monkeypatch.setattr(ag.subprocess, "run", boom)
    state, pids = ag._find_our_pids()
    assert state == "failed"
    assert pids == []
    assert "PID scan failed" in capsys.readouterr().err


def test_scan_pattern_matches_single_backslash_cmdline(monkeypatch):
    """Regression (auto-restart loop): the scan pattern must match a real AHK
    command line, which carries the script path with SINGLE backslashes. Two
    historical traps: the -like wildcard doubled them, and a backtick before
    `$_` made PowerShell treat `$_.CommandLine` as a command name instead of
    the process's command line - both made the scan return an authoritative
    empty set and the engine watchdog restart forever."""
    captured = {}
    monkeypatch.setattr(ag, "_probe_pids",
                        lambda ps_cmd: captured.setdefault("cmd", ps_cmd) or [123])
    monkeypatch.setattr(ag, "_last_scan_ts", 0.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: 99.0)

    ag._find_our_pids(force=True)

    cmd = captured["cmd"]
    assert "`$_.CommandLine" not in cmd, \
        "backtick escapes break the member access in PowerShell"
    assert "$_.CommandLine -match" in cmd, \
        "scan must use plain $_.CommandLine member access"
    m = re.search(r"-match '([^']*)'", cmd)
    assert m, "scan must use a regex -match on the command line"
    pattern = m.group(1)
    sample = '"C:\\AutoHotkeyU64.exe" "%s" 1234' % os.path.abspath(ag.AHK_PATH)
    assert re.search(pattern, sample), "pattern does not match a real cmdline"


def test_scan_pattern_matches_real_path(monkeypatch):
    """The constructed pattern must match the ACTUAL project script path with
    its real (single-backslash) form - the live loop regression."""
    captured = {}
    monkeypatch.setattr(ag, "_probe_pids",
                        lambda ps_cmd: captured.setdefault("cmd", ps_cmd) or [1])
    monkeypatch.setattr(ag, "_last_scan_ts", 0.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: 99.0)

    ag._find_our_pids(force=True)

    m = re.search(r"-match '([^']*)'", captured["cmd"])
    sample = '"C:\\AutoHotkeyU64.exe" "%s" 4242' % os.path.abspath(ag.AHK_PATH)
    assert re.search(m.group(1), sample)


# --- T-087: throttle must not mean "no process" ----------------------------

def test_is_running_reuses_cached_verified_pid(monkeypatch):
    """A cached verified pid behind the pid file reports running WITHOUT a
    rescan - 'not scanned' never reads as 'not running'."""
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 123)
    monkeypatch.setattr(ag, "_last_scan_ts", 5.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: 5.1)  # inside 10s window
    monkeypatch.setattr(ag, "_last_scan_pids", [123])
    monkeypatch.setattr(ag, "_pid_is_ahk_image", lambda pid: True)
    scanned = []
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: scanned.append(force) or ("cached", [123]))
    assert ag.is_running() is True
    assert scanned == []  # fast path, no spawn


def test_is_running_cached_zero_after_stop_stays_false(monkeypatch):
    """After stop_ahk the cache is verified-empty: is_running reports stopped
    within the throttle window without rescanning."""
    monkeypatch.setattr(ag, "_read_pidfile", lambda: None)
    monkeypatch.setattr(ag, "_last_scan_ts", 5.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: 5.1)
    monkeypatch.setattr(ag, "_last_scan_pids", [])
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("cached", []))
    assert ag.is_running() is False


# --- T-088: PID file is not process identity -------------------------------

def test_is_running_never_reports_unrelated_alive_pid(monkeypatch):
    """A stale pid file whose pid was reused by an unrelated-but-alive process
    must not be reported as ours: it was never command-line verified."""
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 999)
    monkeypatch.setattr(ag, "_last_scan_ts", 5.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: 5.1)
    monkeypatch.setattr(ag, "_last_scan_pids", [])      # verified: not ours
    monkeypatch.setattr(ag, "_pid_is_ahk_image", lambda pid: True)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("cached", []))
    assert ag.is_running() is False


def test_stop_ahk_kills_only_verified_pids(monkeypatch):
    killed = []
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 111)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("ok", [111, 222]))
    monkeypatch.setattr(ag, "_stop_pids",
                        lambda pids, wait_ms=500: killed.extend(pids))
    monkeypatch.setattr(ag.os, "remove", lambda *a, **k: None)
    ag.stop_ahk()
    assert killed == [111, 222]


def test_stop_ahk_does_not_kill_unrelated_reused_pid(monkeypatch):
    """A tracked pid that the forced scan does NOT verify as ours is never
    killed - the stale reused pid case (T-088 regression)."""
    killed = []
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 999)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("ok", []))  # 999 is NOT ours
    monkeypatch.setattr(ag, "_stop_pids",
                        lambda pids, wait_ms=500: killed.extend(pids))
    monkeypatch.setattr(ag.os, "remove", lambda *a, **k: None)
    ag.stop_ahk()
    assert killed == []


def test_stop_ahk_uses_force_scan(monkeypatch):
    """Explicit stop always scans fresh, even right after a throttled scan
    (T-087): stop immediately after a previous scan still finds orphans."""
    forces = []
    monkeypatch.setattr(ag, "_read_pidfile", lambda: None)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: forces.append(force) or ("ok", [5]))
    monkeypatch.setattr(ag, "_stop_pids", lambda pids, wait_ms=500: None)
    monkeypatch.setattr(ag.os, "remove", lambda *a, **k: None)
    ag.stop_ahk()
    assert forces == [True]
