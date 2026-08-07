"""generate_and_run chain + _apply_worker thread-boundary tests (T-081)."""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import ahk_generator as ag


def _base_cfg():
    return {
        "mode": "general",
        "toggles": {
            "target_exe": "HD-Player.exe",
            "stop_key": "s",
            "manual_aim_block": True,
            "mouse_toggle_hold": True,
        },
        "combos": [],
        "minimap": {},
        "afkfarm": {"enabled": False},
    }


def _chain_setup(monkeypatch):
    """Monkeypatch everything generate_and_run touches except the fix point."""
    intruded = {}

    def fake_find_exe():
        return "AutoHotkeyU64.exe"

    def fake_stop():
        intruded["stopped"] = True

    def fake_popen(*a, **k):
        intruded["launched"] = True
        return type("P", (), {"pid": 1234})()

    monkeypatch.setattr(ag, "find_ahk_exe", fake_find_exe)
    monkeypatch.setattr(ag, "stop_ahk", fake_stop)
    monkeypatch.setattr(ag.subprocess, "Popen", fake_popen)
    return intruded


def test_chain_malformed_combo_never_reaches_stop_or_launch(monkeypatch):
    """A combo step that fails parse_steps must abort BEFORE the old AHK is
    killed and before any launch - the last-good runtime stays alive."""
    intruded = _chain_setup(monkeypatch)
    cfg = _base_cfg()
    cfg["combos"] = [{"trigger": "F13", "keys": "q:", "interval": 50}]

    ok, msg = ag.generate_and_run(cfg)

    assert ok is False
    assert "q" in msg or "invalid combo" in msg or "Invalid" in msg
    assert "stopped" not in intruded   # never touched the old runtime
    assert "launched" not in intruded  # never launched a candidate


def test_chain_duplicate_hotkey_does_not_replace_running(monkeypatch):
    """A candidate whose generated script contains a proven same-context
    duplicate (real AHK exits 2) must NOT replace the running AHK: no stop,
    no launch, clear diagnostic."""
    intruded = _chain_setup(monkeypatch)
    cfg = _base_cfg()
    # trigger 'b' collides with the fixed ~*b release-move handler
    cfg["combos"].append({"trigger": "b", "keys": "q,e", "interval": 50})

    ok, msg = ag.generate_and_run(cfg)

    assert ok is False
    assert "conflict" in msg.lower()
    assert "stopped" not in intruded
    assert "launched" not in intruded


def test_chain_valid_config_still_launches(monkeypatch):
    intruded = _chain_setup(monkeypatch)
    ok, msg = ag.generate_and_run(_base_cfg())
    assert ok is True
    assert intruded.get("stopped")
    assert intruded.get("launched")


# --- _apply_worker / _watchdog_worker thread-boundary guards ---------------

def _make_worker(monkeypatch):
    """A bare VacWPlayer with fake Tk root/status/dot, ready for a worker."""
    import main as main_mod

    class FakeRoot:
        def __init__(self):
            self.scheduled = []

        def after(self, delay, cb):
            self.scheduled.append(cb)
            cb()

    class FakeStatus:
        def config(self, **kw):
            self.last = kw

    class FakeDot:
        def __init__(self):
            self.fills = []

        def itemconfig(self, iid, fill):
            self.fills.append(fill)

    w = object.__new__(main_mod.VacWPlayer)
    w.root = FakeRoot()
    w.status_lbl = FakeStatus()
    w.ahk_dot = FakeDot()
    w.ahk_dot_id = "dot"
    w._applying = True
    w._engine_should_run = True
    w.config = {"mode": "general"}
    monkeypatch.setattr(ag, "is_running", lambda: False)
    return w


def test_apply_worker_unexpected_exception_clears_applying(monkeypatch):
    """An exception inside the apply worker must never strand _applying=True:
    the worker schedules _apply_done(False, diagnostic) and the flag is
    released."""
    import main as main_mod

    w = _make_worker(monkeypatch)

    def boom(config):
        raise RuntimeError("explosion in the apply worker")

    main_mod.ahk_generator.generate_and_run = boom
    w._apply_worker()

    assert w._applying is False
    assert w.status_lbl.last["text"] == "Apply failed: explosion in the apply worker"


def test_watchdog_worker_unexpected_exception_clears_applying(monkeypatch):
    """The watchdog worker has the same thread-boundary guard - an exception
    there must also release _applying instead of stranding Generating."""
    import main as main_mod

    w = _make_worker(monkeypatch)

    def boom(config):
        raise RuntimeError("explosion in the watchdog worker")

    main_mod.ahk_generator.generate_and_run = boom
    w._watchdog_worker()

    assert w._applying is False
    assert "Auto-restart failed" in w.status_lbl.last["text"]


def test_apply_done_rejection_keeps_green_dot_when_last_good_runs(monkeypatch):
    """A rejected candidate must not paint the last-good runtime dead: the dot
    reflects the ACTUAL runtime state, which is still alive here."""
    from theme import TOKENS

    w = _make_worker(monkeypatch)
    monkeypatch.setattr(ag, "is_running", lambda: True)

    w._apply_done(False, "Hotkey conflict: x")

    assert w._applying is False
    assert w.ahk_dot.fills == [TOKENS["success"]]
    assert "still running" in w.status_lbl.last["text"]


def test_apply_done_rejection_red_dot_when_runtime_dead(monkeypatch):
    from theme import TOKENS

    w = _make_worker(monkeypatch)
    monkeypatch.setattr(ag, "is_running", lambda: False)

    w._apply_done(False, "Failed to launch AutoHotkey: boom")

    assert w._applying is False
    assert w.ahk_dot.fills == [TOKENS["danger"]]
    assert "still running" not in w.status_lbl.last["text"]