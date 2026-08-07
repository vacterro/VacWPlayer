"""Engine unit tests: config load, subprocess lifecycle, hwnd acquisition."""

import sys
from pathlib import Path

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
    good = {
        "monitor_enabled": False,
        "window_title": "BlueStacks App Player",
        "poll_interval_sec": 1.0,
        "click_cooldown_sec": 3.0,
        "templates": [],
        "buttons": [],
    }
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
    cfg = {"window_title": "X", "quickbuy_key": "vk5A"}
    out = _load_with(deathwatch, cfg, monkeypatch)
    assert out["quickbuy_key"] == "vk5A"


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


def test_find_window_raises_when_missing(monkeypatch):
    monkeypatch.setattr(capture.win32gui, "FindWindow", lambda *a: 0)
    with pytest.raises(RuntimeError):
        capture.find_window("NoSuchWindowTitleZZZ")


def test_find_window_returns_hwnd(monkeypatch):
    monkeypatch.setattr(capture.win32gui, "FindWindow", lambda *a: 12345)
    assert capture.find_window("whatever") == 12345


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
