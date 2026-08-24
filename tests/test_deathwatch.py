"""deathwatch restore-gating unit tests (T-202, T-204)."""

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
        "cursor_move_on_resurrect": True,
        "cursor_move_x_pct": 75,
        "cursor_move_y_pct": 25,
        "cursor_move_hold_ms": 250,
        "pvp_after_resurrect": False,
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
    monkeypatch.setattr(deathwatch, "_cursor_move_point", lambda h, cfg: (1440, 270))
    moved = []
    monkeypatch.setattr(deathwatch, "_move_cursor_tap",
                        lambda h, x, y, hold: moved.append((x, y, hold)) or True)
    monkeypatch.setattr(deathwatch, "_pvp_trigger_vk", lambda: None)
    sent_keys = []
    monkeypatch.setattr(deathwatch, "_send_key_tap", lambda h, vk: sent_keys.append(vk) or True)

    def fake_click_at(target, x, y, button="right"):
        clicked.append((target, x, y, button))

    monkeypatch.setattr(deathwatch.window_ctl, "click_at", fake_click_at)
    return clicked, moved, sent_keys


def test_resurrect_click_posts_into_game_window(monkeypatch):
    """The resurrect mid-click must go THROUGH click_at (background posted
    messages into the game window) - the never-implemented
    window_ctl.click_client_pos crashed the phase with AttributeError (T-202)."""
    hwnd = 999
    clicked, _, _ = _install_handle_death_mocks(monkeypatch, hwnd)
    deathwatch.handle_death(hwnd, _death_cfg(), templates=None)
    assert clicked == [(hwnd, 270, 293, "left")]


def test_resurrect_click_skipped_when_outside_client_bounds(monkeypatch):
    hwnd = 999
    clicked, _, _ = _install_handle_death_mocks(monkeypatch, hwnd)
    monkeypatch.setattr(deathwatch.capture, "get_client_size",
                        lambda h: (100, 100))  # mid (270,293) outside
    deathwatch.handle_death(hwnd, _death_cfg(), templates=None)
    assert clicked == []


def test_resurrect_actions_skipped_when_game_never_foreground(monkeypatch):
    hwnd = 999
    clicked, moved, sent = _install_handle_death_mocks(monkeypatch, hwnd)
    monkeypatch.setattr(deathwatch, "_wait_foreground", lambda h, **k: False)
    deathwatch.handle_death(hwnd, _death_cfg(), templates=None)
    assert clicked == []
    assert moved == []
    assert sent == []


def test_resurrect_click_off_when_not_configured(monkeypatch):
    hwnd = 999
    clicked, _, _ = _install_handle_death_mocks(monkeypatch, hwnd)
    cfg = _death_cfg()
    cfg["click_mid_on_resurrect"] = False
    deathwatch.handle_death(hwnd, cfg, templates=None)
    assert clicked == []


# --- T-204 cursor move + PvP restart -----------------------------------------

def test_cursor_move_point_computed_from_client_pct(monkeypatch):
    """T-CORE-011: cursor percentages derive from CLIENT area (not window
    frame), converted to screen via GetClientRect + ClientToScreen."""
    hwnd = 999
    # GetClientRect always returns (0, 0, w, h) where w,h are client dimensions.
    monkeypatch.setattr(deathwatch.win32gui, "GetClientRect",
                        lambda h: (0, 0, 1800, 880))
    # ClientToScreen(hwnd, (0,0)) returns the screen origin of the client area.
    monkeypatch.setattr(deathwatch.win32gui, "ClientToScreen",
                        lambda h, pt: (100, 200))
    # client_w=1800, client_h=880, sx=100, sy=200
    # 75% of 1800 = 1350, 25% of 880 = 220 -> screen (1450, 420)
    assert deathwatch._cursor_move_point(hwnd,
                                         {"cursor_move_x_pct": 75,
                                          "cursor_move_y_pct": 25}) == (1450, 420)
    # 0% of 1800 = 0, 99% of 880 = 871 -> screen (100, 1071)
    assert deathwatch._cursor_move_point(hwnd,
                                         {"cursor_move_x_pct": 0,
                                          "cursor_move_y_pct": 99}) == (100, 1071)


def test_cursor_move_tap_sends_real_lmb_with_hold(monkeypatch):
    import ctypes
    hwnd = 999
    calls = []
    monkeypatch.setattr(deathwatch.win32gui, "GetForegroundWindow", lambda: hwnd)
    monkeypatch.setattr(ctypes.windll.user32, "SetCursorPos",
                        lambda x, y: calls.append(("set", x, y)) or 1)
    monkeypatch.setattr(ctypes.windll.user32, "mouse_event",
                        lambda ev, *a: calls.append(("ev", ev)))
    monkeypatch.setattr(deathwatch.time, "sleep", lambda s: calls.append(("sleep", s)))
    assert deathwatch._move_cursor_tap(hwnd, 1440, 270, 250) is True
    assert calls[0] == ("set", 1440, 270)
    assert ("ev", 0x02) in calls  # LMB down
    assert ("ev", 0x04) in calls  # LMB up
    assert ("sleep", 0.25) in calls
    assert calls[-1] == ("ev", 0x04)


def test_cursor_move_tap_skipped_when_not_foreground(monkeypatch):
    import ctypes
    calls = []
    monkeypatch.setattr(deathwatch.win32gui, "GetForegroundWindow", lambda: 1)
    monkeypatch.setattr(ctypes.windll.user32, "SetCursorPos",
                        lambda x, y: calls.append(("set", x, y)) or 1)
    monkeypatch.setattr(ctypes.windll.user32, "mouse_event",
                        lambda ev, *a: calls.append(("ev", ev)))
    assert deathwatch._move_cursor_tap(999, 100, 100, 100) is False
    # SetCursorPos happens (non-destructive), but LMB down never fires
    # because foreground was lost JIT-before the hardware DOWN (T-CORE-007).
    assert calls[0] == ("set", 100, 100)
    assert all(c[0] != ("ev", 0x02) for c in calls)


def test_cursor_move_tap_false_when_setcursorpos_fails(monkeypatch):
    import ctypes
    hwnd = 999
    calls = []
    monkeypatch.setattr(deathwatch.win32gui, "GetForegroundWindow", lambda: hwnd)
    monkeypatch.setattr(ctypes.windll.user32, "SetCursorPos",
                        lambda x, y: calls.append(("set", x, y)) or 0)
    monkeypatch.setattr(ctypes.windll.user32, "mouse_event",
                        lambda ev, *a: calls.append(("ev", ev)))
    assert deathwatch._move_cursor_tap(hwnd, 100, 100, 100) is False
    assert ("ev", 0x02) not in calls
    assert ("ev", 0x04) not in calls


# --- T-204 PvP trigger resolution --------------------------------------------

def test_trigger_vk_mapping():
    assert deathwatch._trigger_vk("F1") == 0x70
    assert deathwatch._trigger_vk("F15") == 0x7E
    assert deathwatch._trigger_vk("F24") == 0x87
    assert deathwatch._trigger_vk("MButton") == 0x04
    assert deathwatch._trigger_vk("RButton") == 0x02
    assert deathwatch._trigger_vk("LButton") == 0x01
    assert deathwatch._trigger_vk("q") == ord("Q")  # via key_vk canonical parser
    assert deathwatch._trigger_vk("vk7E") == 0x7E
    assert deathwatch._trigger_vk("F25") is None
    assert deathwatch._trigger_vk("") is None
    assert deathwatch._trigger_vk(None) is None


def test_pvp_trigger_vk_uses_first_trigger_of_active_pvp_combo(monkeypatch, tmp_path):
    data = {"mode": "ryze", "champions": {"ryze": {}}}
    # W2-003: isolate the sidecar paths from BASE so a stray .runtime marker in
    # the dev checkout cannot make this test return None before it reaches the
    # config.json fallback it is meant to exercise.
    monkeypatch.setattr(deathwatch, "_RUNTIME_TRIGGER_PATH",
                        str(tmp_path / ".runtime_pvp_trigger"))
    monkeypatch.setattr(deathwatch, "_RUNTIME_TRIGGER_INACTIVE_PATH",
                        str(tmp_path / ".runtime_pvp_trigger_inactive"))
    monkeypatch.setattr(deathwatch.config_store, "validate_config",
                        lambda d: False)
    monkeypatch.setattr(deathwatch.ahk_builder, "_active_combos",
                        lambda d: ([{"tag": "ryze_wave", "triggers": ["F13"]},
                                    {"tag": "ryze_pvp", "triggers": ["F15", "MButton"]}], []))
    vk = deathwatch._pvp_trigger_vk()
    assert vk == 0x7E


def test_pvp_trigger_vk_none_without_pvp_combo(monkeypatch, tmp_path):
    monkeypatch.setattr(deathwatch, "_RUNTIME_TRIGGER_PATH",
                        str(tmp_path / ".runtime_pvp_trigger"))
    monkeypatch.setattr(deathwatch, "_RUNTIME_TRIGGER_INACTIVE_PATH",
                        str(tmp_path / ".runtime_pvp_trigger_inactive"))
    monkeypatch.setattr(deathwatch.config_store, "validate_config",
                        lambda d: False)
    monkeypatch.setattr(deathwatch.ahk_builder, "_active_combos",
                        lambda d: ([{"tag": "ryze_wave", "triggers": ["F13"]}], []))
    assert deathwatch._pvp_trigger_vk() is None


def test_pvp_trigger_vk_none_when_config_invalid(monkeypatch, tmp_path):
    monkeypatch.setattr(deathwatch, "_RUNTIME_TRIGGER_PATH",
                        str(tmp_path / ".runtime_pvp_trigger"))
    monkeypatch.setattr(deathwatch, "_RUNTIME_TRIGGER_INACTIVE_PATH",
                        str(tmp_path / ".runtime_pvp_trigger_inactive"))
    monkeypatch.setattr(deathwatch.config_store, "validate_config",
                        lambda d: True)
    monkeypatch.setattr(deathwatch.ahk_builder, "_active_combos",
                        lambda d: ([{"tag": "ryze_pvp", "triggers": ["F15"]}], []))
    assert deathwatch._pvp_trigger_vk() is None


def test_send_key_tap_down_and_up(monkeypatch):
    import ctypes
    sent = []
    monkeypatch.setattr(deathwatch.win32gui, "GetForegroundWindow", lambda: 999)
    monkeypatch.setattr(ctypes.windll.user32, "keybd_event",
                        lambda vk, *a: sent.append(vk))
    assert deathwatch._send_key_tap(999, 0x7E) is True
    assert sent == [0x7E, 0x7E]
    assert deathwatch._send_key_tap(999, 0) is False
    assert deathwatch._send_key_tap(999, None) is False


def test_resurrect_cursor_move_then_pvp_order(monkeypatch):
    """T-204 integration: when both flags are on, the order is mid-click,
    cursor move+tap, then the PvP trigger key."""
    hwnd = 999
    clicked, moved, sent = _install_handle_death_mocks(monkeypatch, hwnd)
    monkeypatch.setattr(deathwatch, "_pvp_trigger_vk", lambda: 0x7E)
    cfg = _death_cfg()
    cfg["cursor_move_on_resurrect"] = True
    cfg["pvp_after_resurrect"] = True
    deathwatch.handle_death(hwnd, cfg, templates=None)
    assert clicked == [(hwnd, 270, 293, "left")]
    assert moved == [(1440, 270, 250)]
    assert sent == [0x7E]


def test_resurrect_cursor_move_skipped_when_off(monkeypatch):
    hwnd = 999
    clicked, moved, sent = _install_handle_death_mocks(monkeypatch, hwnd)
    cfg = _death_cfg()
    cfg["cursor_move_on_resurrect"] = False
    cfg["pvp_after_resurrect"] = False
    deathwatch.handle_death(hwnd, cfg, templates=None)
    assert moved == []
    assert sent == []
    assert clicked == [(hwnd, 270, 293, "left")]


def test_resurrect_pvp_skipped_when_trigger_unresolvable(monkeypatch):
    hwnd = 999
    clicked, moved, sent = _install_handle_death_mocks(monkeypatch, hwnd)
    monkeypatch.setattr(deathwatch, "_pvp_trigger_vk", lambda: None)
    cfg = _death_cfg()
    cfg["pvp_after_resurrect"] = True
    deathwatch.handle_death(hwnd, cfg, templates=None)
    assert sent == []
    assert moved == [(1440, 270, 250)]
