"""W2-002 regression: HWND identity must be bound to title + owning PID, not just
liveness (IsWindow).

A destroyed target window can have its numeric handle reclaimed by an unrelated
FOREIGN window. That foreign window still passes win32gui.IsWindow, so the old
``if not hwnd or not win32gui.IsWindow(hwnd)`` reacquire test would keep scanning
and clicking the wrong window. The fix binds every acquired handle to the
(target title, owning PID) it was found with and revalidates before each
scan/action; a mismatch invalidates the handle and forces a re-acquire.
"""

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import capture  # noqa: E402
import poller_engine  # noqa: E402


# --------------------------------------------------------------------------
# Pure identity helpers (no real windows; stub the win32 calls).
# --------------------------------------------------------------------------

def _patch_win32(monkeypatch, is_window=True, title="GameWindow", pid=100):
    monkeypatch.setattr(capture.win32gui, "IsWindow", lambda h: is_window)
    monkeypatch.setattr(capture.win32gui, "GetWindowText", lambda h: title)
    monkeypatch.setattr(capture.win32process, "GetWindowThreadProcessId",
                        lambda h: (0, pid))


def test_is_same_window_none_handle_false(monkeypatch):
    _patch_win32(monkeypatch)
    assert capture.is_same_window(None, "GameWindow", 100) is False
    assert capture.is_same_window(0, "GameWindow", 100) is False


def test_is_same_window_not_window_false(monkeypatch):
    # Handle is valid-looking but the OS says it is no longer a window.
    _patch_win32(monkeypatch, is_window=False)
    assert capture.is_same_window(12345, "GameWindow", 100) is False


def test_is_same_window_title_mismatch_false(monkeypatch):
    # Foreign window reused the handle: title no longer matches -> mismatch.
    _patch_win32(monkeypatch, title="SomeOtherApp")
    assert capture.is_same_window(12345, "GameWindow", 100) is False


def test_is_same_window_pid_mismatch_false(monkeypatch):
    # Foreign window reused the handle: different owning PID -> mismatch.
    _patch_win32(monkeypatch, pid=999)
    assert capture.is_same_window(12345, "GameWindow", 100) is False


def test_is_same_window_full_match_true(monkeypatch):
    _patch_win32(monkeypatch, title="GameWindow", pid=100)
    assert capture.is_same_window(12345, "GameWindow", 100) is True


def test_find_window_identity_returns_pid(monkeypatch):
    monkeypatch.setattr(capture, "find_window", lambda t: 12345)
    monkeypatch.setattr(capture, "window_pid", lambda h: 777)
    assert capture.find_window_identity("GameWindow") == (12345, 777)


def test_find_window_identity_propagates_not_found(monkeypatch):
    def _boom(t):
        raise RuntimeError("window not found: %s" % t)
    monkeypatch.setattr(capture, "find_window", _boom)
    with pytest.raises(RuntimeError):
        capture.find_window_identity("GameWindow")


# --------------------------------------------------------------------------
# Integration: run_poller must re-acquire when a foreign window reuses the
# numeric handle (instead of scanning the wrong window).
# --------------------------------------------------------------------------

class SleepSentinel:
    def __init__(self, stop_after):
        self.stop_after = stop_after
        self.calls = 0

    def __call__(self, secs):
        self.calls += 1
        if self.calls >= self.stop_after:
            raise KeyboardInterrupt


def _cfg(window_title="GameWindow"):
    return {"window_title": window_title, "poll_interval_sec": 1.0,
            "click_cooldown_sec": 3.0}


def test_run_poller_reacquires_on_handle_reuse(monkeypatch):
    cfg = _cfg()
    sleep = SleepSentinel(8)

    H = 12345
    REAL_PID = 100
    FOREIGN_PID = 200
    state = {"reused": False}
    find_identity_calls = []
    scans = {"n": 0, "bound_pids": []}
    last_pid = [REAL_PID]

    def _find_identity(title):
        find_identity_calls.append(title)
        pid = FOREIGN_PID if state["reused"] else REAL_PID
        last_pid[0] = pid
        return H, pid

    def _is_same(h, title, pid):
        if h != H:
            return False
        return pid == (FOREIGN_PID if state["reused"] else REAL_PID)

    def _scan(h, c, targets):
        scans["n"] += 1
        # The pid bound at scan time must be the FRESHLY re-acquired one, never
        # a stale identity carried across a handle reuse.
        scans["bound_pids"].append(last_pid[0])
        # First successful scan under the real PID: now simulate a foreign window
        # reclaiming the numeric handle.
        if scans["n"] == 1:
            state["reused"] = True
        return False

    monkeypatch.setattr(poller_engine.time, "sleep", sleep)
    monkeypatch.setattr(poller_engine.single_instance, "ensure_single_instance",
                        lambda *a, **k: None)
    monkeypatch.setattr(poller_engine.single_instance, "start_parent_watchdog",
                        lambda: None)
    monkeypatch.setattr(poller_engine.window_ctl, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(poller_engine.engine_config, "load_config_revision",
                        lambda p, n: (cfg, (1, 1)))
    monkeypatch.setattr(poller_engine, "reload_candidate",
                        lambda p, n: (cfg, None))
    monkeypatch.setattr(poller_engine.os.path, "getmtime", lambda p: 1.0)
    monkeypatch.setattr(poller_engine.engine_config, "mtime_changed",
                        lambda p, m: (1.0, False))
    monkeypatch.setattr(poller_engine.capture, "find_window_identity",
                        _find_identity)
    monkeypatch.setattr(poller_engine.capture, "is_same_window", _is_same)
    monkeypatch.setattr(poller_engine.capture, "find_window", lambda t: H)
    monkeypatch.setattr(poller_engine.win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(poller_engine.capture, "is_minimized", lambda h: False)

    poller_engine.run_poller(
        "test", "cfg.json", "cfg.json",
        build_targets=lambda c: ["t1"], scan_targets=_scan,
        startup=lambda c, t: "started", reload_msg=lambda c, t: None)

    # The loop acquired the handle, ran a few scans under the real PID...
    assert scans["n"] >= 1
    assert all(p == REAL_PID for p in scans["bound_pids"][:1])
    # ...then the foreign window reclaimed the handle on the next poll...
    state["reused"] = True
    # re-acquire happened: the handle was re-bound before any further scan.
    assert len(find_identity_calls) >= 2
    # Every subsequent scan ran with the freshly re-acquired (foreign) PID,
    # i.e. the loop re-validated identity and never scanned under the STALE
    # real PID after the reuse was detected.
    assert all(p == FOREIGN_PID for p in scans["bound_pids"][1:])


def test_run_poller_reacquire_failure_skips_scan(monkeypatch):
    """When a reused handle cannot be re-acquired (find raises), the loop must
    sleep and retry WITHOUT scanning - it must never act on a stale handle."""
    cfg = _cfg()
    sleep = SleepSentinel(4)

    H = 12345
    state = {"reused": False}
    scans = {"n": 0}
    find_identity_calls = []

    def _find_identity(title):
        find_identity_calls.append(title)
        if state["reused"]:
            raise RuntimeError("window not found: %s" % title)
        return H, 100

    def _is_same(h, title, pid):
        return h == H and not state["reused"]

    def _scan(h, c, targets):
        scans["n"] += 1
        if scans["n"] == 1:
            state["reused"] = True
        return False

    monkeypatch.setattr(poller_engine.time, "sleep", sleep)
    monkeypatch.setattr(poller_engine.single_instance, "ensure_single_instance",
                        lambda *a, **k: None)
    monkeypatch.setattr(poller_engine.single_instance, "start_parent_watchdog",
                        lambda: None)
    monkeypatch.setattr(poller_engine.window_ctl, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(poller_engine.engine_config, "load_config_revision",
                        lambda p, n: (cfg, (1, 1)))
    monkeypatch.setattr(poller_engine, "reload_candidate",
                        lambda p, n: (cfg, None))
    monkeypatch.setattr(poller_engine.os.path, "getmtime", lambda p: 1.0)
    monkeypatch.setattr(poller_engine.engine_config, "mtime_changed",
                        lambda p, m: (1.0, False))
    monkeypatch.setattr(poller_engine.capture, "find_window_identity",
                        _find_identity)
    monkeypatch.setattr(poller_engine.capture, "is_same_window", _is_same)
    monkeypatch.setattr(poller_engine.capture, "find_window", lambda t: H)
    monkeypatch.setattr(poller_engine.win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(poller_engine.capture, "is_minimized", lambda h: False)

    poller_engine.run_poller(
        "test", "cfg.json", "cfg.json",
        build_targets=lambda c: ["t1"], scan_targets=_scan,
        startup=lambda c, t: "started", reload_msg=lambda c, t: None)

    # At least one scan happened before the reuse...
    assert scans["n"] >= 1
    # ...then the reuse made re-acquire fail: it tried again, never scanned a
    # stale handle after the first failure.
    assert len(find_identity_calls) >= 2
