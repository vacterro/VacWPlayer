"""key_blocker unit tests: VK map, hook callback, block window, lifecycle."""

import sys
import threading
import time
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import key_blocker as kb


class FakeKBDLL:
    def __init__(self, vk):
        self.contents = type("_contents", (), {"vkCode": vk})()


# --- VK_MAP ----------------------------------------------------------------

@pytest.mark.parametrize("name,code", [
    ("F13", 0x7C), ("F14", 0x7D), ("F15", 0x7E), ("F16", 0x7F),
    ("F17", 0x80), ("F18", 0x81), ("F19", 0x82), ("F20", 0x83),
    ("F21", 0x84), ("F22", 0x85), ("F23", 0x86), ("F24", 0x87),
])
def test_vk_map(name, code):
    assert kb.VK_MAP[name] == code


# --- _hook_proc ------------------------------------------------------------

def test_hook_proc_passes_nonzero_ncode(monkeypatch):
    calls = []
    monkeypatch.setattr(kb.user32, "CallNextHookEx",
                        lambda h, n, w, l: calls.append((n, w)) or ("ret", n, w))
    assert kb._hook_proc(1, kb.WM_KEYDOWN, 0) == ("ret", 1, kb.WM_KEYDOWN)
    assert calls == [(1, kb.WM_KEYDOWN)]


def test_hook_proc_passes_nonkey_events(monkeypatch):
    monkeypatch.setattr(kb, "_blocked_vk", {0x7E})
    calls = []
    monkeypatch.setattr(kb.user32, "CallNextHookEx",
                        lambda h, n, w, l: calls.append((n, w)) or ("ret", n, w))
    kb._hook_proc(0, 0x0103, 0)  # WM_CAPTURECHANGED-ish, not key
    assert calls == [(0, 0x0103)]


def test_hook_proc_blocks_inside_window(monkeypatch):
    monkeypatch.setattr(kb, "_blocked_vk", {0x7E})
    monkeypatch.setattr(kb, "_block_until", time.time() + 5)
    monkeypatch.setattr(kb, "_block_until_released_vk", set())
    monkeypatch.setattr(kb.ctypes, "cast",
                        lambda lp, t: FakeKBDLL(0x7E))
    assert kb._hook_proc(0, kb.WM_KEYDOWN, 0) == 1


def test_hook_proc_blocks_unreleased_then_releases(monkeypatch):
    monkeypatch.setattr(kb, "_blocked_vk", {0x7E})
    monkeypatch.setattr(kb, "_block_until", time.time() - 5)
    monkeypatch.setattr(kb, "_block_until_released_vk", {0x7E})
    monkeypatch.setattr(kb.ctypes, "cast",
                        lambda lp, t: FakeKBDLL(0x7E))
    assert kb._hook_proc(0, kb.WM_KEYDOWN, 0) == 1
    assert kb._hook_proc(0, kb.WM_KEYUP, 0) == 1
    assert kb._block_until_released_vk == set()


def test_hook_proc_passes_outside_window(monkeypatch):
    monkeypatch.setattr(kb, "_blocked_vk", {0x7E})
    monkeypatch.setattr(kb, "_block_until", time.time() - 5)
    monkeypatch.setattr(kb, "_block_until_released_vk", set())
    monkeypatch.setattr(kb.ctypes, "cast",
                        lambda lp, t: FakeKBDLL(0x7D))
    calls = []
    monkeypatch.setattr(kb.user32, "CallNextHookEx",
                        lambda h, n, w, l: calls.append((n, w)))
    kb._hook_proc(0, kb.WM_KEYDOWN, 0)
    assert calls == [(0, kb.WM_KEYDOWN)]


# --- block_until_released --------------------------------------------------

def test_block_until_released_tracks_pressed(monkeypatch):
    monkeypatch.setattr(kb, "_blocked_vk", {0x7C, 0x7D})
    monkeypatch.setattr(kb, "_block_until_released_vk", set())
    monkeypatch.setattr(kb.user32, "GetAsyncKeyState",
                        lambda vk: 0x8000 if vk == 0x7C else 0)
    kb.block_until_released()
    assert kb._block_until_released_vk == {0x7C}


# --- block_pedals_for / unblock -------------------------------------------

def test_block_pedals_for_and_unblock(monkeypatch):
    monkeypatch.setattr(kb, "_block_until", 0.0)
    kb.block_pedals_for(2.0)
    assert kb._block_until > time.time()
    kb.unblock()
    assert kb._block_until == 0.0


# --- start/stop lifecycle --------------------------------------------------

def test_start_maps_and_ignores_unknown(monkeypatch):
    monkeypatch.setattr(kb, "_blocked_vk", set())
    monkeypatch.setattr(kb, "_thread", None)
    monkeypatch.setattr(kb, "_hook_handle", 0x99)

    pumped = []
    monkeypatch.setattr(kb, "_pump", lambda: pumped.append(True))
    monkeypatch.setattr(threading.Thread, "start",
                        lambda self: pumped.append(self._target))

    kb.start(["F13", "F14", "F99"])
    assert kb._blocked_vk == {0x7C, 0x7D}
    assert len(pumped) == 1  # one Thread.start call


def test_start_noop_when_thread_alive(monkeypatch):
    fake_thread = type("FakeThread", (), {"is_alive": lambda self: True})()
    monkeypatch.setattr(kb, "_thread", fake_thread)
    monkeypatch.setattr(kb, "_pump", lambda: pytest.fail("should not pump"))
    kb.start(["F13"])  # must return without creating a second thread
    assert kb._blocked_vk == set()


def test_start_confirms_hook_and_stop_unhooks(monkeypatch):
    hook_handle = 0x1234
    monkeypatch.setattr(kb, "_blocked_vk", set())
    monkeypatch.setattr(kb, "_thread", None)
    monkeypatch.setattr(kb, "_hook_handle", hook_handle)

    monkeypatch.setattr(kb, "_pump", lambda: None)
    started = []
    monkeypatch.setattr(threading.Thread, "start",
                        lambda self: started.append(self._target))

    kb.start(["F13"])
    assert started

    unhooked = []
    monkeypatch.setattr(kb.user32, "UnhookWindowsHookEx",
                        lambda h: unhooked.append(h))
    kb._thread = None
    kb.stop()
    assert unhooked == [hook_handle]
    assert kb._hook_handle is None


def test_stop_posts_quit_to_alive_thread(monkeypatch):
    monkeypatch.setattr(kb, "_hook_handle", None)

    fake = type("FakeThread", (), {})()
    fake.ident = 0xAA
    fake.is_alive = lambda: True
    fake.join = lambda timeout=None: None

    posted = []
    monkeypatch.setattr(kb.user32, "PostThreadMessageW",
                        lambda tid, msg, w, l: posted.append((tid, msg)))
    monkeypatch.setattr(kb, "_thread", fake)

    kb.stop()
    assert posted == [(0xAA, kb.WM_QUIT)]
    assert kb._thread is None


def test_stop_skips_dead_thread(monkeypatch):
    monkeypatch.setattr(kb, "_hook_handle", None)
    fake = type("FakeThread", (), {})()
    fake.ident = 0xBB
    fake.is_alive = lambda: False
    posted = []
    monkeypatch.setattr(kb.user32, "PostThreadMessageW",
                        lambda tid, msg, w, l: posted.append(tid))
    monkeypatch.setattr(kb, "_thread", fake)
    kb.stop()
    assert posted == []
    assert kb._thread is fake  # dead thread: left alone, not nulled
