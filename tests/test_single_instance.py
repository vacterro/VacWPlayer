"""single_instance PID-identity tests (T-088): a stale reused PID pointing at
an unrelated process is never killed."""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import pytest

import single_instance as si


def test_pid_runs_our_script_accepts_own_cmdline(monkeypatch):
    calls = []
    expected = si._expected_script_path("accept.py")

    def fake_run(args, **kw):
        calls.append(args)
        return type("R", (), {
            "stdout": ("C:\\Python\\python.exe -u %s "
                       "--replace\r\n" % expected).encode("utf-8")})()

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


# --- T-144: identity is exact-token, never substring --------------------------

def test_split_command_line_respects_quotes():
    assert si._split_command_line(
        '"C:\\Program Files\\x\\accept.py" --replace') == [
        "C:\\Program Files\\x\\accept.py", "--replace"]
    assert si._split_command_line(
        'python -u C:\\app\\accept.py --replace') == [
        "python", "-u", "C:\\app\\accept.py", "--replace"]
    assert si._split_command_line('python "accept.py a.py"') == [
        "python", "accept.py a.py"]


def test_script_identity_is_exact_absolute_path():
    """T-158: identity is the normalized ABSOLUTE path of the script OUR
    instance launches. Basename equality is never proof - a same-named script
    in another directory must not be killable as ours."""
    expected = si._expected_script_path("accept.py")
    assert si._script_matches(expected, "accept.py") is True          # our exact path
    assert si._script_matches('"%s"' % expected, "accept.py") is True  # quoted
    assert si._script_matches(expected.upper(), "accept.py") is True   # case normalization
    assert si._script_matches("C:\\Other\\accept.py", "accept.py") is False  # other dir
    assert si._script_matches("accept.py", "accept.py") is True  # relative from our dir
    assert si._script_matches("C:\\app\\not_accept.py", "accept.py") is False
    assert si._script_matches("C:\\app\\accept.py.bak", "accept.py") is False
    assert si._script_matches("--accept.py", "accept.py") is False
    assert si._script_matches("C:\\app\\accept_runner.py", "accept.py") is False
    assert si._script_matches("", "accept.py") is False


def test_pid_runs_our_script_rejects_other_dir_same_basename(monkeypatch):
    """A stale PID file pointing at C:\\Other\\accept.py must NEVER be killed
    as our accept.py (T-158)."""
    def fake_run(args, **kw):
        return type("R", (), {
            "stdout": b"C:\\Python\\python.exe -u C:\\Other\\accept.py\r\n"})()
    monkeypatch.setattr(si.subprocess, "run", fake_run)
    assert si._pid_runs_our_script(7777, "accept") is False


def test_pid_runs_our_script_rejects_substring_lookalike(monkeypatch):
    """'not_accept.py' must not pass the accept.py identity check."""
    def fake_run(args, **kw):
        return type("R", (), {
            "stdout": b"C:\\Python\\python.exe -u C:\\app\\not_accept.py\r\n"})()
    monkeypatch.setattr(si.subprocess, "run", fake_run)
    assert si._pid_runs_our_script(4242, "accept") is False


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
    monkeypatch.setattr(si.win32process, "GetModuleFileNameEx", lambda *a: "C:\\Python\\python.exe")
    monkeypatch.setattr(si.win32process, "GetProcessId", lambda h: 123)
    monkeypatch.setattr(si.win32api, "TerminateProcess", lambda *a: killed.append("KILL"))
    monkeypatch.setattr(si.win32event, "WaitForSingleObject", lambda *a: None)
    monkeypatch.setattr(si.win32api, "CloseHandle", lambda *a: None)

    si._kill_previous_holder("accept")
    assert killed == ["KILL"]


def test_kill_previous_holder_rejects_reused_foreign_python(monkeypatch, capsys):
    """CORE-001: a PID reused by a foreign python.exe (our managed process
    exited, Windows recycled the PID) must NOT be terminated. Ownership is
    re-verified against the pinned handle, and the foreign command line fails
    the script check."""
    killed = []
    monkeypatch.setattr(si.os.path, "isfile", lambda p: True)
    # The (reused) pid's command line is NOT our script -> ownership fails.
    monkeypatch.setattr(si, "_pid_runs_our_script", lambda pid, name: False)

    class F:
        def read(self):
            return "123"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    monkeypatch.setattr("builtins.open", lambda path, *a, **k: F())
    monkeypatch.setattr(si.win32api, "OpenProcess", lambda *a: 9)
    # Foreign python image - passes the image gate, must still be refused.
    monkeypatch.setattr(si.win32process, "GetModuleFileNameEx",
                        lambda *a: "C:\\Python\\python.exe")
    monkeypatch.setattr(si.win32process, "GetProcessId", lambda h: 123)
    monkeypatch.setattr(si.win32api, "TerminateProcess", lambda *a: killed.append("KILL"))
    monkeypatch.setattr(si.win32event, "WaitForSingleObject", lambda *a: None)
    monkeypatch.setattr(si.win32api, "CloseHandle", lambda *a: None)

    si._kill_previous_holder("accept")
    assert "KILL" not in killed
    assert "identity not proven" in capsys.readouterr().err


def test_kill_previous_holder_rejects_reused_foreign_ahk(monkeypatch, capsys):
    """CORE-001: a PID reused by a foreign AutoHotkey process must NOT be
    terminated. Image-name equality is not ownership."""
    killed = []
    monkeypatch.setattr(si.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(si, "_pid_runs_our_script", lambda pid, name: False)

    class F:
        def read(self):
            return "123"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    monkeypatch.setattr("builtins.open", lambda path, *a, **k: F())
    monkeypatch.setattr(si.win32api, "OpenProcess", lambda *a: 9)
    monkeypatch.setattr(si.win32process, "GetModuleFileNameEx",
                        lambda *a: "C:\\Other\\AutoHotkeyU64.exe")
    monkeypatch.setattr(si.win32process, "GetProcessId", lambda h: 123)
    monkeypatch.setattr(si.win32api, "TerminateProcess", lambda *a: killed.append("KILL"))
    monkeypatch.setattr(si.win32event, "WaitForSingleObject", lambda *a: None)
    monkeypatch.setattr(si.win32api, "CloseHandle", lambda *a: None)

    si._kill_previous_holder("accept")
    assert "KILL" not in killed
    assert "identity not proven" in capsys.readouterr().err


# --- W2-006: pid-publish failure must fail closed, not silently start ---------

def test_ensure_single_instance_fails_closed_when_pid_publish_fails(monkeypatch):
    """A mutex-holder whose pid file can never be written (disk full / denied)
    must not start: the just-acquired authoritative mutex is released and
    startup raises BEFORE any runtime side effects - otherwise a replace=True
    run could never reclaim the lock through the missing pid hint."""
    closed = []
    monkeypatch.setattr(si.win32event, "CreateMutex", lambda *a: 5)
    monkeypatch.setattr(si.win32api, "GetLastError", lambda: 0)
    monkeypatch.setattr(si, "_write_pid", lambda name: False)
    monkeypatch.setattr(si.win32api, "CloseHandle",
                        lambda h: closed.append(h) or None)
    try:
        with pytest.raises(RuntimeError):
            si.ensure_single_instance("accept")
    finally:
        if 5 in si._handles:
            si._handles.remove(5)
    assert closed == [5], "just-acquired mutex must be released on publish failure"


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


# --- T-143: target watchdog must not preempt GUI cleanup ---------------------

def test_watchdog_seen_alive_any_duration_establishes():
    """A target observed alive for ANY duration sets seen_alive - the
    min_uptime window is absence-grace only, never a seen_alive gate."""
    st = si._watchdog_state(grace_ticks=2, min_uptime_sec=15.0)
    assert si._watchdog_tick(st, 5.0, True) == "alive"  # seen at tick 5 (< 15)
    assert st["seen_alive"] is True
    assert si._watchdog_tick(st, 10.0, False) == "wait"  # absence during grace
    assert si._watchdog_tick(st, 18.0, False) == "wait"  # grace done, pending=1
    assert si._watchdog_tick(st, 21.0, False) == "fire"  # pending >= grace_ticks


def test_watchdog_never_saw_target_ignores_absence():
    st = si._watchdog_state(grace_ticks=2, min_uptime_sec=15.0)
    for t in (3.0, 6.0, 9.0):
        assert si._watchdog_tick(st, t, False) == "wait"
    assert st["seen_alive"] is False


def test_watchdog_alive_again_resets_pending():
    st = si._watchdog_state(grace_ticks=2, min_uptime_sec=15.0)
    si._watchdog_tick(st, 5.0, True)
    si._watchdog_tick(st, 18.0, False)  # pending=1
    assert si._watchdog_tick(st, 21.0, True) == "alive"  # back alive
    assert st["pending_ticks"] == 0
    assert si._watchdog_tick(st, 24.0, False) == "wait"  # pending=1 again


def test_watchdog_fires_callback_once_then_bounded_hard_exit(monkeypatch):
    """on_gone owns shutdown; the watchdog invokes it once and only hard-exits
    after a bounded cleanup window - never os._exit() before the callback ran."""
    import time as _time
    real_sleep = _time.sleep  # si.time IS the time module - capture before patch
    alive = [True] + [False] * 20

    def _alive(exes):
        return alive.pop(0) if alive else False

    sleeps = []
    fired = []
    exited = []
    monkeypatch.setattr(si, "_target_any_alive", _alive)
    monkeypatch.setattr(si.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(si.os, "_exit", lambda c: exited.append(c) or (_ for _ in ()).throw(SystemExit))

    si.start_target_watchdog(["HD-Player.exe"], lambda: fired.append(1),
                             interval_sec=3.0, grace_ticks=2,
                             min_uptime_sec=6.0, hard_exit_timeout_sec=4.0)
    deadline = _time.time() + 2.0
    while fired != [1] and _time.time() < deadline:
        real_sleep(0.01)

    assert len(fired) == 1           # callback invoked exactly once
    assert exited == [0]             # hard-exit fallback still lands
    assert 4.0 in sleeps            # bounded cleanup window observed


# --- CORE-002: parent watchdog must terminate the engine on parent death ---

def test_parent_watchdog_terminates_on_parent_death(monkeypatch):
    """A normal parent death must exit the engine process, not merely return
    from the watcher thread (CORE-002). Returning would strand an orphaned
    engine still holding its mutex and firing input after a GUI crash."""
    exited = []
    monkeypatch.setattr(si.win32api, "OpenProcess", lambda *a: 7)
    # WAIT_OBJECT_0 on the first check -> parent is gone.
    monkeypatch.setattr(si.win32event, "WaitForSingleObject", lambda h, t: 0)
    monkeypatch.setattr(si.win32api, "CloseHandle", lambda h: None)
    monkeypatch.setattr(si.time, "sleep", lambda s: None)
    monkeypatch.setattr(si.os, "_exit",
                        lambda c: exited.append(c) or (_ for _ in ()).throw(SystemExit))

    t = si.start_parent_watchdog(interval_sec=1.0)
    t.join(timeout=2.0)
    assert exited == [0], "engine must os._exit(0) when parent dies"


def test_parent_watchdog_keeps_watching_while_parent_alive(monkeypatch):
    """A live parent (the blocking wait does not return) must NOT terminate
    the engine."""
    import time as _time
    exited = []
    monkeypatch.setattr(si.win32api, "OpenProcess", lambda *a: 7)
    # PERF-006: the watcher now blocks on the pinned handle. A live parent
    # means the wait never returns - simulate with a sleep beyond the join.
    monkeypatch.setattr(si.win32event, "WaitForSingleObject",
                        lambda h, t: _time.sleep(5.0) or 0x102)
    monkeypatch.setattr(si.win32api, "CloseHandle", lambda h: None)
    monkeypatch.setattr(si.os, "_exit",
                        lambda c: exited.append(c) or (_ for _ in ()).throw(SystemExit))

    t = si.start_parent_watchdog(interval_sec=1.0)
    t.join(timeout=1.0)
    assert exited == [], "engine must NOT exit while parent is still alive"


# --- CORE-004 / PERF-001: target absence tri-state + early-exit scan ---

def test_target_absent_complete_snapshot_returns_false(monkeypatch):
    """CORE-004: a successful complete name snapshot with no target image is
    authoritative absence -> False, even with protected/system PIDs present."""
    monkeypatch.setattr(si, "_snapshot_image_names",
                        lambda: {"protected.exe", "system.exe", "svchost.exe"})
    assert si._target_any_alive(["HD-Player.exe"]) is False


def test_target_snapshot_failure_returns_none(monkeypatch):
    """A genuinely failed snapshot enumeration stays None/UNKNOWN."""
    monkeypatch.setattr(si, "_snapshot_image_names", lambda: None)
    assert si._target_any_alive(["HD-Player.exe"]) is None


def test_target_present_snapshot_returns_true(monkeypatch):
    """CORE-004: a snapshot containing the target image returns True."""
    monkeypatch.setattr(si, "_snapshot_image_names",
                        lambda: {"other.exe", "hd-player.exe", "svchost.exe"})
    assert si._target_any_alive(["HD-Player.exe"]) is True


def test_target_watchdog_fires_when_target_gone(monkeypatch):
    """End-to-end (CORE-004): once the target was seen alive, fully-observed
    absence ticks fire the shutdown after the configured grace period."""
    import time as _time
    real_sleep = _time.sleep
    fired = []
    exited = []
    sleeps_append = []
    # One PID observed per scan. First scan: target present. Then: target gone
    # but the scan is fully observed (complete=True) -> False advances the
    # disappearance counter and eventually fires.
    snap = [{"hd-player.exe", "other.exe"}, {"other.exe", "system.exe"}]
    it = iter(snap)

    def _next_snap():
        try:
            return next(it)
        except StopIteration:
            return {"other.exe", "system.exe"}  # repeat absent after exhausted
    monkeypatch.setattr(si, "_snapshot_image_names", _next_snap)
    monkeypatch.setattr(si.time, "sleep", lambda s: sleeps_append.append(s))
    monkeypatch.setattr(si.os, "_exit",
                        lambda c: exited.append(c) or (_ for _ in ()).throw(SystemExit))

    si.start_target_watchdog(["HD-Player.exe"], lambda: fired.append(1),
                             interval_sec=3.0, grace_ticks=2,
                             min_uptime_sec=6.0, hard_exit_timeout_sec=4.0)
    deadline = _time.time() + 3.0
    while fired != [1] and _time.time() < deadline:
        real_sleep(0.01)
    assert len(fired) == 1


def test_target_watchdog_incomplete_scan_does_not_advance(monkeypatch):
    """CORE-004: repeated UNKNOWN (incomplete-scan) observations must NOT
    advance the disappearance counter, so the watchdog never fires on
    observations that cannot prove absence."""
    import time as _time
    real_sleep = _time.sleep
    fired = []
    exited = []
    sleeps_append = []
    # First scan: target present. Then: snapshot enumeration genuinely fails
    # (None -> UNKNOWN) -> pending_ticks stays 0.
    calls = [0]
    monkeypatch.setattr(
        si, "_snapshot_image_names",
        lambda: (calls.__setitem__(0, calls[0] + 1) or
                 ({"hd-player.exe"} if calls[0] == 1 else None)))
    monkeypatch.setattr(si.time, "sleep", lambda s: sleeps_append.append(s))
    monkeypatch.setattr(si.os, "_exit",
                        lambda c: exited.append(c) or (_ for _ in ()).throw(SystemExit))

    si.start_target_watchdog(["HD-Player.exe"], lambda: fired.append(1),
                             interval_sec=3.0, grace_ticks=2,
                             min_uptime_sec=6.0, hard_exit_timeout_sec=4.0)
    real_sleep(0.3)
    assert fired == [] and exited == [], "UNKNOWN observations must not fire"


def test_target_unrelated_protected_process_does_not_block_absent(monkeypatch):
    """CORE-004: unrelated protected/system processes in the snapshot do not
    prevent a proven-absent result (False), unlike the old per-PID-open scan
    where one unobservable PID poisoned the whole scan to UNKNOWN."""
    monkeypatch.setattr(
        si, "_snapshot_image_names",
        lambda: {"system.exe", "svchost.exe", "protected.exe", "winlogon.exe"})
    assert si._target_any_alive(["HD-Player.exe"]) is False


def test_target_absent_ticks_fire_despite_protected_processes(monkeypatch):
    """CORE-004: after the target was seen, two proven-absent ticks fire
    shutdown even when protected/system processes populate the snapshot."""
    import time as _time
    real_sleep = _time.sleep
    fired = []
    exited = []
    sleeps_append = []
    calls = [0]
    monkeypatch.setattr(
        si, "_snapshot_image_names",
        lambda: (calls.__setitem__(0, calls[0] + 1) or
                 ({"hd-player.exe"} if calls[0] == 1
                  else {"system.exe", "svchost.exe", "protected.exe"})))
    monkeypatch.setattr(si.time, "sleep", lambda s: sleeps_append.append(s))
    monkeypatch.setattr(si.os, "_exit",
                        lambda c: exited.append(c) or (_ for _ in ()).throw(SystemExit))

    si.start_target_watchdog(["HD-Player.exe"], lambda: fired.append(1),
                             interval_sec=3.0, grace_ticks=2,
                             min_uptime_sec=6.0, hard_exit_timeout_sec=4.0)
    deadline = _time.time() + 3.0
    while fired != [1] and _time.time() < deadline:
        real_sleep(0.01)
    assert len(fired) == 1


def test_target_snapshot_empty_returns_false(monkeypatch):
    """CORE-004: an empty successful snapshot is authoritative absence."""
    monkeypatch.setattr(si, "_snapshot_image_names", lambda: set())
    assert si._target_any_alive(["HD-Player.exe"]) is False


def test_target_watchdog_cancel_stops_firing(monkeypatch):
    """W2-002: a cancelled watcher generation must not fire on_gone nor
    hard-exit after replacement - old generations are inert."""
    import time as _time
    real_sleep = _time.sleep
    fired = []
    exited = []
    sleeps_append = []
    # Target seen alive once, then fully-observed absent - without cancellation
    # this would fire after grace_ticks. Real interval sleep (NOT patched) so
    # stop() below deterministically lands before the first fire cycle.
    calls = [0]
    monkeypatch.setattr(
        si, "_snapshot_image_names",
        lambda: (calls.__setitem__(0, calls[0] + 1) or
                 ({"hd-player.exe"} if calls[0] == 1 else {"other.exe"})))
    monkeypatch.setattr(si.os, "_exit",
                        lambda c: exited.append(c) or (_ for _ in ()).throw(SystemExit))

    handle = si.start_target_watchdog(["HD-Player.exe"], lambda: fired.append(1),
                                      interval_sec=3.0, grace_ticks=2,
                                      min_uptime_sec=0.0, hard_exit_timeout_sec=4.0)
    handle.stop()
    real_sleep(0.3)
    assert fired == [] and exited == [], "cancelled watcher must be inert"
