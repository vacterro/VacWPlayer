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
