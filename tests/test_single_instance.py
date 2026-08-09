"""single_instance PID-identity tests (T-088): a stale reused PID pointing at
an unrelated process is never killed."""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import single_instance as si


def test_pid_runs_our_script_accepts_own_cmdline(monkeypatch):
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return type("R", (), {
            "stdout": ("C:\\Python\\python.exe -u C:\\app\\accept.py "
                       "--replace\r\n").encode("utf-8")})()

    monkeypatch.setattr(si.subprocess, "run", fake_run)
    assert si._pid_runs_our_script(1234, "accept") is True
    assert "ProcessId = 1234" in calls[0][-1]


def test_pid_runs_our_script_rejects_unrelated_python(monkeypatch):
    def fake_run(args, **kw):
        return type("R", (), {
            "stdout": b"C:\\Python\\python.exe -u C:\\other\\tool.py\r\n"})()

    monkeypatch.setattr(si.subprocess, "run", fake_run)
    assert si._pid_runs_our_script(999, "accept") is False


def test_pid_runs_our_script_rejects_unknown_name():
    assert si._pid_runs_our_script(1, "not_a_real_instance") is False


def test_kill_previous_holder_does_not_kill_unrelated_pid(monkeypatch, capsys):
    """A live pid behind a stale pid file whose command line is NOT our script
    must not be terminated (T-088 regression)."""
    killed = []
    monkeypatch.setattr(si.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(si, "_pid_runs_our_script", lambda pid, name: False)

    class F:
        def read(self):
            return "777"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    monkeypatch.setattr("builtins.open", lambda path, *a, **k: F())
    monkeypatch.setattr(si.win32api, "OpenProcess", lambda *a: killed.append(a) or 5)
    monkeypatch.setattr(si.win32api, "TerminateProcess", lambda *a: killed.append("KILL"))
    monkeypatch.setattr(si.win32event, "WaitForSingleObject", lambda *a: None)
    monkeypatch.setattr(si.win32api, "CloseHandle", lambda *a: None)

    si._kill_previous_holder("accept")

    assert "KILL" not in killed
    assert "identity not proven" in capsys.readouterr().err


def test_kill_previous_holder_kills_verified_holder(monkeypatch):
    killed = []
    monkeypatch.setattr(si.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(si, "_pid_runs_our_script", lambda pid, name: True)

    class F:
        def read(self):
            return "123"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    monkeypatch.setattr("builtins.open", lambda path, *a, **k: F())
    monkeypatch.setattr(si.win32api, "OpenProcess", lambda *a: 9)
    monkeypatch.setattr(si.win32api, "TerminateProcess", lambda *a: killed.append("KILL"))
    monkeypatch.setattr(si.win32event, "WaitForSingleObject", lambda *a: None)
    monkeypatch.setattr(si.win32api, "CloseHandle", lambda *a: None)

    si._kill_previous_holder("accept")
    assert killed == ["KILL"]


def test_set_timer_resolution_survives_winmm_failure(monkeypatch):
    """A host that refuses timeBeginPeriod must not crash the engine bootstrap."""

    class FakeCtypes:
        @staticmethod
        def WinDLL(*a, **k):
            raise OSError("no winmm")

    monkeypatch.setitem(sys.modules, "ctypes", FakeCtypes())
    si.set_timer_resolution()  # must not raise


def test_set_timer_resolution_registers_restore_on_success(monkeypatch):
    calls = []

    class FakeWinmm:
        def timeBeginPeriod(self, ms):
            calls.append(("begin", ms))
            return 0

        def timeEndPeriod(self, ms):
            calls.append(("end", ms))
            return 0

    class FakeCtypes:
        @staticmethod
        def WinDLL(*a, **k):
            return FakeWinmm()

    class FakeAtexit:
        @staticmethod
        def register(fn, arg):
            calls.append(("register", arg))

    monkeypatch.setitem(sys.modules, "ctypes", FakeCtypes())
    monkeypatch.setitem(sys.modules, "atexit", FakeAtexit())
    si.set_timer_resolution(1)
    assert calls == [("begin", 1), ("register", 1)]
