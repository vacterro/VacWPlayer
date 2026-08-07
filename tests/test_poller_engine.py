"""Behavioral tests for poller_engine.run_poller (shared engine loop).

run_poller is an infinite loop; time.sleep is stubbed with a sentinel that
raises KeyboardInterrupt after N calls so each test walks a bounded number of
loop iterations and asserts the sleep pattern it produced.
"""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import poller_engine


class SleepSentinel:
    def __init__(self, stop_after):
        self.stop_after = stop_after
        self.calls = 0
        self.sleeps = []

    def __call__(self, secs):
        self.calls += 1
        self.sleeps.append(secs)
        if self.calls >= self.stop_after:
            raise KeyboardInterrupt


def _cfg(window_title="GameWindow"):
    return {"window_title": window_title, "poll_interval_sec": 1.0,
            "click_cooldown_sec": 3.0}


def _run(monkeypatch, cfg=None, scan_result=False, mtime=(1.0, False),
         find_ok=True, stop_after=3):
    cfg = cfg or _cfg()
    sleep = SleepSentinel(stop_after)
    find_calls = []
    scan_calls = {"n": 0}
    build_calls = {"n": 0}

    def _find(title):
        find_calls.append(title)
        if not find_ok:
            raise RuntimeError("no window")
        return 12345

    def _scan(hwnd, c, targets):
        scan_calls["n"] += 1
        return scan_result

    def _build(c):
        build_calls["n"] += 1
        return ["t1"]

    monkeypatch.setattr(poller_engine.time, "sleep", sleep)
    monkeypatch.setattr(poller_engine.single_instance, "ensure_single_instance",
                        lambda *a, **k: None)
    monkeypatch.setattr(poller_engine.single_instance, "start_parent_watchdog",
                        lambda: None)
    monkeypatch.setattr(poller_engine.window_ctl, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(poller_engine, "load_config", lambda p, n: cfg)
    monkeypatch.setattr(poller_engine.os.path, "getmtime", lambda p: 1.0)
    monkeypatch.setattr(poller_engine.engine_config, "mtime_changed",
                        lambda p, m: mtime)
    monkeypatch.setattr(poller_engine.capture, "find_window", _find)
    monkeypatch.setattr(poller_engine.win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(poller_engine.capture, "is_minimized", lambda h: False)

    poller_engine.run_poller(
        "test", "cfg.json", "cfg.json",
        build_targets=_build, scan_targets=_scan,
        startup=lambda c, t: "started", reload_msg=lambda c, t: None,
        poll_default=1.0, cooldown_default=3.0)

    return sleep, {"find": find_calls, "scan": scan_calls["n"],
                   "build": build_calls["n"]}


def test_click_uses_cooldown_sleep(monkeypatch):
    sleep, _ = _run(monkeypatch, scan_result=True)
    assert all(s == 3.0 for s in sleep.sleeps)


def test_no_match_uses_poll_interval(monkeypatch):
    sleep, _ = _run(monkeypatch, scan_result=False)
    assert all(s == 1.0 for s in sleep.sleeps)


def test_grab_failure_retries_keeps_hwnd(monkeypatch):
    # scan returns None on a transient capture failure: poll-retry, no re-acquire.
    sleep, calls = _run(monkeypatch, scan_result=None)
    assert all(s == 1.0 for s in sleep.sleeps)
    assert len(calls["find"]) == 1


def test_config_reload_rebuilds_targets(monkeypatch):
    _, calls = _run(monkeypatch, mtime=(2.0, True))
    assert calls["build"] >= 2


def test_window_title_change_reacquires_hwnd(monkeypatch):
    cfg_seq = [_cfg("A"), _cfg("B")]
    load_calls = []

    def _load(p, n):
        idx = min(len(cfg_seq) - 1, len(load_calls))
        load_calls.append(idx)
        return cfg_seq[idx]

    state = {"calls": 0}

    def _changed(p, m):
        state["calls"] += 1
        return (2.0, state["calls"] == 2)

    sleep = SleepSentinel(3)
    find_calls = []

    def _find(title):
        find_calls.append(title)
        return 12345

    monkeypatch.setattr(poller_engine.time, "sleep", sleep)
    monkeypatch.setattr(poller_engine.single_instance, "ensure_single_instance",
                        lambda *a, **k: None)
    monkeypatch.setattr(poller_engine.single_instance, "start_parent_watchdog",
                        lambda: None)
    monkeypatch.setattr(poller_engine.window_ctl, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(poller_engine, "load_config", _load)
    monkeypatch.setattr(poller_engine.os.path, "getmtime", lambda p: 1.0)
    monkeypatch.setattr(poller_engine.engine_config, "mtime_changed", _changed)
    monkeypatch.setattr(poller_engine.capture, "find_window", _find)
    monkeypatch.setattr(poller_engine.win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(poller_engine.capture, "is_minimized", lambda h: False)

    poller_engine.run_poller(
        "test", "cfg.json", "cfg.json",
        build_targets=lambda c: ["t1"], scan_targets=lambda h, c, t: False,
        startup=lambda c, t: "started", reload_msg=lambda c, t: None)

    # title change -> hwnd dropped and re-acquired against the new title
    assert find_calls[0] == "A"
    assert "B" in find_calls


def test_acquire_failure_retries(monkeypatch):
    sleep, calls = _run(monkeypatch, find_ok=False)
    assert all(s == 1.0 for s in sleep.sleeps)
    assert len(calls["find"]) == 3


def test_lost_window_resets_and_reacquires(monkeypatch):
    # The sentinel sleep (raising KI) must NOT fire inside run_poller's outer
    # except-Exception handler - an exception raised in an except clause is
    # not caught by the same try. So this test ends the loop from the scan
    # callback (main try body) instead.
    scan_calls = {"n": 0}

    def _scan(hwnd, c, targets):
        scan_calls["n"] += 1
        if scan_calls["n"] >= 3:
            raise KeyboardInterrupt
        raise RuntimeError("window gone")

    monkeypatch.setattr(poller_engine.time, "sleep", SleepSentinel(999))
    monkeypatch.setattr(poller_engine.single_instance, "ensure_single_instance",
                        lambda *a, **k: None)
    monkeypatch.setattr(poller_engine.single_instance, "start_parent_watchdog",
                        lambda: None)
    monkeypatch.setattr(poller_engine.window_ctl, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(poller_engine, "load_config", lambda p, n: _cfg())
    monkeypatch.setattr(poller_engine.os.path, "getmtime", lambda p: 1.0)
    monkeypatch.setattr(poller_engine.engine_config, "mtime_changed",
                        lambda p, m: (1.0, False))
    find_calls = []

    def _find(title):
        find_calls.append(title)
        return 12345

    monkeypatch.setattr(poller_engine.capture, "find_window", _find)
    monkeypatch.setattr(poller_engine.win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(poller_engine.capture, "is_minimized", lambda h: False)

    poller_engine.run_poller(
        "test", "cfg.json", "cfg.json",
        build_targets=lambda c: ["t1"], scan_targets=_scan,
        startup=lambda c, t: "started", reload_msg=lambda c, t: None)

    # every lost window resets hwnd and re-acquires on the next iteration
    assert len(find_calls) == 3
