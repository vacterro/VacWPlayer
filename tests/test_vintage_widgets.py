"""CORE-010: the window picker must wait for a fresh click EDGE on a target
window - not consume the Pick-button press that launched the picker."""

import sys
import time
import threading
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import vintage_widgets


def _drive(states):
    it = iter(states)
    return lambda: next(it, states[-1])


def test_await_click_edge_ignores_launch_click():
    # Launch click held, then released, then a fresh press -> capture the NEW pos.
    states = [True, True, False, False, True]
    pos = (123, 456)
    captured = vintage_widgets._await_click_edge(
        _drive(states), threading.Event(), time.time() + 5,
        get_pos=lambda: pos)
    assert captured == pos


def test_await_click_edge_no_capture_while_launch_held():
    # Button never released -> the held launch click must NOT be captured (it is
    # the picker's own button, not a target window).
    states = [True, True, True, True, True]
    captured = vintage_widgets._await_click_edge(
        _drive(states), threading.Event(), time.time() + 0.3,
        get_pos=lambda: (1, 1))
    assert captured is None


def test_await_click_edge_release_then_press_captures():
    # Already released at start, then a press -> capture.
    states = [False, False, True]
    captured = vintage_widgets._await_click_edge(
        _drive(states), threading.Event(), time.time() + 5,
        get_pos=lambda: (7, 8))
    assert captured == (7, 8)


def test_await_click_edge_cancel_aborts():
    states = [False, False, True]
    cancel = threading.Event()
    cancel.set()
    captured = vintage_widgets._await_click_edge(
        _drive(states), cancel, time.time() + 5, get_pos=lambda: (1, 1))
    assert captured is None
