"""ProcessRunner done-event + engine_config reload tests."""

import os
import sys
import time
from pathlib import Path

import pytest

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
    """When terminate fails, self.proc is RETAINED so poll_log can retry later,
    and the monitor checkbox must stay ON (child still live) - UI must never
    report monitor OFF while a child is running (CORE-009 / W2-006)."""
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
    # terminate failed: proc retained, status stays Running, checkbox stays ON
    assert pr.proc is orig_proc
    assert status.value == "Running"
    assert check.value is True
    assert len(failed) == 1


def test_pump_error_keeps_checkbox_on_when_stop_fails(monkeypatch):
    """CORE-009: a pump_error whose child CANNOT be stopped must NOT flip the
    monitor checkbox OFF - the child is still live, so reporting monitor OFF
    would hide a running process and let a caller orphan it (W2-006)."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    orig_proc = object()

    def fake_stop(proc):
        return False
    pr._stop_proc = fake_stop
    pr.proc = orig_proc
    pr._gen = 1
    status.value = "Running"
    check.value = True
    pr.q.put(("pump_error", 1, "stream broken"))
    pr.poll_log()
    assert pr.proc is orig_proc
    assert check.value is True


def test_eof_keeps_checkbox_on_when_stop_fails(monkeypatch):
    """CORE-009: same guarantee for the EOF path - a failed stop keeps the
    monitor checkbox ON, not silently OFF."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)
    orig_proc = object()

    def fake_stop(proc):
        return False
    pr._stop_proc = fake_stop
    pr.proc = orig_proc
    pr._gen = 1
    status.value = "Running"
    check.value = True
    pr.q.put(("eof", 1))
    pr.poll_log()
    assert pr.proc is orig_proc
    assert check.value is True


def test_stop_keeps_checkbox_on_when_stop_fails(monkeypatch):
    """CORE-009: explicit stop() returning False (live child retained) must not
    flip the monitor checkbox OFF."""
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner("_stub_engine.py", status, last, check)

    class _Alive:
        def poll(self):
            return None  # still running
    orig_proc = _Alive()

    def fake_stop(proc):
        return False
    pr._stop_proc = fake_stop
    pr.proc = orig_proc
    pr._gen = 1
    status.value = "Running"
    check.value = True
    ok = pr.stop()
    assert ok is False
    assert pr.proc is orig_proc
    assert check.value is True


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


# --- engine_config.mtime_changed / load_config_revision ---------------------

def test_mtime_changed_no_change(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}")
    token = engine_config.config_revision(str(cfg))
    rev, changed = engine_config.mtime_changed(str(cfg), token)
    assert rev == token
    assert changed is False


def test_mtime_changed_detects_modification(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}")
    token = engine_config.config_revision(str(cfg))
    time.sleep(0.01)
    cfg.write_text("{2}")
    rev, changed = engine_config.mtime_changed(str(cfg), token)
    assert rev != token
    assert changed is True


def test_mtime_changed_missing_file_keeps_last(tmp_path):
    path = str(tmp_path / "nope.json")
    token = (123000000000, 10)
    rev, changed = engine_config.mtime_changed(path, token)
    assert rev == token
    assert changed is False


def test_mtime_changed_detects_size_only_change(tmp_path, monkeypatch):
    """CORE-006: the old mtime_changed discarded file size, so a rewrite that
    changed only the content (same mtime_ns) ran stale. The token now compares
    BOTH mtime and size - a size flip is detected."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}")
    token = engine_config.config_revision(str(cfg))
    # Same mtime_ns, different size: simulate a same-timestamp rewrite.
    fake_stat = type("S", (), {"st_mtime_ns": token[0], "st_size": token[1] + 1})()

    def _stat(p):
        return fake_stat
    monkeypatch.setattr(engine_config.os, "stat", _stat)
    rev, changed = engine_config.mtime_changed(str(cfg), token)
    assert changed is True
    assert rev[1] == token[1] + 1


def test_load_config_revision_binds_token_to_parsed_bytes(tmp_path):
    """CORE-006: the revision token returned is pinned to the exact bytes read
    (os.fstat on the open handle), not a separate post-read stat - so a
    concurrent rewrite between read and stat cannot bind a post-rewrite token to
    pre-rewrite bytes."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"window_title": "X", "poll_interval_sec": 1.0}')
    loaded, token = engine_config.load_config_revision(
        str(cfg), "accept_config.json")
    assert loaded["window_title"] == "X"
    assert token == engine_config.config_revision(str(cfg))


def test_load_config_revision_rejects_bad_json(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{not valid json")
    with pytest.raises(SystemExit):
        engine_config.load_config_revision(str(cfg), "accept_config.json")
