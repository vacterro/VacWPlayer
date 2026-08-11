"""engine-tab JSON I/O safety (T-137): corrupt/unreadable/wrong-shape source
must never be overwritten by a partial read-modify-write; missing first-run
creates a complete canonical default; saves are atomic with .bak."""

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from engine_config import canonical_default
from tabs.tab_config import read_json, update_json, save_json


# --- read_json statuses -----------------------------------------------------

def test_read_json_missing(tmp_path):
    data, status = read_json(str(tmp_path / "nope.json"))
    assert data is None and status == "missing"


def test_read_json_corrupt(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{not json", encoding="utf-8")
    assert read_json(str(p)) == (None, "corrupt")


def test_read_json_io_error(monkeypatch, tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{}", encoding="utf-8")

    def denied(path, *a, **k):
        raise PermissionError(13, "denied", path)

    monkeypatch.setattr("builtins.open", denied)
    assert read_json(str(p)) == (None, "io_error")


def test_read_json_wrong_shape(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[1, 2]", encoding="utf-8")
    assert read_json(str(p)) == (None, "wrong_shape")


def test_read_json_ok(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    data, status = read_json(str(p))
    assert status == "ok" and data == {"a": 1}


# --- update_json: never overwrite what we could not read --------------------

def test_update_json_corrupt_aborts_no_write(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{corrupt", encoding="utf-8")
    orig = p.read_bytes()
    assert update_json(str(p), lambda c: c.update({"x": 1})) is False
    assert p.read_bytes() == orig  # byte-identical after blocked write


def test_update_json_wrong_shape_aborts_no_write(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[]", encoding="utf-8")
    orig = p.read_bytes()
    assert update_json(str(p), lambda c: c.update({"x": 1})) is False
    assert p.read_bytes() == orig


def test_update_json_permission_error_no_overwrite(monkeypatch, tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    orig = p.read_bytes()

    real_open = open

    def denied(path, *a, **k):
        mode = a[0] if a else k.get("mode", "r")
        if "w" in mode or "a" in mode or "+" in mode:
            raise PermissionError(13, "denied", path)
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", denied)
    assert update_json(str(p), lambda c: c.update({"x": 1})) is False
    assert p.read_bytes() == orig


def test_update_json_missing_with_canonical_creates_complete_default(tmp_path):
    p = tmp_path / "c.json"
    canonical = {"monitor_enabled": False, "window_title": "",
                 "quickbuy_key": "Z", "quickbuy_presses": 5}
    assert update_json(str(p), lambda c: c.update({"monitor_enabled": True}),
                       canonical_default=canonical) is True
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["monitor_enabled"] is True
    assert data["quickbuy_key"] == "Z"  # complete canonical, not partial {}
    assert data["window_title"] == ""


def test_update_json_missing_no_canonical_aborts(tmp_path):
    p = tmp_path / "c.json"
    assert update_json(str(p), lambda c: c.update({"x": 1})) is False
    assert not p.exists()


def test_update_json_preserves_unrelated_keys(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"window_title": "X", "poll_interval_sec": 0.4, "mine": 1}',
                 encoding="utf-8")
    assert update_json(str(p), lambda c: c.update({"quickbuy_key": "Z"})) is True
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["window_title"] == "X"
    assert data["mine"] == 1
    assert data["quickbuy_key"] == "Z"


def test_update_json_does_not_mutate_shared_canonical(tmp_path):
    p = tmp_path / "c.json"
    canonical = {"slots": ["a"]}
    update_json(str(p), lambda c: c["slots"].append("b"),
                canonical_default=canonical)
    assert canonical == {"slots": ["a"]}  # caller's default untouched


def test_update_json_returns_false_on_save_failure(monkeypatch, tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"a": 1}', encoding="utf-8")

    def deny_replace(src, dst):
        raise OSError(13, "denied", dst)

    monkeypatch.setattr("os.replace", deny_replace)
    assert update_json(str(p), lambda c: c.update({"x": 1})) is False
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


# --- save_json: atomic + .bak -----------------------------------------------

def test_save_json_atomic_bak(tmp_path):
    p = tmp_path / "c.json"
    assert save_json(str(p), {"a": 1}) is True
    assert save_json(str(p), {"a": 2}) is True
    bak = str(p) + ".bak"
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 2}
    assert json.loads(open(bak, encoding="utf-8").read()) == {"a": 1}


def test_save_json_non_dict_returns_false(tmp_path):
    p = tmp_path / "c.json"
    assert save_json(str(p), [1, 2]) is False
    assert not p.exists()


# --- tab save() plumbing: Death tab + Buy tab share deathwatch_config -------

class _FakeVar:
    def __init__(self, v):
        self._v = v

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _FakeWindowPicker(_FakeVar):
    def __init__(self, v):
        super().__init__(v)
        self.title_var = _FakeVar(v)


class _FakeRunner:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self, args=None):
        self.started += 1

    def stop(self):
        self.stopped += 1


_TAB_MODULES = {
    "AcceptTab": "tabs.accept_tab",
    "SurrenderTab": "tabs.surrender_tab",
    "DeathWatchTab": "tabs.death_tab",
    "AutoContinueTab": "tabs.auto_tab",
}


def _new_tab(cls_name):
    import importlib
    module = importlib.import_module(_TAB_MODULES[cls_name])
    return object.__new__(getattr(module, cls_name))


def _fake_buy_tab(path):
    from tabs.buy_tab import BuyTab
    tab = object.__new__(BuyTab)
    tab.cfg_path = str(path)
    tab.quickbuy_key = _FakeVar("Z")
    tab.quickbuy_presses = _FakeVar("5")
    tab.quickbuy_window_ms = _FakeVar("10.0")
    tab.autobuy_b = _FakeVar(False)
    tab.buy_delay_sec = _FakeVar("6.5")
    tab.buy_then_mid = _FakeVar(False)
    tab.buy_then_mid_delay = _FakeVar("0.5")
    tab.controlsend_z = _FakeVar(False)
    return tab


def _fake_death_tab(path):
    from tabs.death_tab import DeathWatchTab
    tab = object.__new__(DeathWatchTab)
    tab.cfg_path = str(path)
    tab._static_cfg = {}
    tab.monitor_var = _FakeVar(True)
    tab.window_picker = _FakeWindowPicker("BlueStacks App Player")
    tab.poll_interval = _FakeVar("0.4")
    tab.shop_buffer = _FakeVar("0.0")
    tab.restore_buffer = _FakeVar("0.0")
    tab.match_threshold = _FakeVar("0.75")
    tab.max_wait = _FakeVar("90.0")
    tab.blocked_keys = _FakeVar("F13,F14,F15")
    tab.pedal_block_sec = _FakeVar("5.0")
    tab.switch_to_work = _FakeVar(False)
    tab.click_mid = _FakeVar(False)
    tab.lock_window = _FakeVar(False)
    tab.work_window = _FakeWindowPicker("")
    return tab


def test_death_tab_corrupt_config_save_touches_nothing(tmp_path):
    p = tmp_path / "deathwatch_config.json"
    p.write_text("{corrupt", encoding="utf-8")
    tab = _fake_death_tab(p)
    assert tab.save(silent=True) is False
    assert p.read_text(encoding="utf-8") == "{corrupt"


def test_buy_tab_corrupt_config_save_touches_nothing(tmp_path):
    p = tmp_path / "deathwatch_config.json"
    p.write_text("{corrupt", encoding="utf-8")
    tab = _fake_buy_tab(p)
    assert tab.save(silent=True) is False
    assert p.read_text(encoding="utf-8") == "{corrupt"


def test_death_then_buy_save_preserves_both_subsets(tmp_path):
    p = tmp_path / "deathwatch_config.json"
    p.write_text(json.dumps({"window_title": "W", "poll_interval_sec": 0.4,
                             "quickbuy_key": "Q", "my_key": 7}),
                 encoding="utf-8")
    assert _fake_buy_tab(p).save(silent=True) is True
    assert _fake_death_tab(p).save(silent=True) is True
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["quickbuy_key"] == "Z"          # buy subset
    assert data["window_title"] == "BlueStacks App Player"  # death subset
    assert data["my_key"] == 7                  # unrelated keys survive


def test_death_tab_missing_config_creates_complete_default(tmp_path):
    p = tmp_path / "deathwatch_config.json"
    tab = _fake_death_tab(p)
    assert tab.save(silent=True) is True
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["death_label_region"] == [900, 118, 1165, 145]
    assert data["quickbuy_key"] == "Z"
    assert data["digit_templates_dir"] == "templates/digits"


def test_auto_tab_save_aborts_on_corrupt_source(tmp_path):
    from tabs.auto_tab import AutoContinueTab
    p = tmp_path / "autocontinue_config.json"
    p.write_text("{corrupt", encoding="utf-8")
    tab = object.__new__(AutoContinueTab)
    tab.cfg_path = str(p)
    tab._cfg_status = "corrupt"
    tab.monitor_var = _FakeVar(False)
    tab.window_picker = _FakeVar("")
    tab.poll_interval = _FakeVar("0.6")
    tab.click_cooldown = _FakeVar("2.5")
    tab.buttons = []
    assert tab.save(silent=True) is False
    assert p.read_text(encoding="utf-8") == "{corrupt"


def test_auto_tab_missing_config_creates_complete_default(tmp_path):
    from tabs.auto_tab import AutoContinueTab
    p = tmp_path / "autocontinue_config.json"
    tab = object.__new__(AutoContinueTab)
    tab.cfg_path = str(p)
    tab._cfg_status = "missing"
    tab.monitor_var = _FakeVar(False)
    tab.window_picker = _FakeVar("BlueStacks App Player")
    tab.poll_interval = _FakeVar("0.6")
    tab.click_cooldown = _FakeVar("2.5")
    tab.buttons = [dict(b) for b in
                   canonical_default("autocontinue_config.json")["buttons"]]
    assert tab.save(silent=True) is True
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data["buttons"]) == 3  # canonical ships the real buttons
    assert data["buttons"][0]["name"] == "continue_victory"
    assert data["monitor_enabled"] is False
    assert "window_title" in data and "poll_interval_sec" in data


def test_accept_tab_corrupt_config_save_touches_nothing(tmp_path):
    from tabs.accept_tab import AcceptTab
    p = tmp_path / "accept_config.json"
    p.write_text("{corrupt", encoding="utf-8")
    tab = object.__new__(AcceptTab)
    tab.cfg_path = str(p)
    tab._cfg_status = "corrupt"
    tab.monitor_var = _FakeVar(False)
    tab.window_picker = _FakeVar("")
    tab.poll_interval = _FakeVar("1.0")
    tab.click_cooldown = _FakeVar("3.0")
    assert tab.save(silent=True) is False
    assert p.read_text(encoding="utf-8") == "{corrupt"


def test_surrender_tab_corrupt_config_save_touches_nothing(tmp_path):
    from tabs.surrender_tab import SurrenderTab
    p = tmp_path / "surrender_config.json"
    p.write_text("{corrupt", encoding="utf-8")
    tab = object.__new__(SurrenderTab)
    tab.cfg_path = str(p)
    tab._cfg_status = "corrupt"
    tab.monitor_var = _FakeVar(False)
    tab.window_picker = _FakeVar("")
    tab.poll_interval = _FakeVar("5.0")
    tab.click_cooldown = _FakeVar("3.0")
    tab.auto_accept_var = _FakeVar(True)
    assert tab.save(silent=True) is False
    assert p.read_text(encoding="utf-8") == "{corrupt"


# --- T-141: reset must reset (canonical app defaults, not the live config) ----

def test_buy_tab_reset_uses_canonical_not_current(tmp_path):
    p = tmp_path / "deathwatch_config.json"
    p.write_text(json.dumps({
        "quickbuy_key": "X", "quickbuy_presses": 9,
        "quickbuy_window_ms": 999.0, "autobuy_after_b": True,
        "buy_after_b_delay_sec": 99.0, "autobuy_then_mid": True,
        "autobuy_then_mid_delay_sec": 9.0, "controlsend_z": True}),
        encoding="utf-8")
    tab = _fake_buy_tab(p)
    tab.reset_defaults()
    assert tab.quickbuy_key.get() == "Z"
    assert tab.quickbuy_presses.get() == "5"
    assert tab.quickbuy_window_ms.get() == "10.0"  # not 150.0 drift
    assert tab.buy_delay_sec.get() == "6.5"        # not 5.5 drift
    assert tab.autobuy_b.get() is False
    assert tab.buy_then_mid.get() is False
    assert tab.controlsend_z.get() is False


def test_death_tab_reset_uses_canonical_not_current(tmp_path):
    p = tmp_path / "deathwatch_config.json"
    p.write_text(json.dumps({
        "window_title": "W", "poll_interval_sec": 9.9,
        "shop_buffer_sec": 8.0, "restore_buffer_sec": 7.0,
        "match_threshold": 0.1, "max_death_wait_sec": 1.0,
        "blocked_keys": ["F13"], "pedal_block_sec": 99.0,
        "switch_to_work_window": True, "work_window_title": "X",
        "click_mid_on_resurrect": True, "lock_window_resurrect": True}),
        encoding="utf-8")
    tab = _fake_death_tab(p)
    tab.reset_defaults()
    assert tab.poll_interval.get() == "0.4"
    assert tab.restore_buffer.get() == "0.0"   # canonical 0.0, not 2.0 fallback
    assert tab.shop_buffer.get() == "0.0"
    assert tab.match_threshold.get() == "0.75"
    assert tab.max_wait.get() == "90.0"
    assert tab.blocked_keys.get() == "F13,F14,F15"
    assert tab.switch_to_work.get() is False
    assert tab.click_mid.get() is False
    assert tab.lock_window.get() is False


def test_auto_tab_reset_restores_canonical_buttons(tmp_path):
    from tabs.auto_tab import AutoContinueTab
    p = tmp_path / "autocontinue_config.json"
    p.write_text(json.dumps({"window_title": "W", "poll_interval_sec": 9.9,
                             "click_cooldown_sec": 9.9,
                             "buttons": [{"name": "user-added", "template": "t.png",
                                          "threshold": 0.9}]}),
                 encoding="utf-8")
    tab = object.__new__(AutoContinueTab)
    tab.cfg_path = str(p)
    tab.monitor_var = _FakeVar(True)
    tab.window_picker = _FakeWindowPicker("")
    tab.poll_interval = _FakeVar("0.6")
    tab.click_cooldown = _FakeVar("2.5")
    tab.buttons = [{"name": "user-added", "template": "t.png", "threshold": 0.9}]
    tab._refresh_tree = lambda: None
    tab._auto_save = lambda *a: None
    tab.reset_defaults()
    assert tab.poll_interval.get() == "0.6"
    assert tab.click_cooldown.get() == "2.5"
    assert [b["name"] for b in tab.buttons] == [
        "continue_victory", "continue_shared", "continue_awards"]
    # reset must not share mutable region lists with the canonical source
    tab.buttons[0]["region"][0] = 0
    assert canonical_default("autocontinue_config.json")["buttons"][0]["region"][0] == 800


# --- T-142: failed persistence must abort apply / monitor start --------------

@pytest.mark.parametrize("cls_name", list(_TAB_MODULES))
def test_trigger_apply_aborts_when_save_fails(cls_name):
    tab = _new_tab(cls_name)
    tab.save = lambda silent=False: False
    tab.runner = _FakeRunner()
    tab.monitor_var = _FakeVar(True)
    tab.event_generate = lambda *a, **k: None
    tab._trigger_apply()
    assert tab.runner.started == 0  # engine never started on failed save


@pytest.mark.parametrize("cls_name", list(_TAB_MODULES))
def test_toggle_monitor_on_aborts_and_restores_checkbox(cls_name):
    tab = _new_tab(cls_name)
    tab.save = lambda silent=False: False
    tab.runner = _FakeRunner()
    tab.monitor_var = _FakeVar(True)  # already flipped by the checkbox click
    tab.toggle_monitor()
    assert tab.runner.started == 0
    assert tab.monitor_var.get() is False  # checkbox restored to "off"


@pytest.mark.parametrize("cls_name", list(_TAB_MODULES))
def test_toggle_monitor_off_restores_checkbox_on_failed_state_save(cls_name):
    tab = _new_tab(cls_name)
    tab.runner = _FakeRunner()
    tab.monitor_var = _FakeVar(False)  # turned off
    tab.save_monitor_state = lambda: False
    tab.toggle_monitor()
    assert tab.runner.stopped == 1
    assert tab.monitor_var.get() is True  # disk still says enabled - restore


@pytest.mark.parametrize("cls_name", list(_TAB_MODULES))
def test_trigger_apply_starts_on_successful_save(cls_name):
    tab = _new_tab(cls_name)
    tab.save = lambda silent=False: True
    tab.runner = _FakeRunner()
    tab.monitor_var = _FakeVar(True)
    tab.event_generate = lambda *a, **k: None
    tab._trigger_apply()
    assert tab.runner.started == 1