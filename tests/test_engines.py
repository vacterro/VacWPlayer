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
