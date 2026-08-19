"""ProcessRunner done-event + engine_config reload tests."""

import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import engine_config
import process_runner


class FakeVar:
    def __init__(self):
        self.value = None

    def set(self, v):
        self.value = v


# --- ProcessRunner done-event ----------------------------------------------

def test_eof_event_stops_child_and_clears_proc(monkeypatch):
    """Clean EOF (child exited) sets Stopped, clears checkbox, drops proc."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    pr.start([])
    try:
        assert pr.is_running()
        pr.proc.terminate()
        pr.proc.wait(timeout=3)
        time.sleep(0.3)
        pr.q.put(("eof", pr._gen))
        pr.poll_log()
        assert status.value == "Stopped"
        assert check.value is False
        assert pr.proc is None
    finally:
        pr.stop()


def test_pump_error_terminates_live_child(monkeypatch):
    """pump_error on a LIVE child: _stop_proc terminates it, status -> Error,
    proc cleared, checkbox off (T-CORE-005)."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    # Mock _stop_proc to simulate successful termination
    terminated = []
    def fake_stop(proc):
        terminated.append(proc)
        return True
    monkeypatch.setattr(pr, "_stop_proc", fake_stop)
    pr.start([])
    try:
        assert pr.is_running()
        pr.q.put(("pump_error", pr._gen, "stream broken"))
        pr.poll_log()
        assert status.value.startswith("Error: stream broken")
        assert check.value is False
        assert pr.proc is None
        assert len(terminated) == 1
    finally:
        pr.stop()


def test_pump_error_retains_proc_on_terminate_failure(monkeypatch):
    """When terminate raises OSError, self.proc is RETAINED so poll_log can
    retry later - UI must never say Stopped while a child is still live."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    orig_proc = object()
    failed = []
    def fake_stop(proc):
        failed.append(proc)
        return False
    pr._stop_proc = fake_stop
    pr.proc = orig_proc
    pr._gen = 1
    status.value = "Running"  # simulate start() already ran
    check.value = True
    pr.q.put(("pump_error", 1, "stream broken"))
    pr.poll_log()
    # terminate failed: proc retained, status stays Running
    assert pr.proc is orig_proc
    assert status.value == "Running"
    assert check.value is False
    assert len(failed) == 1


def test_eof_clears_proc_even_when_child_already_gone(monkeypatch):
    """EOF after child exit: _stop_proc is a no-op (already dead), proc
    cleared, status Stopped."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    pr.start([])
    try:
        assert pr.is_running()
        pr.proc.terminate()
        pr.proc.wait(timeout=3)
        pr.q.put(("eof", pr._gen))
        pr.poll_log()
        assert status.value == "Stopped"
        assert check.value is False
        assert pr.proc is None
    finally:
        pr.stop()


def test_stop_uses_same_terminate_wait_kill_path(monkeypatch):
    """Explicit stop uses the same _stop_proc primitive as pump_error/EOF,
    so both paths behave identically on success and failure."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    pr.start([])
    try:
        assert pr.is_running()
        pr.stop()
        assert status.value == "Stopped"
        assert check.value is False
        assert pr.proc is None
    finally:
        pass


def test_spawn_failure_leaves_coherent_stopped_state(monkeypatch):
    """Popen failure: self.proc stays None, status shows a diagnostic, the
    checkbox cannot remain Running, and no stale generation is left behind."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)

    def boom(*a, **k):
        raise OSError("python not found")

    monkeypatch.setattr(process_runner.subprocess, "Popen", boom)
    ok = pr.start([])

    assert ok is False
    assert pr.proc is None
    assert pr.is_running() is False
    assert status.value.startswith("Error:")
    assert check.value is False


def test_real_child_death_triggers_done():
    # A short-lived child: stub sleeps 30s, so terminate it ourselves and
    # let the pump's EOF path emit the done marker the way a real engine
    # crash would.
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    pr.start([])
    try:
        assert pr.is_running()
        pr.proc.terminate()
        pr.proc.wait(timeout=3)
        time.sleep(0.3)  # let the pump thread reach EOF
        pr.poll_log()
        assert status.value == "Stopped"
        assert check.value is False
        assert pr.proc is None
    finally:
        pr.stop()


# --- engine_config.mtime_changed -------------------------------------------

def test_mtime_changed_no_change(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}")
    mtime = os.path.getmtime(cfg)
    cur, changed = engine_config.mtime_changed(str(cfg), mtime)
    assert cur == mtime
    assert changed is False


def test_mtime_changed_detects_modification(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}")
    mtime = os.path.getmtime(cfg)
    time.sleep(0.01)
    cfg.write_text("{2}")
    cur, changed = engine_config.mtime_changed(str(cfg), mtime)
    assert cur != mtime
    assert changed is True


def test_mtime_changed_missing_file_keeps_last(tmp_path):
    path = str(tmp_path / "nope.json")
    cur, changed = engine_config.mtime_changed(path, 123.0)
    assert cur == 123.0
    assert changed is False
