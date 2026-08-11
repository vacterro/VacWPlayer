"""Engine unit tests: config load, subprocess lifecycle, hwnd acquisition."""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import accept
import autocontinue
import capture
import deathwatch
import engine_config
import poller_engine
import process_runner
import surrender


ENGINES = [accept, surrender, autocontinue, deathwatch]


class FakeVar:
    def __init__(self):
        self.value = None

    def set(self, v):
        self.value = v


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_valid(engine):
    cfg = engine.load_config()
    assert isinstance(cfg, dict)
    assert "window_title" in cfg


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_missing_file_exits(engine, monkeypatch):
    def missing_open(path, *a, **k):
        raise OSError("no such file")
    monkeypatch.setattr("builtins.open", missing_open)
    with pytest.raises(SystemExit):
        engine.load_config()


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_corrupt_exits(engine, monkeypatch):
    def corrupt_json(*a, **k):
        raise ValueError("bad json")
    monkeypatch.setattr("json.load", corrupt_json)
    with pytest.raises(SystemExit):
        engine.load_config()


# --- engine config wrong-type rejection (SAIT-003 / T-079) --------------------


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_wrongtype_window_title_exits(engine, monkeypatch):
    def wrong_json(*a, **k):
        return {"window_title": 12345, "poll_interval_sec": 0.5}
    monkeypatch.setattr("json.load", wrong_json)
    with pytest.raises(SystemExit):
        engine.load_config()


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_wrongtype_poll_interval_exits(engine, monkeypatch):
    def wrong_json(*a, **k):
        return {"window_title": "X", "poll_interval_sec": "abc"}
    monkeypatch.setattr("json.load", wrong_json)
    with pytest.raises(SystemExit):
        engine.load_config()


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_valid_types_pass(engine, monkeypatch):
    good = dict(engine_config.canonical_default(
        os.path.basename(engine.CONFIG_PATH)))
    good.update({
        "monitor_enabled": False,
        "window_title": "BlueStacks App Player",
        "poll_interval_sec": 1.0,
        "click_cooldown_sec": 3.0,
    })
    monkeypatch.setattr("json.load", lambda *a, **k: good)
    cfg = engine.load_config()
    assert cfg["window_title"] == "BlueStacks App Player"


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_wrongtype_templates_exits(engine, monkeypatch):
    def wrong_json(*a, **k):
        return {"window_title": "X", "poll_interval_sec": 0.5, "templates": "notalist"}
    monkeypatch.setattr("json.load", wrong_json)
    with pytest.raises(SystemExit):
        engine.load_config()


def test_deathwatch_has_module_config_path():
    assert deathwatch.CONFIG_PATH.endswith("deathwatch_config.json")


# --- T-082: full semantic validation ----------------------------------------

def _load_with(engine, cfg, monkeypatch):
    monkeypatch.setattr("json.load", lambda *a, **k: cfg)
    return engine.load_config()


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_bool_rejected_for_numeric(engine, monkeypatch):
    """bool is int in Python - a numeric field must reject it (T-082)."""
    with pytest.raises(SystemExit):
        _load_with(engine, {"window_title": "X", "poll_interval_sec": True},
                   monkeypatch)


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_non_finite_numeric_rejected(engine, monkeypatch):
    with pytest.raises(SystemExit):
        _load_with(engine, {"window_title": "X",
                            "poll_interval_sec": float("inf")}, monkeypatch)


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_negative_poll_interval_rejected(engine, monkeypatch):
    with pytest.raises(SystemExit):
        _load_with(engine, {"window_title": "X", "poll_interval_sec": -1.0},
                   monkeypatch)


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_bad_template_threshold_rejected(engine, monkeypatch):
    cfg = {"window_title": "X", "poll_interval_sec": 1.0,
           "templates": [{"name": "A", "file": "t.png", "threshold": 1.5}],
           "buttons": []}
    with pytest.raises(SystemExit):
        _load_with(engine, cfg, monkeypatch)


@pytest.mark.parametrize("engine", ENGINES, ids=lambda m: m.__name__)
def test_load_config_template_item_non_dict_rejected(engine, monkeypatch):
    cfg = {"window_title": "X", "poll_interval_sec": 1.0,
           "templates": ["not-a-dict"], "buttons": []}
    with pytest.raises(SystemExit):
        _load_with(engine, cfg, monkeypatch)


def test_load_config_buttons_bad_region_rejected(monkeypatch):
    cfg = {"window_title": "X", "poll_interval_sec": 1.0,
           "buttons": [{"name": "b", "template": "t.png",
                        "region": [10, 10, 5, 5], "threshold": 0.8}]}
    with pytest.raises(SystemExit):
        _load_with(autocontinue, cfg, monkeypatch)


def test_load_config_buttons_region_wrong_length_rejected(monkeypatch):
    cfg = {"window_title": "X", "poll_interval_sec": 1.0,
           "buttons": [{"name": "b", "template": "t.png",
                        "region": [1, 2, 3], "threshold": 0.8}]}
    with pytest.raises(SystemExit):
        _load_with(autocontinue, cfg, monkeypatch)


def test_deathwatch_quickbuy_presses_non_int_rejected(monkeypatch):
    cfg = {"window_title": "X", "quickbuy_presses": 2.5}
    with pytest.raises(SystemExit):
        _load_with(deathwatch, cfg, monkeypatch)


def test_deathwatch_quickbuy_presses_zero_rejected(monkeypatch):
    cfg = {"window_title": "X", "quickbuy_presses": 0}
    with pytest.raises(SystemExit):
        _load_with(deathwatch, cfg, monkeypatch)


def test_deathwatch_invalid_blocked_key_rejected(monkeypatch):
    cfg = {"window_title": "X", "blocked_keys": ["F12", "F13"]}
    with pytest.raises(SystemExit):
        _load_with(deathwatch, cfg, monkeypatch)


def test_deathwatch_invalid_quickbuy_key_rejected(monkeypatch):
    cfg = {"window_title": "X", "quickbuy_key": "Shift+"}
    with pytest.raises(SystemExit):
        _load_with(deathwatch, cfg, monkeypatch)


def test_deathwatch_quickbuy_key_vk_hex_accepted(monkeypatch):
    cfg = dict(engine_config.canonical_default("deathwatch_config.json"))
    cfg["quickbuy_key"] = "vk5A"
    out = _load_with(deathwatch, cfg, monkeypatch)
    assert out["quickbuy_key"] == "vk5A"


# --- T-140: one canonical quickbuy parser, runtime consumes it ----------------

def test_quickbuy_key_vk_parser():
    assert engine_config.quickbuy_key_vk("a") == 0x41
    assert engine_config.quickbuy_key_vk("Z") == 0x5A
    assert engine_config.quickbuy_key_vk("5") == 0x35
    assert engine_config.quickbuy_key_vk("vk5A") == 0x5A
    assert engine_config.quickbuy_key_vk("Ж") is None  # ord() is not a real VK
    assert engine_config.quickbuy_key_vk("Shift+") is None
    assert engine_config.quickbuy_key_vk("vkGG") is None
    assert engine_config.quickbuy_key_vk("vk") is None
    assert engine_config.quickbuy_key_vk("") is None


def test_deathwatch_non_ascii_quickbuy_key_rejected(monkeypatch):
    """The validator must agree with the parser: a non-ASCII letter passes
    ord()-as-VK today and would feed keybd_event a meaningless code."""
    cfg = dict(engine_config.canonical_default("deathwatch_config.json"))
    cfg["quickbuy_key"] = "Ж"
    with pytest.raises(SystemExit):
        _load_with(deathwatch, cfg, monkeypatch)


def test_deathwatch_region_wrong_shape_rejected(monkeypatch):
    cfg = {"window_title": "X", "death_label_region": [1, 2, 3]}
    with pytest.raises(SystemExit):
        _load_with(deathwatch, cfg, monkeypatch)


def test_deathwatch_region_reversed_rejected(monkeypatch):
    cfg = {"window_title": "X", "death_label_region": [500, 500, 100, 100]}
    with pytest.raises(SystemExit):
        _load_with(deathwatch, cfg, monkeypatch)


def test_deathwatch_bool_field_wrong_type_rejected(monkeypatch):
    cfg = {"window_title": "X", "autobuy_after_b": "yes"}
    with pytest.raises(SystemExit):
        _load_with(deathwatch, cfg, monkeypatch)


def test_validator_never_throws_on_hostile_garbage():
    """The shared validator is total: hostile values produce problems, never a
    validator exception (no int()/float() on unchecked objects)."""
    hostile = {
        "templates": [{"name": 5, "file": [], "threshold": "abc"}],
        "buttons": [{"region": "junk", "threshold": None}],
        "death_label_region": [True, "x", float("inf"), None],
        "blocked_keys": [None, 7, {"a": 1}],
        "quickbuy_key": [1],
        "quickbuy_presses": "five",
        "match_threshold": "high",
        "poll_interval_sec": object(),
        "monitor_enabled": "yes",
    }
    problems = engine_config._collect_problems(hostile, "test.json")
    assert problems  # problems, not an exception


def test_validate_engine_config_passes_real_deathwatch():
    import json as _json
    with open(deathwatch.CONFIG_PATH, encoding="utf-8") as f:
        cfg = _json.load(f)
    assert engine_config.validate_engine_config(cfg, "deathwatch_config.json") is cfg


# --- T-139: runtime-indexed keys are REQUIRED per engine ----------------------

def test_validate_engine_config_requires_window_title():
    for name in ("accept_config.json", "surrender_config.json",
                 "autocontinue_config.json", "deathwatch_config.json"):
        with pytest.raises(SystemExit) as ex:
            engine_config.validate_engine_config({}, name)
        assert ex.value.code == 1, name


def test_validate_engine_config_requires_buttons_for_autocontinue():
    cfg = {"window_title": "Game"}
    with pytest.raises(SystemExit):
        engine_config.validate_engine_config(cfg, "autocontinue_config.json")
    cfg["buttons"] = []
    assert engine_config.validate_engine_config(cfg, "autocontinue_config.json") is cfg


def test_validate_engine_config_requires_deathwatch_core():
    cfg = {"window_title": "Game"}
    with pytest.raises(SystemExit):
        engine_config.validate_engine_config(cfg, "deathwatch_config.json")


def test_canonical_defaults_validate_clean():
    """ENGINE_DEFAULTS must satisfy each engine's own REQUIRED contract - the
    first-run files they produce are guaranteed valid."""
    for name in ("accept_config.json", "surrender_config.json",
                 "autocontinue_config.json", "deathwatch_config.json"):
        cfg = engine_config.canonical_default(name)
        assert engine_config.validate_engine_config(cfg, name) is cfg, name


def test_optional_keys_may_be_absent():
    """Required = what runtime indexes unconditionally; everything else stays
    optional for backward compatibility with older configs."""
    cfg = {"window_title": "Game", "buttons": []}
    assert engine_config.validate_engine_config(cfg, "autocontinue_config.json") is cfg


def test_canonical_default_is_a_deep_copy():
    """Mutating a returned canonical default must not leak into the source or
    into later callers (T-159): nested buttons/templates/regions included."""
    d = engine_config.canonical_default("autocontinue_config.json")
    d["buttons"][0]["region"][0] = 0
    fresh = engine_config.canonical_default("autocontinue_config.json")
    assert fresh["buttons"][0]["region"][0] == 800
    d["buttons"].pop()
    assert len(engine_config.canonical_default(
        "autocontinue_config.json")["buttons"]) == 3


# --- T-151: autocontinue buttons must satisfy runtime index contract ----------

def _ac_buttons(*buttons):
    return {"window_title": "Game", "buttons": list(buttons)}


@pytest.mark.parametrize("bad", [
    [{}],                                        # empty button object
    [{"name": "x"}],                             # no template
    [{"name": "x", "template": "t.png"}],        # no region
    [{"name": "x", "template": "t.png",
      "region": [0, 0, 10, 10]}],                # no threshold
    [{"template": "t.png", "region": [0, 0, 10, 10],
      "threshold": 0.8}],                        # no name
    [{"name": "", "template": "t.png",
      "region": [0, 0, 10, 10], "threshold": 0.8}],  # empty name
    [{"name": "x", "template": "",
      "region": [0, 0, 10, 10], "threshold": 0.8}],  # empty template
    [{"name": "x", "template": "t.png",
      "region": [800.5, 690, 1140, 765], "threshold": 0.8}],  # float coord
    [{"name": "x", "template": "t.png",
      "region": [800, True, 1140, 765], "threshold": 0.8}],   # bool coord
    [{"name": "x", "template": "t.png",
      "region": [0, 0, 10], "threshold": 0.8}],               # 3 coords
    [{"name": "x", "template": "t.png",
      "region": [0, 0, 10, 10], "threshold": 1.5}],           # threshold >1
])
def test_autocontinue_button_contract_rejects(bad):
    with pytest.raises(SystemExit):
        engine_config.validate_engine_config(_ac_buttons(*bad),
                                             "autocontinue_config.json")


def test_autocontinue_button_contract_accepts_valid():
    cfg = _ac_buttons({"name": "continue", "template": "t.png",
                       "region": [800, 690, 1140, 765], "threshold": 0.85})
    assert engine_config.validate_engine_config(cfg, "autocontinue_config.json") is cfg


def test_accept_template_fields_stay_optional():
    """accept/surrender read templates via .get() - a name-less template is
    still valid there (backward compatibility, T-151)."""
    cfg = {"window_title": "Game", "templates": [{"file": "t.png"}]}
    assert engine_config.validate_engine_config(cfg, "accept_config.json") is cfg


def test_deathwatch_region_must_be_integer_pixels():
    cfg = dict(engine_config.canonical_default("deathwatch_config.json"))
    cfg["death_label_region"] = [900.5, 118, 1165, 145]
    with pytest.raises(SystemExit):
        engine_config.validate_engine_config(cfg, "deathwatch_config.json")


def test_process_runner_start_stop_restart():
    stub = "tests/_stub_engine.py"
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner(stub, status, last, check)
    assert not pr.is_running()

    pr.start([])
    try:
        assert pr.is_running()
        pr.poll_log()
        assert status.value == "Running"
    finally:
        pr.stop()
    assert not pr.is_running()

    pr.start([])
    try:
        assert pr.is_running()
        assert status.value == "Running"
    finally:
        pr.stop()
    assert not pr.is_running()


def test_process_runner_start_is_noop_when_running():
    stub = "tests/_stub_engine.py"
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner(stub, status, last, check)
    pr.start([])
    try:
        gen_before = pr._gen
        pr.start([])
        assert pr._gen == gen_before
        assert pr.is_running()
    finally:
        pr.stop()


# --- T-171: failed spawn after a dead proc must leave proc = None -------------

def test_process_runner_failed_spawn_after_dead_proc_clears_proc(monkeypatch):
    """A dead old Popen + failed new Popen must leave self.proc = None (the
    doc promise) - never a stale reference to the dead child (T-171)."""
    stub = "tests/_stub_engine.py"
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner(stub, status, last, check)

    class _DeadProc:
        def poll(self):
            return 0  # exited

    pr.proc = _DeadProc()

    def boom(*a, **k):
        raise OSError(13, "no spawn")

    monkeypatch.setattr(process_runner.subprocess, "Popen", boom)
    assert pr.start([]) is False
    assert pr.proc is None          # not a stale dead proc
    assert check.value is False
    assert status.value.startswith("Error")


def test_process_runner_successful_spawn_replaces_dead_proc(monkeypatch):
    """A dead old proc is transparently replaced by a live spawn."""
    stub = "tests/_stub_engine.py"
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    pr = process_runner.ProcessRunner(stub, status, last, check)

    class _DeadProc:
        def poll(self):
            return 0

    pr.proc = _DeadProc()

    class _LiveProc:
        def __init__(self, *a, **k):
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def terminate(self):
            self._alive = False

        def wait(self, timeout=None):
            self._alive = False
            return 0

    monkeypatch.setattr(process_runner.subprocess, "Popen",
                        lambda *a, **k: _LiveProc())
    monkeypatch.setattr(process_runner.threading.Thread,
                        "start", lambda self: None)
    try:
        assert pr.start([]) is True
        assert pr.is_running()
    finally:
        pr.stop()


# --- T-173: stream failure must never orphan a live child ---------------------

class _TrackedProc:
    def __init__(self, alive=True):
        self.alive = alive
        self.termed = False
        self.killed = False

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False
        self.termed = True

    def wait(self, timeout=None):
        self.alive = False
        return 0

    def kill(self):
        self.alive = False
        self.killed = True


def _runner(stub="tests/_stub_engine.py"):
    status, last, check = FakeVar(), FakeVar(), FakeVar()
    return process_runner.ProcessRunner(stub, status, last, check), status, check


def test_pump_eof_live_child_is_terminated_not_orphaned():
    """Stream EOF while the child is STILL ALIVE must deliberately terminate
    it - never mark Stopped + proc=None with a live process running (T-173)."""
    pr, status, check = _runner()
    child = _TrackedProc(alive=True)
    pr.proc = child
    pr._gen = 1
    pr.q.put(("eof", 1))
    pr.poll_log()
    assert pr.proc is None
    assert child.termed is True  # deliberately terminated, not orphaned
    assert status.value == "Stopped"
    assert check.value is False


def test_pump_error_live_child_terminated_with_diagnostic():
    pr, status, check = _runner()
    child = _TrackedProc(alive=True)
    pr.proc = child
    pr._gen = 1
    pr.q.put(("pump_error", 1, "stream exploded"))
    pr.poll_log()
    assert pr.proc is None
    assert child.termed is True
    assert "Error" in str(status.value)


def test_pump_eof_exited_child_normal_stop_no_terminate():
    pr, status, check = _runner()
    child = _TrackedProc(alive=False)  # already exited
    pr.proc = child
    pr._gen = 1
    pr.q.put(("eof", 1))
    pr.poll_log()
    assert pr.proc is None
    assert child.termed is False  # exited naturally, nothing to terminate
    assert status.value == "Stopped"


def test_pump_stale_generation_events_ignored():
    pr, status, check = _runner()
    child = _TrackedProc(alive=True)
    pr.proc = child
    pr._gen = 2  # current generation
    pr.q.put(("eof", 1))  # stale pump's event
    pr.q.put(("line", 1, "old"))
    pr.poll_log()
    assert pr.proc is child  # untouched by stale events
    assert child.termed is False


def test_pump_emits_pump_error_when_stream_fails_while_alive():
    pr, _, _ = _runner()

    class _BoomStream:
        def __iter__(self):
            return self

        def __next__(self):
            raise OSError("pipe broke")

    child = _TrackedProc(alive=True)
    child.stdout = _BoomStream()
    pr._gen = 1
    pr._pump(child, 1)
    items = list(pr.q.queue)
    assert any(t[0] == "pump_error" for t in items)
    assert not any(t[0] == "done" for t in items)  # never fake-done a live child


def test_pump_emits_eof_when_stream_fails_but_child_exited():
    pr, _, _ = _runner()

    class _BoomStream:
        def __iter__(self):
            return self

        def __next__(self):
            raise OSError("pipe broke")

    child = _TrackedProc(alive=False)  # exited despite stream failure
    child.stdout = _BoomStream()
    pr._gen = 1
    pr._pump(child, 1)
    items = list(pr.q.queue)
    assert any(t[0] == "eof" for t in items)


def test_find_window_raises_when_missing(monkeypatch):
    monkeypatch.setattr(capture.win32gui, "FindWindow", lambda *a: 0)
    with pytest.raises(RuntimeError):
        capture.find_window("NoSuchWindowTitleZZZ")


def test_find_window_returns_hwnd(monkeypatch):
    monkeypatch.setattr(capture.win32gui, "FindWindow", lambda *a: 12345)
    assert capture.find_window("whatever") == 12345


# --- T-146: is_foreground + occlusion-safe grab_client_region -----------------

def test_is_foreground_uses_foreground_window(monkeypatch):
    monkeypatch.setattr(capture.win32gui, "GetForegroundWindow", lambda: 999)
    assert capture.is_foreground(999) is True
    assert capture.is_foreground(1) is False


def test_grab_client_region_crops_printwindow(monkeypatch):
    calls = []
    full = np.zeros((100, 200, 3), dtype=np.uint8)
    full[50:60, 30:40] = 7
    monkeypatch.setattr(capture, "grab", lambda h: calls.append(h) or full)
    crop = capture.grab_client_region(123, [30, 50, 40, 60])
    assert calls == [123]
    assert crop.shape == (10, 10, 3)
    assert (crop == 7).all()  # the marked pixels landed inside the crop


def test_grab_client_region_passthrough_failure(monkeypatch):
    def boom(hwnd):
        raise RuntimeError("minimized")
    monkeypatch.setattr(capture, "grab", boom)
    try:
        capture.grab_client_region(1, [0, 0, 1, 1])
        raise AssertionError("should have raised")
    except RuntimeError:
        pass


# --- T-162: grab_region must reject zero/negative sizes before GDI allocation

def test_grab_region_rejects_zero_or_negative_size(monkeypatch):
    """A zero/negative region must be rejected BEFORE any GDI handle is
    acquired (T-162) - never BitBlt a negative-size rectangle."""
    def no_acquire(*a, **k):
        raise AssertionError("GDI acquisition must not happen")
    monkeypatch.setattr(capture.win32gui, "GetWindowDC", no_acquire)
    for region in ([0, 0, 0, 0], [10, 10, 10, 10], [10, 20, 5, 5]):
        try:
            capture.grab_region(1, region)
            raise AssertionError("should have raised for %r" % region)
        except RuntimeError:
            pass


def test_grab_region_valid_size_still_acquires(monkeypatch):
    got = []
    monkeypatch.setattr(capture.win32gui, "ClientToScreen", lambda h, p: p)
    monkeypatch.setattr(capture.win32gui, "GetWindowDC", lambda h: got.append("dc") or 5)
    monkeypatch.setattr(capture.win32ui, "CreateDCFromHandle",
                        lambda h: type("DC", (), {
                            "CreateCompatibleDC": lambda self: type("DC2", (), {})()})())
    monkeypatch.setattr(capture.win32gui, "ReleaseDC", lambda *a: None)
    monkeypatch.setattr(capture.win32gui, "DeleteObject", lambda *a: None)
    try:
        capture.grab_region(1, [0, 0, 5, 5])
        raise AssertionError("BitBlt chain is stubbed - should not reach bitmap")
    except Exception:
        pass
    assert got == ["dc"]


# --- T-147: GDI/DC cleanup on every capture path (incl. mid-acquisition throw)

class _FakeDC:
    def __init__(self, cleanup, name):
        self.cleanup = cleanup
        self.name = name

    def CreateCompatibleDC(self):
        self.cleanup.append("create_dc")
        return _FakeDC(self.cleanup, "save")

    def GetSafeHdc(self):
        return 7

    def SelectObject(self, bmp):
        self.cleanup.append("select")

    def DeleteDC(self):
        self.cleanup.append("del_dc:" + self.name)


class _FakeBitmap:
    def __init__(self, cleanup):
        self.cleanup = cleanup

    def CreateCompatibleBitmap(self, dc, w, h):
        self.cleanup.append("create_bmp")

    def GetHandle(self):
        return 9

    def GetInfo(self):
        return {"bmWidth": 10, "bmHeight": 10}

    def GetBitmapBits(self, ordered):
        return b"\x00\x00\x00\x00" * 100  # 10*10*4 bytes


def _monkey_capture_ok(monkeypatch, cleanup):
    monkeypatch.setattr(capture.win32gui, "GetWindowDC",
                        lambda h: cleanup.append("get_dc") or 5)
    monkeypatch.setattr(capture.win32ui, "CreateDCFromHandle",
                        lambda h: cleanup.append("from_handle") or _FakeDC(cleanup, "mfc"))
    monkeypatch.setattr(capture.win32ui, "CreateBitmap",
                        lambda: _FakeBitmap(cleanup))
    monkeypatch.setattr(capture.win32gui, "ReleaseDC", lambda h, d: cleanup.append("release"))
    monkeypatch.setattr(capture.win32gui, "DeleteObject",
                        lambda h: cleanup.append("del_obj"))
    monkeypatch.setattr(capture.ctypes.windll.user32, "PrintWindow",
                        lambda *a, **k: 1)


def test_grab_cleans_all_on_success(monkeypatch):
    cleanup = []
    _monkey_capture_ok(monkeypatch, cleanup)
    monkeypatch.setattr(capture, "get_client_size", lambda h: (10, 10))
    img = capture.grab(123)
    assert img.shape == (10, 10, 3)
    assert cleanup == ["get_dc", "from_handle", "create_dc", "create_bmp",
                       "select", "del_obj", "del_dc:save", "del_dc:mfc",
                       "release"]


def test_grab_releases_acquired_handles_on_mid_acquisition_throw(monkeypatch):
    """A throw between GetWindowDC and SelectObject must still release
    everything already acquired (T-147) - GetWindowDC succeeded and must not
    leak."""
    cleanup = []
    monkeypatch.setattr(capture.win32gui, "GetWindowDC",
                        lambda h: cleanup.append("get_dc") or 5)
    monkeypatch.setattr(capture.win32ui, "CreateDCFromHandle",
                        lambda h: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(capture.win32gui, "ReleaseDC",
                        lambda h, d: cleanup.append("release"))
    monkeypatch.setattr(capture, "get_client_size", lambda h: (10, 10))
    try:
        capture.grab(123)
        raise AssertionError("should have raised")
    except RuntimeError:
        pass
    assert "release" in cleanup  # hwnd DC never leaks


def test_grab_rejects_zero_size_client(monkeypatch):
    monkeypatch.setattr(capture, "get_client_size", lambda h: (0, 0))
    monkeypatch.setattr(capture.win32gui, "GetWindowDC",
                        lambda h: (_ for _ in ()).throw(AssertionError("must not acquire")))
    try:
        capture.grab(123)
        raise AssertionError("should have raised")
    except RuntimeError as e:
        assert "zero" in str(e).lower()


def test_autocontinue_group_by_region():
    buttons = [
        {"name": "a", "region": [0, 0, 10, 10]},
        {"name": "b", "region": [0, 0, 10, 10]},
        {"name": "c", "region": [5, 5, 15, 15]},
    ]
    groups = autocontinue.group_by_region(buttons)
    assert len(groups) == 2
    assert len(groups[(0, 0, 10, 10)]) == 2
    assert len(groups[(5, 5, 15, 15)]) == 1


def test_accept_build_templates_scales():
    cfg = {"templates": [{"name": "Accept", "file": "templates/game_accept1.png", "threshold": 0.75}]}
    loaded = accept.build_templates(cfg)
    assert len(loaded) == 1
    assert len(loaded[0]["templates"]) == 5


def test_accept_build_templates_skips_missing():
    cfg = {"templates": [{"name": "Ghost", "file": "templates/nonexistent.png"}]}
    loaded = accept.build_templates(cfg)
    assert loaded == []


def test_build_scaled_templates_tiny_image_no_zero_dims(monkeypatch):
    """A 1x1 template scaled down computes dimension 0 (int(1*0.8)); cv2.resize
    must never be handed a zero dimension - dimensions clamp to >=1."""
    import numpy as np
    dsize_calls = []
    monkeypatch.setattr(poller_engine.cv2, "imread",
                        lambda p, f: np.ones((1, 1), dtype=np.uint8))

    def guarded_resize(img, dsize):
        dsize_calls.append(dsize)
        assert dsize[0] >= 1 and dsize[1] >= 1, f"zero dimension {dsize}"
        return img

    monkeypatch.setattr(poller_engine.cv2, "resize", guarded_resize)
    cfg = {"templates": [{"name": "t", "file": "x.png", "threshold": 0.5}]}
    loaded = poller_engine.build_scaled_templates(cfg, ".")
    assert len(loaded) == 1
    assert len(loaded[0]["templates"]) == 5  # original + 4 scales preserved
    assert all(d[0] >= 1 and d[1] >= 1 for d in dsize_calls)


def test_engines_share_poller(monkeypatch):
    calls = []
    monkeypatch.setattr(poller_engine, "run_poller", lambda *a, **k: calls.append((a, k)))
    accept.main()
    surrender.main()
    autocontinue.main()
    assert len(calls) == 3
    names = {c[0][0] for c in calls}
    assert names == {"accept", "surrender", "autocontinue"}
    configs = {c[0][2] for c in calls}
    assert configs == {"accept_config.json", "surrender_config.json", "autocontinue_config.json"}


# --- T-178: deathwatch mid-click must use validated coords + client bounds -----

def _write_main_cfg(tmp_path, monkeypatch, mid):
    import json as _j
    cfg = {"mode": "general", "toggles": {}, "combos": [], "champions": {},
           "minimap": {"mid": mid}, "afkfarm": {}}
    (tmp_path / "config.json").write_text(_j.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(deathwatch, "BASE", str(tmp_path))


def test_mid_click_coords_corrupt_config_none(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text("{corrupt", encoding="utf-8")
    monkeypatch.setattr(deathwatch, "BASE", str(tmp_path))
    assert deathwatch._mid_click_coords() is None


@pytest.mark.parametrize("mid", [
    {},
    [],
    "junk",
    {"x": "100", "y": 200},     # string x
    {"x": -5, "y": 10},         # negative
    {"x": 10, "y": -5},         # negative
    {"x": 10},                  # missing y
    {"x": True, "y": 200},      # bool is not an integer coordinate
])
def test_mid_click_coords_invalid_none(tmp_path, monkeypatch, mid):
    _write_main_cfg(tmp_path, monkeypatch, mid)
    assert deathwatch._mid_click_coords() is None


def test_mid_click_coords_valid(tmp_path, monkeypatch):
    _write_main_cfg(tmp_path, monkeypatch, {"x": 100, "y": 200})
    assert deathwatch._mid_click_coords() == (100, 200)


def test_mid_click_bounds_require_inside_client(monkeypatch):
    monkeypatch.setattr(deathwatch.capture, "get_client_size",
                        lambda h: (1920, 1080))
    assert deathwatch._client_bounds_ok(1, 100, 200) is True
    assert deathwatch._client_bounds_ok(1, 2000, 10) is False
    assert deathwatch._client_bounds_ok(1, 10, 2000) is False
    assert deathwatch._client_bounds_ok(1, 0, 0) is True


def test_mid_click_bounds_failure_no_click(monkeypatch):
    def boom(hwnd):
        raise RuntimeError("no window")
    monkeypatch.setattr(deathwatch.capture, "get_client_size", boom)
    assert deathwatch._client_bounds_ok(1, 100, 200) is False


# --- T-153: deathwatch must never trigger automation on foreign pixels --------

def test_deathwatch_grab_safe_foreground_uses_fast_path(monkeypatch):
    grabbed, safe = [], []
    monkeypatch.setattr(deathwatch.capture, "is_foreground", lambda h: True)
    monkeypatch.setattr(deathwatch.capture, "grab_region",
                        lambda h, r: grabbed.append(r) or np.zeros((1, 1, 3), dtype=np.uint8))
    monkeypatch.setattr(deathwatch.capture, "grab_client_region",
                        lambda h, r: safe.append(r) or np.zeros((1, 1, 3), dtype=np.uint8))
    deathwatch._grab_safe(123, [0, 0, 1, 1])
    assert grabbed and not safe


def test_deathwatch_grab_safe_occluded_uses_client_pixels(monkeypatch):
    """Background/occluded: the read must come from the TARGET window's own
    client area (PrintWindow), never from topmost desktop pixels - foreign
    pixels can never feed is_dead/OCR (T-153)."""
    grabbed, safe = [], []
    monkeypatch.setattr(deathwatch.capture, "is_foreground", lambda h: False)
    monkeypatch.setattr(deathwatch.capture, "grab_region",
                        lambda h, r: grabbed.append(r) or np.zeros((1, 1, 3), dtype=np.uint8))
    monkeypatch.setattr(deathwatch.capture, "grab_client_region",
                        lambda h, r: safe.append(r) or np.zeros((1, 1, 3), dtype=np.uint8))
    deathwatch._grab_safe(123, [0, 0, 1, 1])
    assert safe and not grabbed


def test_deathwatch_grab_safe_passes_failures_through(monkeypatch):
    def boom(hwnd, region):
        raise RuntimeError("window gone")
    monkeypatch.setattr(deathwatch.capture, "is_foreground", lambda h: False)
    monkeypatch.setattr(deathwatch.capture, "grab_client_region", boom)
    try:
        deathwatch._grab_safe(1, [0, 0, 1, 1])
        raise AssertionError("should have raised")
    except RuntimeError:
        pass


# --- T-154: deathwatch must not launder programming errors as lost window -----

class _SleepSentinel:
    def __init__(self, stop_after):
        self.stop_after = stop_after
        self.calls = 0

    def __call__(self, secs):
        self.calls += 1
        if self.calls >= self.stop_after:
            raise KeyboardInterrupt


def _run_deathwatch_loop(monkeypatch, grab_fn, stop_after=999):
    find_calls = []

    monkeypatch.setattr(deathwatch.engine_config, "setup_logging", lambda: None)
    monkeypatch.setattr(deathwatch.single_instance, "ensure_single_instance",
                        lambda *a, **k: None)
    monkeypatch.setattr(deathwatch.single_instance, "start_parent_watchdog",
                        lambda: None)
    monkeypatch.setattr(deathwatch.window_ctl, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(deathwatch.key_blocker, "start", lambda *a, **k: None)
    monkeypatch.setattr(deathwatch.key_blocker, "stop", lambda *a, **k: None)
    monkeypatch.setattr(deathwatch.digit_reader, "load_templates",
                        lambda *a, **k: [])
    monkeypatch.setattr(deathwatch.cv2, "imread",
                        lambda *a, **k: np.zeros((10, 10), dtype=np.uint8))
    monkeypatch.setattr(deathwatch.win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(deathwatch.capture, "find_window",
                        lambda t: find_calls.append(t) or 12345)
    monkeypatch.setattr(deathwatch.capture, "is_minimized", lambda h: False)
    monkeypatch.setattr(deathwatch.engine_config, "mtime_changed",
                        lambda p, m: (1.0, False))
    monkeypatch.setattr(deathwatch.time, "sleep", _SleepSentinel(stop_after))
    monkeypatch.setattr(deathwatch.capture, "is_foreground", lambda h: True)
    monkeypatch.setattr(deathwatch.capture, "grab_region", grab_fn)
    return find_calls


def test_deathwatch_runtime_error_reacquires(monkeypatch):
    """A capture/window RuntimeError is the only 'lost window': hwnd reset and
    re-acquire, not a crash (T-154)."""
    def grab_boom(hwnd, region):
        raise RuntimeError("window gone")
    find_calls = _run_deathwatch_loop(monkeypatch, grab_boom, stop_after=3)
    try:
        deathwatch.main(replace=False)
    except KeyboardInterrupt:
        pass  # sentinel ended the loop after the reacquire cycle
    assert len(find_calls) >= 2  # re-acquired after the lost window


def test_deathwatch_keyerror_is_fatal_not_lost_window(monkeypatch):
    def grab_boom(hwnd, region):
        raise KeyError("config bug")
    find_calls = _run_deathwatch_loop(monkeypatch, grab_boom)
    try:
        deathwatch.main(replace=False)
        raise AssertionError("KeyError was swallowed - must be FATAL (T-154)")
    except KeyError:
        pass  # correct: programming error propagates
    except KeyboardInterrupt:
        raise AssertionError("KeyError was swallowed and looped until sentinel")
    assert len(find_calls) == 1  # never treated as lost window, no reacquire


def test_deathwatch_typeerror_is_fatal_not_lost_window(monkeypatch):
    def grab_boom(hwnd, region):
        raise TypeError("programming error")
    find_calls = _run_deathwatch_loop(monkeypatch, grab_boom)
    try:
        deathwatch.main(replace=False)
        raise AssertionError("TypeError was swallowed - must be FATAL (T-154)")
    except TypeError:
        pass  # correct: programming error propagates
    except KeyboardInterrupt:
        raise AssertionError("TypeError was swallowed and looped until sentinel")
    assert len(find_calls) == 1


# --- T-155: deathwatch hot reload is transactional as a WHOLE -----------------

_LABEL_MARK = "<deathwatch-label-marker>"


def _run_deathwatch_reload(monkeypatch, make_candidate, stop_after=4):
    import json as _json
    state = {"load_calls": 0, "probes": 0, "find_titles": [],
             "imread_paths": [], "warns": 0}
    real_cfg = _json.load(open(deathwatch.CONFIG_PATH, encoding="utf-8"))

    def _load():
        state["load_calls"] += 1
        return real_cfg if state["load_calls"] == 1 else make_candidate()

    def _changed(p, m):
        state["probes"] += 1
        return (2.0, state["probes"] == 1)  # exactly one config change

    def _imread(path, flags):
        state["imread_paths"].append(path)
        if str(path).endswith("missing_label.png"):
            return None
        return _LABEL_MARK

    def _find(title):
        state["find_titles"].append(title)
        return 12345

    def _print(*a, **k):
        line = " ".join(str(x) for x in a)
        if "WARN" in line:
            state["warns"] += 1

    monkeypatch.setattr(deathwatch.engine_config, "setup_logging", lambda: None)
    monkeypatch.setattr(deathwatch.single_instance, "ensure_single_instance",
                        lambda *a, **k: None)
    monkeypatch.setattr(deathwatch.single_instance, "start_parent_watchdog",
                        lambda: None)
    monkeypatch.setattr(deathwatch.window_ctl, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(deathwatch.key_blocker, "start", lambda *a, **k: None)
    monkeypatch.setattr(deathwatch.key_blocker, "stop", lambda *a, **k: None)
    monkeypatch.setattr(deathwatch, "load_config", _load)
    monkeypatch.setattr(deathwatch.engine_config, "mtime_changed", _changed)
    monkeypatch.setattr(deathwatch.digit_reader, "load_templates",
                        lambda path: {"0": _LABEL_MARK}
                        if "missing_digits" not in str(path)
                        else (_ for _ in ()).throw(OSError(2, "no dir", path)))
    monkeypatch.setattr(deathwatch.cv2, "imread", _imread)
    monkeypatch.setattr(deathwatch.win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(deathwatch.capture, "find_window", _find)
    monkeypatch.setattr(deathwatch.capture, "is_minimized", lambda h: False)
    monkeypatch.setattr(deathwatch.time, "sleep", _SleepSentinel(stop_after))
    monkeypatch.setattr(deathwatch.capture, "is_foreground", lambda h: True)
    monkeypatch.setattr(deathwatch.capture, "grab_region",
                        lambda h, r: np.zeros((10, 10, 3), dtype=np.uint8))
    monkeypatch.setattr(deathwatch, "label_match_score",
                        lambda crop, tmpl: 0.0)
    monkeypatch.setattr("builtins.print", _print)
    return state


def _candidate(window_title="NewTitle", digits_dir="templates/digits",
               label="templates/death_label.png"):
    import json as _json
    cfg = _json.load(open(deathwatch.CONFIG_PATH, encoding="utf-8"))
    cfg["window_title"] = window_title
    cfg["digit_templates_dir"] = digits_dir
    cfg["death_label_template"] = label
    return cfg


def test_reload_bad_label_rejects_whole_candidate(monkeypatch):
    """Bad label path: old cfg stays active (window title unchanged), the
    rejection warns ONCE per revision, not per poll (T-155)."""
    state = _run_deathwatch_reload(
        monkeypatch, lambda: _candidate(label="missing_label.png"))
    try:
        deathwatch.main(replace=False)
    except KeyboardInterrupt:
        pass
    assert state["find_titles"] == ["BlueStacks App Player"] * len(state["find_titles"])
    assert "NewTitle" not in state["find_titles"]
    assert state["warns"] == 1  # one warning, not one per polling iteration


def test_reload_bad_digits_dir_rejects_whole_candidate(monkeypatch):
    state = _run_deathwatch_reload(
        monkeypatch, lambda: _candidate(digits_dir="missing_digits"))
    try:
        deathwatch.main(replace=False)
    except KeyboardInterrupt:
        pass
    assert "NewTitle" not in state["find_titles"]
    assert state["warns"] == 1


def test_reload_valid_candidate_commits_together(monkeypatch):
    """Valid candidate: cfg + resources commit together - new window title is
    watched and the new label is used, no warning."""
    state = _run_deathwatch_reload(monkeypatch, lambda: _candidate())
    try:
        deathwatch.main(replace=False)
    except KeyboardInterrupt:
        pass
    assert "NewTitle" in state["find_titles"]
    assert state["warns"] == 0
