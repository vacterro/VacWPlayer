"""deathwatch restore-gating unit tests (T-202)."""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import deathwatch


# --- _wait_foreground --------------------------------------------------------

def test_wait_foreground_true_when_hwnd_foreground(monkeypatch):
    calls = []
    monkeypatch.setattr(deathwatch.win32gui, "GetForegroundWindow", lambda: 42)
    monkeypatch.setattr(deathwatch.time, "sleep", lambda s: calls.append(s))
    assert deathwatch._wait_foreground(42, timeout=3.0, settle=0.2) is True
    assert 0.2 in calls  # settle pause happened before returning True


def test_wait_foreground_false_on_timeout(monkeypatch):
    monkeypatch.setattr(deathwatch.win32gui, "GetForegroundWindow", lambda: 1)
    monkeypatch.setattr(deathwatch.time, "sleep", lambda s: None)
    assert deathwatch._wait_foreground(42, timeout=0.15, settle=0.2) is False


def test_wait_foreground_false_on_probe_failure(monkeypatch):
    def boom():
        raise RuntimeError("foreground refused")

    monkeypatch.setattr(deathwatch.win32gui, "GetForegroundWindow", boom)
    monkeypatch.setattr(deathwatch.time, "sleep", lambda s: None)
    assert deathwatch._wait_foreground(42, timeout=0.15) is False


# --- handle_death phase-3 resurrect click ------------------------------------

def _death_cfg():
    return {
        "pedal_block_sec": 0.0,
        "quickbuy_key": "Z",
        "quickbuy_presses": 0,
        "quickbuy_window_ms": 10.0,
        "shop_buffer_sec": 0.0,
        "timer_digits_region": [0, 0, 10, 10],
        "restore_buffer_sec": 10.0,   # wait clamps to 0 -> no wait loop
        "max_death_wait_sec": 90.0,
        "switch_to_work_window": False,
        "work_window_title": "",
        "click_mid_on_resurrect": True,
        "lock_window_resurrect": False,
    }


def _install_handle_death_mocks(monkeypatch, hwnd):
    clicked = []

    monkeypatch.setattr(deathwatch.key_blocker, "block_pedals_for", lambda s: None)
    monkeypatch.setattr(deathwatch.key_blocker, "unblock", lambda: None)
    monkeypatch.setattr(deathwatch.window_ctl, "press_key_burst",
                        lambda *a, **k: False)
    monkeypatch.setattr(deathwatch.time, "sleep", lambda s: None)
    monkeypatch.setattr(deathwatch, "_grab_safe", lambda h, r: None)
    monkeypatch.setattr(deathwatch.digit_reader, "read_number",
                        lambda crop, tpl: 1)
    monkeypatch.setattr(deathwatch.window_ctl, "release_mouse_buttons",
                        lambda h: None)
    monkeypatch.setattr(deathwatch.window_ctl, "minimize", lambda h: None)
    monkeypatch.setattr(deathwatch.window_ctl, "maximize_and_focus",
                        lambda h: None)
    monkeypatch.setattr(deathwatch.win32gui, "IsIconic", lambda h: False)
    monkeypatch.setattr(deathwatch.win32gui, "GetForegroundWindow", lambda: hwnd)
    monkeypatch.setattr(deathwatch.capture, "get_client_size",
                        lambda h: (1920, 1080))
    monkeypatch.setattr(deathwatch, "_mid_click_coords", lambda: (270, 293))

    def fake_click_at(target, x, y, button="right"):
        clicked.append((target, x, y, button))

    monkeypatch.setattr(deathwatch.window_ctl, "click_at", fake_click_at)
    return clicked


def test_resurrect_click_posts_into_game_window(monkeypatch):
    """The resurrect mid-click must go THROUGH click_at (background posted
    messages into the game window) - the never-implemented
    window_ctl.click_client_pos crashed the phase with AttributeError (T-202)."""
    hwnd = 999
    clicked = _install_handle_death_mocks(monkeypatch, hwnd)
    deathwatch.handle_death(hwnd, _death_cfg(), templates=None)
    assert clicked == [(hwnd, 270, 293, "left")]


def test_resurrect_click_skipped_when_outside_client_bounds(monkeypatch):
    hwnd = 999
    clicked = _install_handle_death_mocks(monkeypatch, hwnd)
    monkeypatch.setattr(deathwatch.capture, "get_client_size",
                        lambda h: (100, 100))  # mid (270,293) outside
    deathwatch.handle_death(hwnd, _death_cfg(), templates=None)
    assert clicked == []


def test_resurrect_actions_skipped_when_game_never_foreground(monkeypatch):
    hwnd = 999
    clicked = _install_handle_death_mocks(monkeypatch, hwnd)
    monkeypatch.setattr(deathwatch, "_wait_foreground", lambda h, **k: False)
    deathwatch.handle_death(hwnd, _death_cfg(), templates=None)
    assert clicked == []


def test_resurrect_click_off_when_not_configured(monkeypatch):
    hwnd = 999
    clicked = _install_handle_death_mocks(monkeypatch, hwnd)
    cfg = _death_cfg()
    cfg["click_mid_on_resurrect"] = False
    deathwatch.handle_death(hwnd, cfg, templates=None)
    assert clicked == []