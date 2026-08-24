"""PERF-006 regression: a window-picker worker must bail out of its long
blocking wait the moment a newer pick (or widget destroy) invalidates its
generation - not only at the final _apply write. _await_click_edge accepts a
`stale()` predicate for exactly this."""

import threading
from vintage_widgets import _await_click_edge


def test_await_click_edge_returns_none_when_stale():
    cancel = threading.Event()
    seen = {"n": 0}

    def get_state():
        seen["n"] += 1
        return False  # button never pressed

    # stale() True on the very first poll -> must return immediately.
    assert _await_click_edge(get_state, cancel, deadline=1e9, stale=lambda: True) is None


def test_await_click_edge_returns_none_on_cancel():
    cancel = threading.Event()
    cancel.set()

    def get_state():
        return False

    assert _await_click_edge(get_state, cancel, deadline=1e9) is None
