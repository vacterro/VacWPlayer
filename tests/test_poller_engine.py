"""Behavioral tests for poller_engine.run_poller (shared engine loop).

run_poller is an infinite loop; time.sleep is stubbed with a sentinel that
raises KeyboardInterrupt after N calls so each test walks a bounded number of
loop iterations and asserts the sleep pattern it produced.
"""

import sys
from pathlib import Path

import numpy as np

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


# --- T-083: (0,0) is a valid match location ---------------------------------

def test_click_template_match_clicks_at_top_left(monkeypatch):
    """A threshold-passing match at the top-left corner (0,0) MUST click -
    loc=(0,0) is a real location, not a 'no match' sentinel."""
    clicks = []
    monkeypatch.setattr(poller_engine, "best_template_match",
                        lambda gray, entry: (0.9, (0, 0), (10, 20)))
    monkeypatch.setattr(poller_engine.window_ctl, "click_at",
                        lambda h, x, y, button="left": clicks.append((x, y)))
    entry = {"name": "t", "threshold": 0.75}
    assert poller_engine.click_template_match(123, "gray", entry) is True
    assert clicks == [(10, 5)]  # cx = 0 + 20//2, cy = 0 + 10//2


def test_click_template_match_no_match_returns_false(monkeypatch):
    """loc/size None means no template matched - no click."""
    monkeypatch.setattr(poller_engine, "best_template_match",
                        lambda gray, entry: (0.0, None, None))
    entry = {"name": "t", "threshold": 0.75}
    assert poller_engine.click_template_match(123, "gray", entry) is False


# --- T-127: region-based cheap scan (grab_region, not full-window grab) -----

def test_click_template_match_origin_offsets_click(monkeypatch):
    """origin shifts the click into window space when gray is a crop."""
    clicks = []
    monkeypatch.setattr(poller_engine, "best_template_match",
                        lambda gray, entry: (0.9, (0, 0), (10, 20)))
    monkeypatch.setattr(poller_engine.window_ctl, "click_at",
                        lambda h, x, y, button="left": clicks.append((x, y)))
    entry = {"name": "t", "threshold": 0.75}
    assert poller_engine.click_template_match(123, "gray", entry, origin=(5, 7)) is True
    assert clicks == [(15, 12)]  # 0 + 10//2 + 5, 0 + 20//2 + 7


def test_has_regions_requires_all_nonempty():
    assert poller_engine.has_regions([]) is False
    assert poller_engine.has_regions([{"name": "a"}]) is False
    assert poller_engine.has_regions(
        [{"name": "a"}, {"name": "b", "region": [0, 0, 1, 1]}]) is False
    assert poller_engine.has_regions(
        [{"name": "a", "region": [0, 0, 1, 1]}]) is True


def test_scan_by_region_grabs_union_once_and_offsets(monkeypatch):
    """One grab_region of the union box; each entry matches on its own crop
    with an origin offset back into window space."""
    grabs = []
    monkeypatch.setattr(poller_engine.capture, "grab_region",
                        lambda h, r: grabs.append(r) or np.zeros((30, 30, 3), dtype=np.uint8))
    seen = []

    def fake_match(hwnd, gray, entry, origin=(0, 0)):
        seen.append((entry["name"], origin, gray.shape))
        return False

    entries = [
        {"name": "a", "threshold": 0.75, "region": [10, 20, 30, 40]},
        {"name": "b", "threshold": 0.75, "region": [20, 30, 40, 50]},
    ]
    assert poller_engine.scan_by_region(123, entries, match=fake_match) is False
    assert grabs == [(10, 20, 40, 50)]  # union box, captured once
    # entry a's top-left is the union origin; entry b is offset by (10, 10)
    assert seen[0] == ("a", (0, 0), (20, 20))
    assert seen[1] == ("b", (10, 10), (20, 20))


def test_scan_by_region_capture_failure_returns_none(monkeypatch):
    """A transient grab_region failure is None, matching scan_targets' contract."""
    def boom(hwnd, region):
        raise RuntimeError("window gone")
    monkeypatch.setattr(poller_engine.capture, "grab_region", boom)
    entries = [{"name": "a", "threshold": 0.75, "region": [0, 0, 10, 10]}]
    assert poller_engine.scan_by_region(123, entries) is None


def test_build_scaled_templates_carries_region(monkeypatch):
    monkeypatch.setattr(poller_engine.cv2, "imread",
                        lambda path, flags: np.zeros((10, 10), dtype=np.uint8))
    loaded = poller_engine.build_scaled_templates(
        {"templates": [{"name": "b", "file": "x.png", "threshold": 0.8,
                        "region": [1, 2, 30, 40]}]}, ".")
    assert loaded[0].get("region") == [1, 2, 30, 40]
    assert "region" not in poller_engine.build_scaled_templates(
        {"templates": [{"name": "b", "file": "x.png", "threshold": 0.8}]}, ".")[0]
