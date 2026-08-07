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

def test_done_event_when_child_exits():
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    pr.start([])
    try:
        assert pr.is_running()
    finally:
        pr.stop()

    # done marker arrives on the queue; poll_log must apply it
    pr.q.put(("done", pr._gen))
    pr.poll_log()
    assert status.value == "Stopped"
    assert check.value is False
    assert pr.proc is None


def test_done_event_ignores_stale_generation():
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    pr.start([])
    gen = pr._gen
    try:
        assert pr.is_running()
    finally:
        pr.stop()

    # done from an older generation must NOT touch the current state
    pr.q.put(("done", gen - 1))
    pr.poll_log()
    assert status.value == "Stopped"  # set by stop(), not by the stale done
    assert pr.proc is None


def test_done_event_lines_update_last_line():
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    pr.start([])
    try:
        assert pr.is_running()
    finally:
        pr.stop()

    pr.q.put(("line", pr._gen, "hello-world"))
    pr.poll_log()
    assert last.value == "hello-world"


def test_stale_generation_line_ignored():
    """A line from an older pump must never overwrite the current UI line
    (T-085: stale events carry a generation and poll_log discards them)."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    pr.start([])
    gen = pr._gen
    try:
        assert pr.is_running()
    finally:
        pr.stop()

    pr.last_line_var.value = "current"
    pr.q.put(("line", gen - 1, "stale line from old process"))
    pr.poll_log()
    assert last.value == "current"  # untouched by the stale event


def test_stale_generation_done_ignored():
    """A done marker from an older pump must not stop the current process
    (T-085 regression)."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    pr.start([])
    gen = pr._gen
    try:
        assert pr.is_running()
        pr.q.put(("done", gen - 1))
        pr.poll_log()
        assert pr.is_running()          # still running
        assert status.value == "Running"
    finally:
        pr.stop()


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
