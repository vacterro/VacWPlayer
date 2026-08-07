"""window_ctl unit tests: background click/press/release + foreground control."""

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import window_ctl


# --- set_dpi_aware ---------------------------------------------------------

def test_set_dpi_aware_success(monkeypatch):
    calls = []
    def fake_set():
        calls.append(True)
    monkeypatch.setattr(window_ctl.ctypes.windll.user32, "SetProcessDPIAware", fake_set)
    window_ctl.set_dpi_aware()
    assert calls == [True]


def test_set_dpi_aware_failure_no_raise(monkeypatch, capsys):
    def boom():
        raise OSError("denied")
    monkeypatch.setattr(window_ctl.ctypes.windll.user32, "SetProcessDPIAware", boom)
    window_ctl.set_dpi_aware()  # must not raise
    assert "SetProcessDPIAware failed" in capsys.readouterr().err


# --- minimize / maximize_and_focus / switch_to -----------------------------

def test_minimize(monkeypatch):
    shown = []
    monkeypatch.setattr(window_ctl.win32gui, "ShowWindow",
                        lambda h, c: shown.append((h, c)))
    window_ctl.minimize(7)
    assert shown == [(7, window_ctl.win32con.SW_MINIMIZE)]


def test_maximize_and_focus(monkeypatch):
    shown, focused = [], []
    monkeypatch.setattr(window_ctl.win32gui, "ShowWindow",
                        lambda h, c: shown.append((h, c)))
    monkeypatch.setattr(window_ctl, "_force_foreground", lambda h: focused.append(h))
    window_ctl.maximize_and_focus(9)
    assert shown == [(9, window_ctl.win32con.SW_MAXIMIZE)]
    assert focused == [9]


def test_switch_to_iconic_restores(monkeypatch):
    shown, focused = [], []
    monkeypatch.setattr(window_ctl.win32gui, "IsIconic", lambda h: True)
    monkeypatch.setattr(window_ctl.win32gui, "ShowWindow",
                        lambda h, c: shown.append((h, c)))
    monkeypatch.setattr(window_ctl, "_force_foreground", lambda h: focused.append(h))
    window_ctl.switch_to(3)
    assert shown == [(3, window_ctl.win32con.SW_RESTORE)]
    assert focused == [3]


def test_switch_to_visible_only_focuses(monkeypatch):
    shown, focused = [], []
    monkeypatch.setattr(window_ctl.win32gui, "IsIconic", lambda h: False)
    monkeypatch.setattr(window_ctl.win32gui, "ShowWindow",
                        lambda h, c: shown.append((h, c)))
    monkeypatch.setattr(window_ctl, "_force_foreground", lambda h: focused.append(h))
    window_ctl.switch_to(3)
    assert shown == []
    assert focused == [3]


# --- _force_foreground -----------------------------------------------------

def test_force_foreground_simple(monkeypatch):
    monkeypatch.setattr(window_ctl.win32gui, "SetForegroundWindow", lambda h: 1)
    monkeypatch.setattr(window_ctl.win32gui, "GetForegroundWindow", lambda: 0)
    monkeypatch.setattr(window_ctl.win32api, "GetCurrentThreadId", lambda: 1)
    window_ctl._force_foreground(5)  # no exception


def test_force_foreground_fallback_attaches(monkeypatch):
    calls = []
    monkeypatch.setattr(window_ctl.win32gui, "GetForegroundWindow", lambda: 100)
    monkeypatch.setattr(window_ctl.win32api, "GetCurrentThreadId", lambda: 200)
    monkeypatch.setattr(window_ctl.win32process, "GetWindowThreadProcessId",
                        lambda h: (300, 0))
    monkeypatch.setattr(window_ctl.win32process, "AttachThreadInput",
                        lambda a, b, on: calls.append((a, b, on)))
    attempts = []

    def fake_setfg(h):
        if not attempts:
            attempts.append(True)
            raise OSError("steal blocked")
        calls.append(("setfg", h))

    monkeypatch.setattr(window_ctl.win32gui, "SetForegroundWindow", fake_setfg)
    window_ctl._force_foreground(5)
    assert calls == [(200, 300, True), ("setfg", 5), (200, 300, False)]


def test_force_foreground_fallback_no_fg(monkeypatch):
    calls = []
    monkeypatch.setattr(window_ctl.win32gui, "GetForegroundWindow", lambda: 0)
    monkeypatch.setattr(window_ctl.win32api, "GetCurrentThreadId", lambda: 1)
    monkeypatch.setattr(window_ctl.win32process, "AttachThreadInput",
                        lambda a, b, on: calls.append(on))
    attempts = []

    def fake_setfg(h):
        if not attempts:
            attempts.append(True)
            raise OSError("steal blocked")
        return None

    monkeypatch.setattr(window_ctl.win32gui, "SetForegroundWindow", fake_setfg)
    window_ctl._force_foreground(5)
    assert calls == []  # no fg window -> no attach, plain set


# --- click_at --------------------------------------------------------------

@pytest.mark.parametrize("button,down,up,wparam", [
    ("left", "WM_LBUTTONDOWN", "WM_LBUTTONUP", "MK_LBUTTON"),
    ("right", "WM_RBUTTONDOWN", "WM_RBUTTONUP", "MK_RBUTTON"),
    ("middle", "WM_RBUTTONDOWN", "WM_RBUTTONUP", "MK_RBUTTON"),
])
def test_click_at(monkeypatch, button, down, up, wparam):
    sent = []
    monkeypatch.setattr(window_ctl.win32gui, "PostMessage",
                        lambda h, m, w, l: sent.append((h, m, w, l)))
    window_ctl.click_at(42, 3, 4, button=button)
    expected_lparam = (4 << 16) | 3
    assert sent[0] == (42, getattr(window_ctl.win32con, down),
                       getattr(window_ctl.win32con, wparam), expected_lparam)
    assert sent[1] == (42, getattr(window_ctl.win32con, up), 0, expected_lparam)


# --- release_mouse_buttons -------------------------------------------------

def test_release_mouse_buttons(monkeypatch):
    sent = []
    monkeypatch.setattr(window_ctl.win32gui, "PostMessage",
                        lambda h, m, w, l: sent.append((h, m, w, l)))
    window_ctl.release_mouse_buttons(7)
    assert [s[1] for s in sent] == [
        window_ctl.win32con.WM_LBUTTONUP,
        window_ctl.win32con.WM_RBUTTONUP,
        window_ctl.win32con.WM_MBUTTONUP,
    ]
    assert all(s[0] == 7 for s in sent)


def test_release_mouse_buttons_stops_on_error(monkeypatch, capsys):
    sent = []

    def fake_post(h, m, w, l):
        sent.append(m)
        if m == window_ctl.win32con.WM_LBUTTONUP:
            raise OSError("boom")
    monkeypatch.setattr(window_ctl.win32gui, "PostMessage", fake_post)
    window_ctl.release_mouse_buttons(7)
    assert len(sent) == 1
    assert "release_mouse_buttons failed" in capsys.readouterr().err


# --- key_vk ----------------------------------------------------------------

@pytest.mark.parametrize("letter,expected", [
    ("a", 0x41), ("Z", 0x5A), ("q", 0x51),
])
def test_key_vk(letter, expected):
    assert window_ctl.key_vk(letter) == expected


# --- press_key_burst -------------------------------------------------------

def test_press_key_burst_refuses_when_not_foreground(monkeypatch):
    pressed = []
    monkeypatch.setattr(window_ctl.win32gui, "GetForegroundWindow", lambda: 1)
    monkeypatch.setattr(window_ctl.win32api, "keybd_event",
                        lambda *a: pressed.append(a))
    assert window_ctl.press_key_burst(2, 0x41, times=3) is False
    assert pressed == []


def test_press_key_burst_fires_when_foreground(monkeypatch):
    pressed = []
    monkeypatch.setattr(window_ctl.win32gui, "GetForegroundWindow", lambda: 2)
    monkeypatch.setattr(window_ctl.win32api, "keybd_event",
                        lambda *a: pressed.append(a))
    monkeypatch.setattr(window_ctl.time, "sleep", lambda s: None)
    assert window_ctl.press_key_burst(2, 0x41, times=3, window_ms=150) is True
    assert len(pressed) == 6
    assert pressed[0] == (0x41, 0, 0, 0)
    assert pressed[-1] == (0x41, 0, window_ctl.win32con.KEYEVENTF_KEYUP, 0)
