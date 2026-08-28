"""W2-001 regression: monotonic request ordering for Apply/DeathBuy/Stop.

Before this fix, Apply/DeathBuy/Stop were not a linear request stream:
- a busy Apply dropped the newer request entirely;
- Stop and a following Apply could share one generation, letting the older
  Stop completion kill the newer runtime.

These tests pin the new contract: every intent bumps the generation, busy
requests are retained as a pending slot (latest wins, full Apply supersedes
DeathBuy), and completions drain the pending request.
"""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import main as main_mod  # noqa: E402


class FakeRoot:
    def __init__(self):
        self.scheduled = []

    def after(self, delay, cb, *args):
        self.scheduled.append((cb, args))
        cb(*args)


class FakeStatus:
    def config(self, **kw):
        self.last = kw


class FakeDot:
    def __init__(self):
        self.fills = []

    def itemconfig(self, iid, fill):
        self.fills.append(fill)


def _make_worker():
    """Bare VacWPlayer with fake Tk surface, initialised fields set."""
    w = object.__new__(main_mod.VacWPlayer)
    w.root = FakeRoot()
    w.status_lbl = FakeStatus()
    w.ahk_dot = FakeDot()
    w._applying = False
    w._applying_epoch = None
    w._engine_epoch = 0
    w._engine_should_run = True
    w._last_applied_config = None
    w._active_runtime_config = None
    w._pending_request = None
    w._engine_lock = type("Lock", (), {"__enter__": lambda s: s,
                                       "__exit__": lambda s, *a: None})()
    return w


def test_apply_bumps_epoch():
    """Every Apply must obtain a newer generation than the previous."""
    w = _make_worker()
    # Simulate: first apply started, busy
    w._applying = True
    w._engine_epoch = 3
    w._applying_epoch = 3
    w.collect_config = lambda: None
    w.config = {"toggles": {"target_exe": "HD-Player.exe"}}
    w._engine_lock.__enter__ = lambda s: None
    w._engine_lock.__exit__ = lambda s, *a: None
    # busy path: no epoch change (captured as pending)
    w.apply_and_start()
    assert w._pending_request is not None
    assert w._pending_request[0] == "apply"
    # idle path: not busy -> bumps epoch
    w._applying = False
    before = w._engine_epoch
    w.apply_and_start()
    assert w._engine_epoch == before + 1


def test_busy_apply_retained_not_dropped():
    """A B Apply while A is generating is retained as pending, not lost."""
    w = _make_worker()
    w._applying = True
    w.collect_config = lambda: None
    w.config = {"toggles": {"target_exe": "HD-Player.exe"}}
    w.apply_and_start()
    assert w._pending_request == ("apply", {"toggles": {"target_exe": "HD-Player.exe"}})


def test_repeated_applies_coalesce_to_latest():
    """Repeated B/C Applies while busy coalesce to one pending (latest)."""
    w = _make_worker()
    w._applying = True
    w.collect_config = lambda: None
    w.config = {"v": 1}
    w.apply_and_start()
    w.config = {"v": 2}
    w.apply_and_start()
    w.config = {"v": 3}
    w.apply_and_start()
    # One pending request, latest candidate
    assert w._pending_request is not None
    assert w._pending_request[0] == "apply"
    assert w._pending_request[1] == {"v": 3}


def test_full_apply_supersedes_pending_deathbuy():
    """A DeathBuy captured while busy is replaced when a full Apply arrives."""
    w = _make_worker()
    w._applying = True
    w._active_runtime_config = {"mode": "general"}
    w._last_applied_config = {"mode": "general"}
    w.config = {"mode": "general"}
    # DeathBuy first -> pending deathbuy
    w._on_death_buy_apply()
    assert w._pending_request[0] == "deathbuy"
    # Full Apply -> supersedes the pending DeathBuy
    w.collect_config = lambda: None
    w.config = {"mode": "general", "new": True}
    w.apply_and_start()
    assert w._pending_request[0] == "apply"
    assert w._pending_request[1] == {"mode": "general", "new": True}


def test_stop_while_busy_cancels_pending_and_bumps_epoch():
    """Stop while an Apply is in flight supersedes pending work and gets a
    newer generation so the older completion cannot commit truth."""
    w = _make_worker()
    w._applying = True
    w._pending_request = ("apply", {"mode": "general"})
    before = w._engine_epoch
    w.stop_engine()
    assert w._pending_request == ("stop",)
    assert w._engine_epoch == before + 1


def test_stop_worker_owns_applying_flag():
    """A Stop that starts a worker sets _applying so a newer Apply cannot
    begin while the Stop is in flight (shared generation)."""
    import threading
    w = _make_worker()
    w._applying = False
    w._engine_epoch = 0
    w.stop_engine()
    assert w._applying is True
    assert w._applying_epoch == 1
