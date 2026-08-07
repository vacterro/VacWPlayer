"""config_store unit tests: atomic write, .bak backup, restore, corrupt config."""

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import config_store


# --- read_raw --------------------------------------------------------------

def test_read_raw_missing_file(tmp_path):
    data, err = config_store.read_raw(str(tmp_path / "nope.json"))
    assert data is None
    assert err == "missing"


def test_read_raw_corrupt_json(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text("{not json", encoding="utf-8")
    data, err = config_store.read_raw(str(p))
    assert data is None
    assert err == "corrupt"


def test_read_raw_valid(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    data, err = config_store.read_raw(str(p))
    assert data == {"a": 1}
    assert err is None


# --- atomic_write ----------------------------------------------------------

def test_atomic_write_creates_file(tmp_path):
    p = tmp_path / "cfg.json"
    config_store.atomic_write(str(p), {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


def test_atomic_write_backs_up_previous(tmp_path):
    p = tmp_path / "cfg.json"
    config_store.atomic_write(str(p), {"a": 1})
    config_store.atomic_write(str(p), {"a": 2})
    bak = p.with_suffix(".json.bak")
    assert bak.exists()
    assert json.loads(bak.read_text(encoding="utf-8")) == {"a": 1}
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 2}


def test_atomic_write_no_bak_on_first_write(tmp_path):
    p = tmp_path / "cfg.json"
    config_store.atomic_write(str(p), {"a": 1})
    assert not p.with_suffix(".json.bak").exists()


def test_atomic_write_no_partial_on_failure(tmp_path):
    p = tmp_path / "cfg.json"
    config_store.atomic_write(str(p), {"a": 1})
    # a data object that cannot serialize must leave the old file intact
    class Bad:
        pass
    with pytest.raises(TypeError):
        config_store.atomic_write(str(p), {"a": Bad()})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


# --- restore_backup --------------------------------------------------------

def test_restore_backup(tmp_path):
    p = tmp_path / "cfg.json"
    config_store.atomic_write(str(p), {"a": 1})
    config_store.atomic_write(str(p), {"a": 2})
    p.write_text("{corrupt", encoding="utf-8")  # user-file damage
    assert config_store.restore_backup(str(p)) is True
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


def test_restore_backup_missing_returns_false(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text("{}", encoding="utf-8")
    assert config_store.restore_backup(str(p)) is False


# --- validate_config -------------------------------------------------------

def test_validate_config_ok():
    assert config_store.validate_config({
        "mode": "ryze", "lang": "ru",
        "toggles": {}, "combos": [], "champions": {},
        "minimap": {}, "afkfarm": {},
    }) == []


def test_validate_config_non_object_root():
    problems = config_store.validate_config([1, 2, 3])
    assert problems and "not an object" in problems[0]


@pytest.mark.parametrize("key", ["toggles", "combos", "champions", "minimap", "afkfarm"])
def test_validate_config_section_wrong_type(key):
    problems = config_store.validate_config({key: "not-an-object"})
    assert any(key in p for p in problems)


@pytest.mark.parametrize("key", ["mode", "lang"])
def test_validate_config_string_field_wrong_type(key):
    problems = config_store.validate_config({key: 42})
    assert any(key in p for p in problems)


# --- split_volatile / merge_volatile ----------------------------------------

def test_split_volatile_moves_window_and_champ_flags():
    cfg = {
        "mode": "ryze",
        "champions": {
            "ryze": {"enabled_pvp": True, "toggle_wave": False,
                     "trigger_pvp": "F15", "keys_pvp": "q,w,e"},
            "xin_zhao": {"enabled_jungle": True, "trigger_jungle": "F14"},
        },
        "window": {"active_tab": 2, "position": "100,200"},
    }
    stable, local = config_store.split_volatile(cfg)
    assert "window" not in stable
    assert stable["champions"]["ryze"] == {"trigger_pvp": "F15", "keys_pvp": "q,w,e"}
    assert stable["champions"]["xin_zhao"] == {"trigger_jungle": "F14"}
    assert local["window"] == {"active_tab": 2, "position": "100,200"}
    assert local["champions"]["ryze"] == {"enabled_pvp": True, "toggle_wave": False}
    assert local["champions"]["xin_zhao"] == {"enabled_jungle": True}


def test_split_volatile_empty_window_omitted():
    cfg = {"mode": "general", "window": {}, "champions": {}}
    stable, local = config_store.split_volatile(cfg)
    assert "window" not in local
    assert "window" not in stable


def test_merge_volatile_overlays_local():
    config = {
        "mode": "ryze",
        "champions": {"ryze": {"enabled_pvp": False, "trigger_pvp": "F15"}},
        "window": {"active_tab": 0},
    }
    local = {
        "window": {"active_tab": 3, "position": "50,60"},
        "champions": {"ryze": {"enabled_pvp": True}},
    }
    merged = config_store.merge_volatile(config, local)
    assert merged["window"] == {"active_tab": 3, "position": "50,60"}
    assert merged["champions"]["ryze"] == {"enabled_pvp": True, "trigger_pvp": "F15"}


def test_merge_volatile_non_dict_ignored():
    config = {"mode": "general", "window": {"active_tab": 1}}
    assert config_store.merge_volatile(config, None) is config
    assert config_store.merge_volatile(config, [1, 2]) is config


def test_split_merge_roundtrip_preserves_config():
    cfg = {
        "mode": "ryze",
        "champions": {
            "ryze": {"enabled_pvp": True, "toggle_wave": False,
                     "trigger_pvp": "F15", "keys_pvp": "q,w,e"},
        },
        "window": {"active_tab": 2, "position": "100,200"},
        "lang": "ru",
    }
    stable, local = config_store.split_volatile(cfg)
    restored = config_store.merge_volatile(dict(stable), local)
    assert restored == cfg


# --- main.load_config corrupt path (integration) ----------------------------

def test_load_config_corrupt_restores_bak(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    # two saves -> .bak exists with the first good config, then corrupt live
    good = main_mod.default_config()
    config_store.atomic_write(str(cfg_file), good)
    config_store.atomic_write(str(cfg_file), good)
    cfg_file.write_text("{corrupt", encoding="utf-8")

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert main_mod.config_warning == "restored"
    assert cfg["mode"] == good["mode"]


def test_load_config_corrupt_no_bak_returns_defaults(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    cfg_file.write_text("{corrupt", encoding="utf-8")

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert main_mod.config_warning == "corrupt"
    assert cfg["mode"] == main_mod.default_config()["mode"]


def test_load_config_missing_returns_defaults(monkeypatch, tmp_path):
    import main as main_mod
    main_mod.CONFIG_FILE = str(tmp_path / "nope.json")
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert main_mod.config_warning is None
    assert cfg["mode"] == main_mod.default_config()["mode"]


def test_load_config_applies_local_overlay(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    config_store.atomic_write(str(cfg_file), {"mode": "ryze"})
    config_store.atomic_write(str(local_file), {"window": {"active_tab": 4}})

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert cfg["window"]["active_tab"] == 4


def test_load_config_corrupt_local_ignored(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    config_store.atomic_write(str(cfg_file), {"mode": "ryze"})
    local_file.write_text("{corrupt", encoding="utf-8")

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert cfg["mode"] == "ryze"
    assert cfg["window"] == {"active_tab": 0}


def test_save_config_writes_split_files(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    cfg = {
        "mode": "ryze",
        "champions": {"ryze": {"enabled_pvp": True, "trigger_pvp": "F15"}},
        "window": {"active_tab": 1, "position": "5,5"},
    }
    main_mod.save_config(cfg)
    stable = json.loads(cfg_file.read_text(encoding="utf-8"))
    local = json.loads(local_file.read_text(encoding="utf-8"))
    assert "window" not in stable
    assert stable["champions"]["ryze"] == {"trigger_pvp": "F15"}
    assert local["window"] == {"active_tab": 1, "position": "5,5"}
    assert local["champions"]["ryze"] == {"enabled_pvp": True}
