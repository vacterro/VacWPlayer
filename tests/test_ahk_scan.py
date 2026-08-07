"""ahk_generator PID-scan tests: silent-except removal (T-032)."""

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


# --- _find_our_pids --------------------------------------------------------

def test_find_our_pids_success(monkeypatch):
    _monkey_ts(monkeypatch)
    monkeypatch.setattr(ag.subprocess, "run", lambda *a, **k: FakeOut("777\n"))
    assert ag._find_our_pids() == [777]


def test_find_our_pids_returns_empty_inside_throttle(monkeypatch):
    _monkey_ts(monkeypatch)
    monkeypatch.setattr(ag.subprocess, "run", lambda *a, **k: FakeOut("1\n"))
    ag._find_our_pids()  # first call sets _last_scan_ts
    assert ag._find_our_pids() == []  # within 10s window


def test_find_our_pids_timeout_retries_once(monkeypatch, capsys):
    _monkey_ts(monkeypatch, value=99.0)
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired("powershell", 10)
        return FakeOut("42\n")

    monkeypatch.setattr(ag.subprocess, "run", flaky)
    assert ag._find_our_pids() == [42]
    assert len(calls) == 2
    assert "retrying once" in capsys.readouterr().err


def test_find_our_pids_double_timeout_gives_up(monkeypatch, capsys):
    _monkey_ts(monkeypatch, value=99.0)
    calls = []

    def always_timeout(*a, **k):
        calls.append(1)
        raise subprocess.TimeoutExpired("powershell", 10)

    monkeypatch.setattr(ag.subprocess, "run", always_timeout)
    assert ag._find_our_pids() == []
    assert len(calls) == 2
    assert "timed out again" in capsys.readouterr().err


def test_find_our_pids_other_exception_logs(monkeypatch, capsys):
    _monkey_ts(monkeypatch, value=99.0)

    def boom(*a, **k):
        raise OSError("powershell missing")

    monkeypatch.setattr(ag.subprocess, "run", boom)
    assert ag._find_our_pids() == []
    assert "PID scan failed" in capsys.readouterr().err
