"""generate_and_run chain + _apply_worker thread-boundary tests (T-081)."""

import os
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
    # trigger 'a' collides with the ~*a untoggle handler (default set a,v)
    cfg["combos"].append({"trigger": "a", "keys": "q,e", "interval": 50})

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

        def after(self, delay, cb, *args):
            # Mirror the real Tk after(delay, cb, *args) signature: the callback
            # is invoked with the forwarded positional args.
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

    w = object.__new__(main_mod.VacWPlayer)
    w.root = FakeRoot()
    w.status_lbl = FakeStatus()
    w.ahk_dot = FakeDot()
    w.ahk_dot_id = "dot"
    w._applying = True
    w._engine_should_run = True
    w.config = {"mode": "general"}
    # W2-001: engine lock/epoch required by worker methods.
    import threading
    w._engine_lock = threading.Lock()
    w._engine_epoch = 0
    w._active_runtime_config = None  # W2-010
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

    monkeypatch.setattr(main_mod.ahk_generator, "generate_and_run", boom)
    w._apply_worker(_base_cfg(), w._engine_epoch)

    assert w._applying is False
    assert w.status_lbl.last["text"] == "Apply failed: explosion in the apply worker"


def test_watchdog_worker_unexpected_exception_clears_applying(monkeypatch):
    """The watchdog worker has the same thread-boundary guard - an exception
    there must also release _applying instead of stranding Generating."""
    import main as main_mod

    w = _make_worker(monkeypatch)

    def boom(config):
        raise RuntimeError("explosion in the watchdog worker")

    monkeypatch.setattr(main_mod.ahk_generator, "generate_and_run", boom)
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


# --- CORE-004: Apply/Stop generation (epoch) race safety ---------------------

def test_apply_done_current_generation_commits_and_clears(monkeypatch):
    """A current-generation success commits runtime truth and releases _applying."""
    import main as main_mod
    w = _make_worker(monkeypatch)
    w._applying = True
    w._applying_epoch = 5
    w._engine_epoch = 5  # not superseded
    cand = {"mode": "general"}
    w._apply_done(True, "ok", cand, epoch=5)
    assert w._applying is False
    assert w._applying_epoch is None
    assert w._active_runtime_config == cand
    assert w._last_applied_config == cand


def test_apply_done_stale_owned_clears_applying_and_ignores_truth(monkeypatch):
    """A stale callback that still owns _applying releases the flag but must NOT
    commit candidate/runtime truth (CORE-004 defect #2: Stop truth stays authoritative)."""
    import main as main_mod
    w = _make_worker(monkeypatch)
    w._applying = True
    w._applying_epoch = 5
    w._engine_epoch = 6  # Stop bumped the epoch after this worker was launched
    w._active_runtime_config = None  # Stop cleared it
    w._last_applied_config = {"mode": "old"}
    # Stop's truth must survive a stale success callback.
    w._apply_done(True, "ok", {"mode": "general"}, epoch=5)
    assert w._applying is False
    assert w._applying_epoch is None
    assert w._active_runtime_config is None  # stale success must NOT restore runtime truth
    assert w._last_applied_config == {"mode": "old"}  # candidate not overwritten


def test_apply_done_stale_not_owned_leaves_applying(monkeypatch):
    """A stale callback for an older generation must not clear _applying when a
    newer generation owns it (CORE-004: never clobber a newer generation's flag)."""
    import main as main_mod
    w = _make_worker(monkeypatch)
    w._applying = True
    w._applying_epoch = 7  # newer generation owns the flag
    w._engine_epoch = 7
    w._apply_done(True, "ok", {"mode": "general"}, epoch=5)  # stale epoch 5
    assert w._applying is True
    assert w._applying_epoch == 7
    assert w._active_runtime_config is None


def test_apply_worker_superseded_before_generate_still_finalizes(monkeypatch):
    """CORE-004 defect #1: a worker whose epoch was invalidated before it could
    generate must still post its completion (clearing _applying) instead of
    returning silently and stranding _applying=True forever."""
    import main as main_mod
    import unittest.mock as mock
    w = _make_worker(monkeypatch)
    w._applying = True
    w._applying_epoch = 5
    w._engine_epoch = 6  # Stop ran before the worker obtained the lock
    gen = mock.MagicMock(side_effect=AssertionError("generate must NOT run"))
    monkeypatch.setattr(main_mod.ahk_generator, "generate_and_run", gen)
    w._apply_worker(_base_cfg(), epoch=5)
    assert w._applying is False
    assert w._applying_epoch is None
    gen.assert_not_called()  # never generated for a superseded generation


def test_watchdog_worker_superseded_before_generate_still_finalizes(monkeypatch):
    """Same guard for the watchdog restart path."""
    import main as main_mod
    import unittest.mock as mock
    w = _make_worker(monkeypatch)
    w._applying = True
    w._applying_epoch = 5
    w._engine_epoch = 6
    gen = mock.MagicMock(side_effect=AssertionError("generate must NOT run"))
    monkeypatch.setattr(main_mod.ahk_generator, "generate_and_run", gen)
    w._watchdog_worker(cfg=_base_cfg(), epoch=5)
    assert w._applying is False
    assert w._applying_epoch is None
    gen.assert_not_called()
# --- T-181: AHK ownership must be exact-token, never command-line regex -------

def test_cmdline_launches_our_script_exact():
    ours = ag.AHK_PATH
    assert ag._cmdline_launches_our_script(
        '"C:\\Python\\AutoHotkeyU64.exe" "%s" 1234' % ours) is True


def test_cmdline_other_dir_same_name_foreign():
    assert ag._cmdline_launches_our_script(
        '"C:\\Python\\AutoHotkeyU64.exe" "C:\\Other\\wr_runtime.ahk"') is False


def test_cmdline_first_script_arg_wins():
    """AutoHotkey's script arg is the FIRST .ahk token - our path appearing as
    a LATER/unrelated argument must not claim ownership (T-181)."""
    ours = ag.AHK_PATH
    cmd = '"C:\\Python\\AutoHotkeyU64.exe" "C:\\Other\\x.ahk" "%s"' % ours
    assert ag._cmdline_launches_our_script(cmd) is False


def test_cmdline_bak_and_suffix_foreign():
    assert ag._cmdline_launches_our_script(
        '"C:\\Python\\AutoHotkeyU64.exe" "%s.bak"' % ag.AHK_PATH) is False
    assert ag._cmdline_launches_our_script(
        '"C:\\Python\\AutoHotkeyU64.exe" "C:\\x\\wr_runtime.ahk.old"') is False


def test_cmdline_no_script_arg_foreign():
    assert ag._cmdline_launches_our_script(
        '"C:\\Python\\AutoHotkeyU64.exe" /ErrorStdOut') is False


def test_find_our_pids_filters_by_exact_token(monkeypatch):
    ours = ag.AHK_PATH
    entries = [
        (101, '"C:\\Python\\AutoHotkeyU64.exe" "%s" 1' % ours),
        (202, '"C:\\Python\\AutoHotkeyU64.exe" "C:\\Other\\wr_runtime.ahk"'),
        (303, '"C:\\Python\\AutoHotkeyU64.exe" "C:\\Other\\x.ahk" "%s"' % ours),
    ]
    monkeypatch.setattr(ag, "_probe_entries", lambda ps_cmd: ("ok", entries))
    monkeypatch.setattr(ag.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(ag, "_last_scan_ts", 0.0)
    state, pids = ag._find_our_pids(force=True)
    assert state == "ok"
    assert pids == [101]  # only the exact launch wins

# --- T-189/T-190: replacement transactional after commit + stop gate ----------

def test_candidate_launch_failure_restores_last_good(monkeypatch):
    # Reset global state that may leak from prior tests (T-W2-PERF-007).
    ag._last_launched_script_hash = None
    ag._last_launched_proc = None
    intruded = {}
    monkeypatch.setattr(ag, "find_ahk_exe", lambda: "AutoHotkeyU64.exe")
    monkeypatch.setattr(ag, "_atomic_write_script",
                        lambda s: intruded.setdefault("wrote", s))
    monkeypatch.setattr(ag, "stop_ahk", lambda: "STOPPED")
    monkeypatch.setattr(ag, "_restore_previous_script",
                        lambda b: intruded.setdefault("restored", b))
    monkeypatch.setattr(ag, "_reset_scan_cache", lambda: None)
    launches = []
    real_popen = ag.subprocess.Popen

    def flaky(*a, **k):
        args = a[0]
        target = args[1] if len(args) > 1 else ""
        launches.append(target)
        # the CANDIDATE (wr_runtime.ahk) launch always fails; preflight probe
        # uses a temp path and passes through untouched
        if os.path.normcase(target) == os.path.normcase(ag.AHK_PATH):
            raise OSError(13, "no launch")
        return real_popen(*a, **k)

    monkeypatch.setattr(ag.subprocess, "Popen", flaky)
    ok, msg = ag.generate_and_run(_base_cfg())
    assert ok is False
    assert "restored" in intruded       # last-good script restored (T-189)
    assert any(os.path.normcase(t) == os.path.normcase(ag.AHK_PATH)
               for t in launches)       # candidate launch was attempted


def test_stop_unknown_aborts_replacement_no_launch(monkeypatch):
    # Reset global state that may leak from prior tests (T-W2-PERF-007).
    ag._last_launched_script_hash = None
    ag._last_launched_proc = None
    monkeypatch.setattr(ag, "find_ahk_exe", lambda: "AutoHotkeyU64.exe")
    monkeypatch.setattr(ag, "_atomic_write_script", lambda s: None)
    monkeypatch.setattr(ag, "stop_ahk", lambda: "UNKNOWN_IDENTITY")
    restored = []
    monkeypatch.setattr(ag, "_restore_previous_script",
                        lambda b: restored.append(b))
    monkeypatch.setattr(ag, "_reset_scan_cache", lambda: None)
    launched = []
    monkeypatch.setattr(ag.subprocess, "Popen",
                        lambda *a, **k: launched.append(
                            a[0][1] if len(a[0]) > 1 else "?"))
    ok, msg = ag.generate_and_run(_base_cfg())
    assert ok is False
    # preflight may spawn the probe; the CANDIDATE (our script) must not
    candidate_launches = [t for t in launched
                          if os.path.normcase(t) == os.path.normcase(ag.AHK_PATH)]
    assert candidate_launches == []     # no second runtime on unknown owner
    assert "unknown" in msg.lower()


def test_hide_stops_engine_and_blocks_resurrection(monkeypatch):
    """X (hide) must stop wr_runtime.ahk and the engine watchdog must NOT
    resurrect it afterwards. Regression for: runtime lingered after close and
    came back when manually killed (window hidden kept _engine_should_run
    True, so _engine_watchdog relaunched it every cycle)."""
    w = _make_worker(monkeypatch)
    w._applying = False
    w._engine_should_run = True
    w.tray_icon = object()          # take the stop_engine (not quit) branch
    w.root.withdraw = lambda: None  # FakeRoot has no withdraw

    stopped = []
    # KILL_FAILED keeps stop_engine out of the deathwatch import branch.
    monkeypatch.setattr(ag, "stop_ahk",
                        lambda: (stopped.append(1), "KILL_FAILED")[1])

    gen_calls = []
    monkeypatch.setattr(ag, "generate_and_run",
                        lambda c: (gen_calls.append(1), (True, "x"))[1])

    w.hide_window()

    # Close stopped the runtime and dropped the run flag.
    assert stopped, "hide_window must call stop_ahk"
    assert w._engine_should_run is False

    # Watchdog probe sees the runtime gone (False) but must NOT relaunch,
    # because the window (and therefore the engine) is closed.
    w._probe_result(False)
    assert gen_calls == [], "watchdog must not resurrect wr_runtime.ahk after hide"

